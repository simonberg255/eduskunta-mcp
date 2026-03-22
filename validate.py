"""
Validation script for the Eduskunta MCP server.

Run directly:  python validate.py
"""

import asyncio
import sys

from client import EduskuntaClient


async def run_validation() -> bool:
    client = EduskuntaClient()
    await client.initialize()

    results: list[tuple[str, str, str]] = []

    # ------------------------------------------------------------------
    # 1. list_tables — at least 5 tables, VaskiData must be present
    # ------------------------------------------------------------------
    first_doc_id: int | None = None
    first_vote_id: int | None = None

    try:
        tables = await client.get_tables()
        if len(tables) >= 5 and "VaskiData" in tables:
            results.append(
                (
                    "PASS",
                    "list_tables",
                    f"{len(tables)} tables found including VaskiData",
                )
            )
        else:
            results.append(
                (
                    "FAIL",
                    "list_tables",
                    f"{len(tables)} tables found, VaskiData present: "
                    f"{'VaskiData' in tables}. Tables: {sorted(tables)}",
                )
            )
    except Exception as exc:
        results.append(("FAIL", "list_tables", str(exc)))

    # ------------------------------------------------------------------
    # 2. search_documents — HE results, no XmlData
    # ------------------------------------------------------------------
    try:
        docs = await client.search_documents(
            year=2024, document_type="Hallituksen esitys", limit=5
        )
        tunniste_values = [d.get("Tunniste", "") for d in docs if d.get("Tunniste")]
        # Tunniste for HE docs: "HE 7/2024 vp"
        has_he = any("HE" in t and "2024" in t for t in tunniste_values)
        has_xml = any("XmlData" in d for d in docs)

        if docs and has_he and not has_xml:
            first_doc_id = int(docs[0]["Id"]) if docs[0].get("Id") else None
            results.append(
                (
                    "PASS",
                    "search_documents",
                    f"{len(docs)} docs, HE/2024 found, no XmlData. "
                    f"Sample Tunniste: {tunniste_values[:3]}",
                )
            )
        else:
            reasons = []
            if not docs:
                reasons.append("no documents returned")
            if not has_he:
                reasons.append(f"no HE 2024 in Tunniste: {tunniste_values}")
            if has_xml:
                reasons.append("XmlData found in results")
            results.append(("FAIL", "search_documents", "; ".join(reasons)))
    except Exception as exc:
        results.append(("FAIL", "search_documents", str(exc)))

    # ------------------------------------------------------------------
    # 3. search_votes — results contain AanestysId
    # ------------------------------------------------------------------
    try:
        votes = await client.search_votes(keyword="sosiaali", year=2024)
        if votes and all("AanestysId" in v for v in votes):
            first_vote_id = votes[0]["AanestysId"]
            results.append(
                (
                    "PASS",
                    "search_votes",
                    f"{len(votes)} vote sessions found, "
                    f"first AanestysId: {first_vote_id}",
                )
            )
        else:
            results.append(
                (
                    "FAIL",
                    "search_votes",
                    f"{len(votes)} results; sample: {votes[:2] if votes else 'empty'}",
                )
            )
    except Exception as exc:
        results.append(("FAIL", "search_votes", str(exc)))

    # ------------------------------------------------------------------
    # 4. get_vote_result — summary with 100–210 total votes
    # ------------------------------------------------------------------
    if first_vote_id is not None:
        try:
            result = await client.get_vote_result(int(first_vote_id))
            summary = result.get("summary", {})
            total = sum(summary.values())
            if "summary" in result and 100 <= total <= 210:
                results.append(
                    (
                        "PASS",
                        "get_vote_result",
                        f"Total votes: {total}, summary: {summary}",
                    )
                )
            else:
                results.append(
                    (
                        "FAIL",
                        "get_vote_result",
                        f"Total {total} not in 100-210 or summary missing. "
                        f"Keys: {list(result.keys())}",
                    )
                )
        except Exception as exc:
            results.append(("FAIL", "get_vote_result", str(exc)))
    else:
        results.append(
            ("FAIL", "get_vote_result", "Skipped — no AanestysId from search_votes")
        )

    # ------------------------------------------------------------------
    # 5. get_mp_list — 180–210 active MPs
    # ------------------------------------------------------------------
    try:
        mps = await client.get_mp_list(active_only=True)
        if 180 <= len(mps) <= 210:
            results.append(("PASS", "get_mp_list", f"{len(mps)} active MPs found"))
        else:
            results.append(
                (
                    "FAIL",
                    "get_mp_list",
                    f"{len(mps)} MPs found, expected 180–210",
                )
            )
    except Exception as exc:
        results.append(("FAIL", "get_mp_list", str(exc)))

    # ------------------------------------------------------------------
    # 6. get_document_text — at least 100 chars
    # ------------------------------------------------------------------
    if first_doc_id is not None:
        try:
            doc = await client.get_document_text(first_doc_id)
            text = doc.get("text", "")
            if len(text) >= 100:
                results.append(
                    (
                        "PASS",
                        "get_document_text",
                        f"Text length: {len(text)} chars, source: {doc.get('source')}",
                    )
                )
            else:
                results.append(
                    (
                        "FAIL",
                        "get_document_text",
                        f"Text too short: {len(text)} chars. "
                        f"doc keys: {list(doc.keys())}",
                    )
                )
        except Exception as exc:
            results.append(("FAIL", "get_document_text", str(exc)))
    else:
        results.append(
            (
                "FAIL",
                "get_document_text",
                "Skipped — no document Id from search_documents",
            )
        )

    await client.close()

    # ------------------------------------------------------------------
    # Print summary
    # ------------------------------------------------------------------
    print()
    print("=" * 65)
    print("  EDUSKUNTA MCP VALIDATION RESULTS")
    print("=" * 65)
    for status, name, reason in results:
        marker = "✓" if status == "PASS" else "✗"
        print(f"  {marker} [{status}] {name}")
        print(f"        {reason}")
    print("=" * 65)
    passed = sum(1 for s, _, _ in results if s == "PASS")
    print(f"  Results: {passed}/{len(results)} passed")
    print("=" * 65)
    print()

    return passed == len(results)


if __name__ == "__main__":
    success = asyncio.run(run_validation())
    sys.exit(0 if success else 1)
