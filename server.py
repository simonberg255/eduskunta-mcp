import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path

from dotenv import load_dotenv
from fastmcp import FastMCP
from fastmcp.server.auth.providers.jwt import JWTVerifier
from mcp.server.fastmcp import Icon
from starlette.middleware import Middleware
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import FileResponse, JSONResponse, PlainTextResponse

load_dotenv()

from client import EduskuntaClient  # noqa: E402

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

eduskunta = EduskuntaClient()


####### API KEY #######


verifier = JWTVerifier(
    public_key=os.getenv("MCP_SERVER_JWT_SECRET"),
    issuer=os.getenv("MCP_SERVER_JWT_ISSUER", ""),
    audience=os.getenv("MCP_SERVER_JWT_AUDIENCE", ""),
    algorithm="HS256",
)


####### MIDDLEWARE #######


class IPAllowlistMiddleware(BaseHTTPMiddleware):
    def __init__(self, app, allowed_ips: list[str]):
        super().__init__(app)
        self.allowed_ips = set(allowed_ips)
        self.allow_all = "*" in self.allowed_ips

    async def dispatch(self, request, call_next):
        if self.allow_all:
            return await call_next(request)

        client_ip = request.client.host if request.client else None
        if client_ip not in self.allowed_ips:
            return JSONResponse(
                status_code=403,
                content={"error": "Forbidden", "your_ip": client_ip},
            )
        return await call_next(request)


ALLOWED_IPS = ["*"]
middleware = [Middleware(IPAllowlistMiddleware, allowed_ips=ALLOWED_IPS)]


####### SERVER METADATA #######


# SERVER_BASE_URL must match the public URL where this server is reachable
# (e.g. your ngrok HTTPS URL). Intric uses it to fetch the logo.
SERVER_BASE_URL = os.getenv("SERVER_BASE_URL", "http://localhost:8000").rstrip("/")
LOGO_PATH = Path(__file__).parent / "logo.png"

icon = Icon(
    src=f"{SERVER_BASE_URL}/logo.png",
    mimeType="image/png",
)

INSTRUCTION_STRING = (
    "Finnish Parliament (Eduskunta) open data server. "
    "Provides access to parliamentary documents, votes, and MP information via the "
    "Finnish Parliament's public API at avoindata.eduskunta.fi. "
    "Use list_tables to discover available data sources. "
    "Use search_documents to find bills, committee reports, and written questions. "
    "Use get_document_text to read the full text of a specific document. "
    "Use search_votes and get_vote_result to explore plenary voting records. "
    "Use get_mp_list to get information about Members of Parliament."
)
VERSION = "1.0.0"
WEBSITE_URL = "https://avoindata.eduskunta.fi"


####### LIFESPAN #######


@asynccontextmanager
async def lifespan(server):
    await eduskunta.initialize()
    logger.info("EduskuntaClient initialised and ready")
    yield
    await eduskunta.close()
    logger.info("EduskuntaClient shut down")


####### SERVER #######


mcp = FastMCP(
    name="Eduskunta MCP Server",
    instructions=INSTRUCTION_STRING,
    version=VERSION,
    website_url=WEBSITE_URL,
    icons=[icon],
    auth=verifier,
    lifespan=lifespan,
)


####### TOOLS #######


@mcp.tool(meta={"requires_permission": False})
async def list_tables() -> list | dict:
    """
    List all available tables in the Finnish Parliament open data API.

    Returns the full list of table names. Use this to discover what data is
    available before querying. Key tables:
      VaskiData                — parliamentary documents (bills, reports, etc.)
      SaliDBAanestys           — plenary vote sessions
      SaliDBAanestysEdustaja   — per-MP vote records
      MemberOfParliament       — MP biographical data
      Attachment               — PDF document attachments
      SaliDBIstunto            — plenary session records

    returns:
        List of table name strings.
    """
    try:
        return await eduskunta.get_tables()
    except Exception as exc:
        return {"error": str(exc)}


