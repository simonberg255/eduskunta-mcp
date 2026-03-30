# Eduskunta MCP Server

An MCP server that connects an AI assistant to the Finnish Parliament's open data API at [avoindata.eduskunta.fi](https://avoindata.eduskunta.fi). It provides structured access to parliamentary documents (government bills, committee reports, written questions), plenary vote records with per-MP breakdowns, and biographical data on current Members of Parliament — all sourced directly from the Parliament's official public API with no authentication required.

## Tools

| Tool | Description |
|---|---|
| `list_tables` | List all available tables in the Finnish Parliament open data API |
| `search_documents` | Search parliamentary documents by year, type, and committee |
| `get_document_text` | Fetch the full text of a document by its Id (XML or PDF fallback) |
| `search_votes` | Search plenary vote sessions by keyword and optional year |
| `get_vote_result` | Get per-MP vote breakdown for a specific vote session |
| `get_mp_list` | Get currently serving (or all) Members of Parliament |

## How it works

1. **Discover** — call `list_tables` to see all available data sources, or go directly to a known table.
2. **Search** — use `search_documents` with a document type and year to find relevant bills or reports, or use `search_votes` with a keyword to find vote sessions.
3. **Retrieve** — pass the `Id` from `search_documents` to `get_document_text`, or the `AanestysId` from `search_votes` to `get_vote_result`.
4. **Explore MPs** — call `get_mp_list` to get the current parliament roster with party and constituency.

## Quick start

```bash
git clone https://github.com/SimonBerg255/eduskunta-mcp.git
cd eduskunta-mcp
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
uvicorn server:app --host 0.0.0.0 --port 8000
```

## API details

- **Base URL:** `https://avoindata.eduskunta.fi/api/v1`
- **Protocol:** REST, JSON responses
- **Authentication:** None — fully public
- **Rate limits:** No documented limit; client uses 0.5 s delay between paginated requests and retries once on HTTP 429
- **Response format:** Columnar envelope — `{"columnNames": [...], "rowData": [[...]], "hasMore": true/false}`
- **License:** Open data, Finnish Parliament

## Domain reference

**Document types** (`document_type` parameter in `search_documents`):

| Finnish name | Abbreviation in Tunniste |
|---|---|
| Hallituksen esitys | `HE` |
| Lakialoite | `LA` |
| Kirjallinen kysymys | `KK` |
| Valiokunnan mietintö | `{committee}VM` |
| Valiokunnan lausunto | `{committee}VL` |

**Committee abbreviations** (`committee` parameter):

`PeV` (constitutional), `LaV` (legal affairs), `SiV` (education), `StV` (social affairs), `HaV` (administration), `TaV` (commerce), `LiV` (transport), `UaV` (foreign affairs), `PuV` (defence)

**Vote values** (returned in `get_vote_result`):

`Jaa` (aye), `Ei` (no), `Poissa` (absent), `Tyhjaa` (abstain)

**Tunniste format:** Parliamentary identifiers follow the pattern `HE 7/2024 vp` — type, number, year, and session marker (`vp` = valtiopäivät, `rd` = riksdag/Swedish).

## Validation

```bash
python validate.py
```

Runs 6 live checks against the real API: table discovery, document search (HE 2024, no raw XML in results), vote search by keyword, per-MP vote result totals (100–210 votes), active MP count (180–210), and full document text extraction (≥100 chars). Exits 0 on all pass, 1 on any failure.

## License

MIT
