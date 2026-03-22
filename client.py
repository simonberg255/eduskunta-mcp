import asyncio
import logging
import re

import httpx

from parsers import (
    extract_html_href,
    extract_pdf_text,
    extract_xml_text,
    extract_year_from_tunniste,
    first_identifier,
    rows_to_dicts,
    strip_xml_tags,
)

logger = logging.getLogger(__name__)

BASE_URL = "https://avoindata.eduskunta.fi/api/v1"
HEADERS = {
    "User-Agent": "intric-eduskunta-mcp/1.0",
    "Accept": "application/json",
}

# Document type keywords used as vaski/text filter when no keyword is given
_DOC_TYPE_FILTER: dict[str, str] = {
    "hallituksen esitys": "HE",
    "lakialoite": "LA",
    "kirjallinen kysymys": "KK",
    "valiokunnan mietintö": "mietintö",
    "valiokunnan lausunto": "lausunto",
}

# Abbreviation prefixes that identify document types in an EduskuntaTunnus
_DOC_TYPE_PREFIXES: dict[str, list[str]] = {
    "hallituksen esitys": ["HE "],
    "lakialoite": ["LA "],
    "kirjallinen kysymys": ["KK "],
    # Committee reports / opinions match any committee prefix ending in VM/VL
    "valiokunnan mietintö": [],   # checked via regex below
    "valiokunnan lausunto": [],
}


def _tunniste_matches_type(tunniste: str, document_type: str) -> bool:
    """Return True if the leading identifier in tunniste matches document_type."""
    if not document_type:
        return True
    dt = document_type.lower()
    first = first_identifier(tunniste)
    prefixes = _DOC_TYPE_PREFIXES.get(dt, [])
    if prefixes:
        return any(first.startswith(p) for p in prefixes)
    if "mietintö" in dt:
        return bool(re.match(r"[A-Za-z]+VM\s+\d+/\d+", first))
    if "lausunto" in dt:
        return bool(re.match(r"[A-Za-z]+VL\s+\d+/\d+", first))
    return True  # no filter when type is unknown