@mcp.tool(meta={"requires_permission": False})
async def search_documents(
    year: int | None = None,
    document_type: str | None = None,
    committee: str | None = None,
    limit: int = 20,
) -> list | dict:
    """
    Search Finnish parliamentary documents (VaskiData table).

    Returns lightweight document metadata — never includes raw XML content.

    args:
        year: Filter by parliamentary year, e.g. 2024.
        document_type: Case-insensitive substring match on document type
            (AsiakirjatyyppiNimi). Common values:
              "Hallituksen esitys"    — government bills (HE)
              "Valiokunnan mietintö"  — committee reports
              "Valiokunnan lausunto"  — committee opinions
              "Kirjallinen kysymys"   — written parliamentary questions
              "Lakialoite"            — private member bills
        committee: Filter by committee abbreviation (ToimielinLyhenne).
            Common values: PeV (constitutional), LaV (legal affairs),
            SiV (education), StV (social affairs), HaV (administration).
        limit: Maximum number of results to return (default 20).

    returns:
        List of documents with fields: Id, Tunniste, NimiSuomi,
        AsiakirjatyyppiNimi, ToimielinLyhenne, ValtiopaivaVuosi, PdfLink.
    """
    try:
        return await eduskunta.search_documents(
            year=year,
            document_type=document_type,
            committee=committee,
            limit=limit,
        )
    except Exception as exc:
        return {"error": str(exc)}


@mcp.tool(meta={"requires_permission": False})
async def get_document_text(document_id: int) -> dict:
    """
    Fetch the full text of a Finnish parliamentary document by its Id.

    Extracts clean Finnish plain text from the document's XML data.
    Falls back to PDF extraction via PdfLink if XML is absent or unparseable.

    args:
        document_id: The integer Id of the document (from search_documents results).

    returns:
        Dict with fields: Id, Tunniste, NimiSuomi, AsiakirjatyyppiNimi,
        text (clean Finnish plain text), source ("xml" or "pdf").
    """
    try:
        return await eduskunta.get_document_text(document_id)
    except Exception as exc:
        return {"error": str(exc)}


@mcp.tool(meta={"requires_permission": False})
async def search_votes(
    keyword: str,
    year: int | None = None,
) -> list | dict:
    """
    Search Finnish parliament plenary vote sessions (SaliDBAanestys table).

    Filters vote session titles (KohtaOtsikko) by keyword.

    args:
        keyword: Case-insensitive substring to match against vote session titles.
        year: Optional filter — only return votes from this year.

    returns:
        List of up to 50 vote sessions with fields:
        AanestysId, KohtaOtsikko, Aanestysaika, Istunto.
    """
    try:
        return await eduskunta.search_votes(keyword=keyword, year=year)
    except Exception as exc:
        return {"error": str(exc)}


@mcp.tool(meta={"requires_permission": False})
async def get_vote_result(aanestys_id: int) -> dict:
    """
    Get detailed voting results for a specific plenary vote session.

    Fetches individual MP votes and joins with MP profile data to show
    how each member voted, broken down by party.

    args:
        aanestys_id: The AanestysId of the vote session (from search_votes results).

    returns:
        Dict with:
          aanestys_id: The vote session id.
          summary: {"Jaa": N, "Ei": N, "Poissa": N, "Tyhjaa": N}
          by_party: {"PartyName": {"Jaa": N, "Ei": N, "Poissa": N, "Tyhjaa": N}, ...}
          votes: [{"name": str, "party": str, "vote": str}, ...]
    """
    try:
        return await eduskunta.get_vote_result(aanestys_id)
    except Exception as exc:
        return {"error": str(exc)}


@mcp.tool(meta={"requires_permission": False})
async def get_mp_list(active_only: bool = True) -> list | dict:
    """
    Get a list of Finnish Members of Parliament (Kansanedustajat).

    args:
        active_only: If True (default), return only currently serving MPs
                     (those with no end date in their term of service).
                     If False, return all MPs including historical members.

    returns:
        List of MPs with fields:
        HenkiloNumero, Sukunimi, Etunimi, Puolue, Vaalipiiri.
    """
    try:
        return await eduskunta.get_mp_list(active_only=active_only)
    except Exception as exc:
        return {"error": str(exc)}


####### CUSTOM ROUTES #######


@mcp.custom_route("/health", methods=["GET"])
async def health_check(request: Request) -> PlainTextResponse:
    return PlainTextResponse("OK")


@mcp.custom_route("/logo.png", methods=["GET"])
async def serve_logo(request: Request) -> FileResponse:
    return FileResponse(str(LOGO_PATH), media_type="image/png")


####### APP #######

# Run with: uvicorn server:app --host 0.0.0.0 --port 8000
app = mcp.http_app(middleware=middleware)
