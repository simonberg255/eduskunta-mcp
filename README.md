# Eduskunta MCP Server

Finnish Parliament open data server built on [FastMCP](https://github.com/jlowin/fastmcp),
designed for use with [Intric](https://www.intric.ai).

Data source: [avoindata.eduskunta.fi](https://avoindata.eduskunta.fi) — fully public, no API key required.

## Tools

| Tool | Description |
|---|---|
| `list_tables` | Discover all available data tables |
| `search_documents` | Search parliamentary documents (bills, reports, questions) |
| `get_document_text` | Read the full text of a specific document |
| `search_votes` | Search plenary vote sessions by keyword |
| `get_vote_result` | Get per-MP vote breakdown with party summary |
| `get_mp_list` | List Members of Parliament (active or historical) |

All tools run automatically in Intric — no user confirmation prompts.

## Quick Start

```bash
# 1. Set up environment
cp .env.example .env
# Edit .env — set MCP_SERVER_JWT_SECRET to a random string of 32+ chars

# 2. Install dependencies
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# 3. Generate an API token for Intric
python3 generate_token.py

# 4. Start the server
uvicorn server:app --host 0.0.0.0 --port 8000
```

The MCP endpoint is available at `http://localhost:8000/mcp`.

## Connecting to Intric

1. Expose the server with a public HTTPS URL (e.g. via [ngrok](https://ngrok.com): `ngrok http 8000`)
2. In Intric → Settings → MCP Connections, add the URL ending in `/mcp`
3. Paste the JWT token from `generate_token.py` as the API Key

## Validate Against the Live API

```bash
python3 validate.py
```

Runs 6 checks against the real Finnish Parliament API and prints PASS/FAIL for each.

## Project Structure

```
eduskunta-mcp/
├── server.py          # FastMCP server — tool registration, auth, middleware
├── client.py          # EduskuntaClient — all HTTP and pagination logic
├── parsers.py         # rows_to_dicts, XML/PDF text extraction, field helpers
├── validate.py        # End-to-end validation against the live API
├── generate_token.py  # Generate a JWT for Intric's API Key field
├── requirements.txt
└── .env.example
```

## Key API Notes

The Finnish Parliament API (`avoindata.eduskunta.fi/api/v1`) uses a **columnar response format**:

```json
{
  "columnNames": ["Id", "XmlData", "Eduskuntatunnus", "..."],
  "rowData": [["12345", "<xml>...", "HE 1/2024 vp", "..."]],
  "hasMore": true
}
```

All rows are converted to named dicts immediately via `rows_to_dicts()`. Pagination is
driven by `hasMore`, not row count.

Document search uses the `/vaski/text` full-text endpoint. Document metadata (title,
type, year) is extracted from the `EduskuntaTunnus` field and XML content — these are
**not** separate columns in `VaskiData`.