class EduskuntaClient:
    def __init__(self):
        self._client: httpx.AsyncClient | None = None
        self._tables_cache: list[str] | None = None

    async def _ensure_client(self):
        if self._client is None:
            self._client = httpx.AsyncClient(
                base_url=BASE_URL,
                headers=HEADERS,
                timeout=30.0,
            )

    async def initialize(self):
        """Create HTTP client and warm the table cache."""
        await self._ensure_client()
        try:
            await self.get_tables()
            logger.info("EduskuntaClient ready")
        except Exception as exc:
            logger.warning("Could not fetch tables at startup: %s", exc)

    async def close(self):
        if self._client:
            await self._client.aclose()
            self._client = None

    # ------------------------------------------------------------------ #
    # Internal HTTP helpers                                                #
    # ------------------------------------------------------------------ #

    async def _get(self, path: str, params: dict | None = None) -> dict | list:
        """GET with automatic 429 retry."""
        await self._ensure_client()
        assert self._client is not None

        for attempt in range(2):
            resp = await self._client.get(path, params=params)
            if resp.status_code == 429:
                if attempt == 0:
                    logger.warning("Rate limited (429), waiting 10 s…")
                    await asyncio.sleep(10)
                    continue
                resp.raise_for_status()
            resp.raise_for_status()
            return resp.json()

        raise RuntimeError("Request failed after retry")

    async def fetch_all_rows(
        self,
        table: str,
        column_name: str | None = None,
        column_value: str | None = None,
        max_pages: int = 50,
    ) -> list[dict]:
        """Paginate a table using hasMore; always convert via rows_to_dicts."""
        results: list[dict] = []
        page = 0

        while page < max_pages:
            params: dict = {"page": page, "perPage": 100}
            if column_name and column_value is not None:
                params["columnName"] = column_name
                params["columnValue"] = str(column_value)

            data = await self._get(f"/tables/{table}/rows", params=params)
            results.extend(rows_to_dicts(data))  # type: ignore[arg-type]

            if not data.get("hasMore", False):  # type: ignore[union-attr]
                break
            page += 1
            await asyncio.sleep(0.5)

        return results

    # ------------------------------------------------------------------ #
    # Domain methods                                                       #
    # ------------------------------------------------------------------ #

    async def get_tables(self) -> list[str]:
        """Return (and cache) all available table names from GET /tables/."""
        if self._tables_cache is not None:
            return self._tables_cache

        data = await self._get("/tables/")
        if isinstance(data, list):
            self._tables_cache = [str(t) for t in data]
        else:
            self._tables_cache = []

        expected = {
            "VaskiData",
            "SaliDBAanestys",
            "SaliDBAanestysEdustaja",
            "MemberOfParliament",
        }
        for name in expected:
            if name not in self._tables_cache:
                logger.warning("Expected table '%s' not in /tables/ response", name)

        return self._tables_cache

    # ----- search_documents -----

    async def search_documents(
        self,
        year: int | None = None,
        document_type: str | None = None,
        committee: str | None = None,
        limit: int = 20,
    ) -> list[dict]:
        """Search parliament documents via /vaski/text. Never returns XmlData."""
        dt_lower = (document_type or "").lower()

        # Derive a non-empty filter for the full-text search endpoint
        filter_text = _DOC_TYPE_FILTER.get(dt_lower, document_type or "HE")
        if committee and not filter_text:
            filter_text = committee

        params: dict = {
            "page": 0,
            "perPage": 100,
            "filter": filter_text,
            "languageCode": "fi",
        }
        if document_type:
            params["type"] = document_type
        if committee:
            params["committee"] = committee

        results: list[dict] = []
        page = 0
        max_pages = 20

        while page < max_pages and len(results) < limit:
            params["page"] = page
            data = await self._get("/vaski/text", params=params)
            rows = rows_to_dicts(data)  # type: ignore[arg-type]

            for row in rows:
                tunniste = (row.get("EduskuntaTunnus") or "").strip()

                # Year filter: check first identifier contains /{year} vp|rd
                if year is not None:
                    yr_str = str(year)
                    if yr_str not in tunniste:
                        continue
                    first = first_identifier(tunniste)
                    if f"/{yr_str} vp" not in first and f"/{yr_str} rd" not in first:
                        continue

                # Document type filter: first identifier must match expected prefix
                if document_type and not _tunniste_matches_type(tunniste, document_type):
                    continue

                # Committee filter: tunniste should mention the committee
                if committee and committee not in tunniste:
                    continue

                # Clean XML from title / type fields
                results.append(
                    {
                        "Id": row.get("Id"),
                        "Tunniste": tunniste,
                        "NimiSuomi": strip_xml_tags(row.get("NimekeTeksti") or ""),
                        "AsiakirjatyyppiNimi": strip_xml_tags(
                            row.get("AsiakirjatyyppiNimi") or ""
                        ),
                        "ValtiopaivaVuosi": extract_year_from_tunniste(tunniste),
                        "ToimielinLyhenne": "",
                        "PdfLink": extract_html_href(row.get("Url") or ""),
                    }
                )
                if len(results) >= limit:
                    break

            if not data.get("hasMore", False):  # type: ignore[union-attr]
                break
            page += 1
            await asyncio.sleep(0.5)

        return results[:limit]

    # ----- get_document_text -----

    async def get_document_text(self, document_id: int) -> dict:
        """Fetch VaskiData row by Id; return clean text from XML or PDF."""
        rows = await self.fetch_all_rows(
            "VaskiData",
            column_name="Id",
            column_value=str(document_id),
            max_pages=1,
        )

        if not rows:
            return {"error": f"Document with Id={document_id} not found"}

        row = rows[0]
        xml_data = row.get("XmlData") or ""
        text = ""
        source = "xml"

        if xml_data:
            text = extract_xml_text(xml_data)

        if len(text) < 100:
            # Fallback: get PDF URL from Attachment table
            attachment_group_id = row.get("AttachmentGroupId")
            if attachment_group_id:
                try:
                    attachments = await self.fetch_all_rows(
                        "Attachment",
                        column_name="AttachmentGroupId",
                        column_value=str(attachment_group_id),
                        max_pages=1,
                    )
                    for att in attachments:
                        raw_url = att.get("Url") or ""
                        # URL may be wrapped in quotes: "https://..."
                        pdf_url = raw_url.strip('"\'')
                        if pdf_url.startswith("http"):
                            async with httpx.AsyncClient(
                                headers=HEADERS,
                                timeout=60.0,
                                follow_redirects=True,
                            ) as pdf_client:
                                resp = await pdf_client.get(pdf_url)
                                resp.raise_for_status()
                                text = extract_pdf_text(resp.content)
                                source = "pdf"
                            if text:
                                break
                except Exception as exc:
                    logger.warning(
                        "PDF extraction failed for AttachmentGroupId=%s: %s",
                        attachment_group_id,
                        exc,
                    )

        return {
            "Id": row.get("Id"),
            "Tunniste": row.get("Eduskuntatunnus"),
            "NimiSuomi": "",  # not available as a plain column in VaskiData
            "AsiakirjatyyppiNimi": "",
            "text": text,
            "source": source,
        }

    # ----- search_votes -----

    async def search_votes(
        self,
        keyword: str,
        year: int | None = None,
    ) -> list[dict]:
        """Search SaliDBAanestys vote sessions by keyword in KohtaOtsikko."""
        # Server-side filter by year to keep pages manageable
        col_name = "IstuntoVPVuosi" if year is not None else None
        col_value = str(year) if year is not None else None

        rows = await self.fetch_all_rows(
            "SaliDBAanestys",
            column_name=col_name,
            column_value=col_value,
            max_pages=50,
        )

        keyword_lower = keyword.lower()
        results: list[dict] = []

        for row in rows:
            # Use Finnish language rows only (KieliId=1)
            if str(row.get("KieliId", "1")) != "1":
                continue

            title = (row.get("KohtaOtsikko") or "").lower()
            alt_title = (row.get("AanestysOtsikko") or "").lower()

            if keyword_lower not in title and keyword_lower not in alt_title:
                continue

            results.append(
                {
                    "AanestysId": row.get("AanestysId"),
                    "KohtaOtsikko": row.get("KohtaOtsikko"),
                    "Aanestysaika": row.get("AanestysAlkuaika"),
                    "Istunto": row.get("AanestysPoytakirja"),
                }
            )

            if len(results) >= 50:
                break

        return results

    # ----- get_vote_result -----

    async def get_vote_result(self, aanestys_id: int) -> dict:
        """Get per-MP vote breakdown for a plenary vote session."""
        votes = await self.fetch_all_rows(
            "SaliDBAanestysEdustaja",
            column_name="AanestysId",
            column_value=str(aanestys_id),
        )

        summary: dict[str, int] = {"Jaa": 0, "Ei": 0, "Poissa": 0, "Tyhjaa": 0}
        by_party: dict[str, dict[str, int]] = {}
        vote_list: list[dict] = []

        for v in votes:
            first_name = (v.get("EdustajaEtunimi") or "").strip()
            last_name = (v.get("EdustajaSukunimi") or "").strip()
            name = f"{first_name} {last_name}".strip()
            party = (v.get("EdustajaRyhmaLyhenne") or "Unknown").strip()
            vote_val = (v.get("EdustajaAanestys") or "").strip()

            if vote_val in summary:
                summary[vote_val] += 1

            if party not in by_party:
                by_party[party] = {"Jaa": 0, "Ei": 0, "Poissa": 0, "Tyhjaa": 0}
            if vote_val in by_party[party]:
                by_party[party][vote_val] += 1

            vote_list.append({"name": name, "party": party, "vote": vote_val})

        return {
            "aanestys_id": aanestys_id,
            "summary": summary,
            "by_party": by_party,
            "votes": vote_list,
        }

    # ----- get_mp_list -----

    async def get_mp_list(self, active_only: bool = True) -> list[dict]:
        """Return MPs from MemberOfParliament, optionally filtered to active."""
        rows = await self.fetch_all_rows("MemberOfParliament")

        results: list[dict] = []
        for row in rows:
            if active_only:
                xml = row.get("XmlDataFi") or ""
                if "<EdustajantoimenTila>Nykyinen</EdustajantoimenTila>" not in xml:
                    continue

                # Extract current constituency from XML
                vaalipiiri_m = re.search(
                    r"<NykyinenVaalipiiri><Nimi>(.*?)</Nimi>", xml
                )
                vaalipiiri = vaalipiiri_m.group(1) if vaalipiiri_m else ""
            else:
                vaalipiiri = ""

            results.append(
                {
                    "HenkiloNumero": row.get("personId"),
                    "Sukunimi": (row.get("lastname") or "").strip(),
                    "Etunimi": (row.get("firstname") or "").strip(),
                    "Puolue": (row.get("party") or "").strip(),
                    "Vaalipiiri": vaalipiiri,
                }
            )

        return results
