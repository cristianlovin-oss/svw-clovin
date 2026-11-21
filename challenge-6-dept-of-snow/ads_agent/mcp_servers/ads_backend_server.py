"""Custom MCP server: ADS (Alaska Department of Snow) operations backend.

Exposes Python functions as MCP tools over stdio. The backend is the Google Cloud
AI Applications datastore "ads-operations-backend", loaded from JSONL in Cloud Storage
(see setup_cloud.py). Records are read with the Discovery Engine DocumentService and new
service requests are written back to the same datastore.

Privacy rule (ADS-PUB-300 section 5): requester names and phone numbers stored on service
requests are NEVER returned by any tool.

Run standalone for debugging:  python ads_agent/mcp_servers/ads_backend_server.py
"""

import os
import time
import uuid
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from dotenv import load_dotenv
from google.cloud import discoveryengine_v1 as de
from mcp.server.mcpserver import MCPServer

load_dotenv(Path(__file__).resolve().parents[1] / ".env")

DATASTORE = os.environ.get(
    "OPS_DATASTORE_ID",
    f"projects/{os.environ.get('GOOGLE_CLOUD_PROJECT', '')}/locations/global/collections/"
    "default_collection/dataStores/ads-operations-backend",
)
BRANCH = f"{DATASTORE}/branches/default_branch"
PRIVATE_FIELDS = {"requester_name", "requester_phone", "requester_email"}
AK = ZoneInfo("America/Anchorage")

server = MCPServer(
    name="ads-backend",
    instructions=(
        "Alaska Department of Snow operations backend: storm declarations, road segment status, "
        "plow fleet, road closures, incidents and public service requests."
    ),
)

_client = None
_cache: dict = {"at": 0.0, "records": []}


def _docs_client() -> de.DocumentServiceClient:
    global _client
    if _client is None:
        _client = de.DocumentServiceClient()
    return _client


def _records(max_age_s: float = 20) -> list[dict]:
    """All backend records (cached briefly; the dataset is small)."""
    if time.time() - _cache["at"] > max_age_s:
        rows = []
        request = de.ListDocumentsRequest(parent=BRANCH, page_size=500)
        for doc in _docs_client().list_documents(request=request):
            data = de.Document.to_dict(doc).get("struct_data") or {}
            data.setdefault("id", doc.id)
            rows.append(data)
        _cache.update(at=time.time(), records=rows)
    return _cache["records"]


def _public(record: dict) -> dict:
    return {k: v for k, v in record.items() if k not in PRIVATE_FIELDS}


def _of_type(record_type: str, region: str = "") -> list[dict]:
    region = region.strip().lower()
    return [
        _public(r) for r in _records()
        if r.get("record_type") == record_type and (not region or region in str(r.get("region", "")).lower())
    ]


@server.tool()
def get_storm_status(region: str = "") -> dict:
    """Get the active storm declarations (storm level 1-4, NWS warning, forecast, next briefing).

    Args:
        region: Optional ADS region filter, e.g. "Southcentral", "Interior", "Copper River / Valdez",
            "Kenai Peninsula", "Southeast". Leave empty for all regions.
    """
    storms = [s for s in _of_type("storm_declaration", region) if s.get("status") == "active"]
    return {"active_declarations": storms, "count": len(storms), "source": "ADS operations backend"}


@server.tool()
def get_road_status(road: str) -> dict:
    """Get the current status of road segments matching a road name, segment or segment ID
    (open / closed / convoy, surface condition, priority class, last plowed, avalanche danger).

    Args:
        road: Road name or segment, e.g. "Seward Highway", "Turnagain Pass", "Glenn", "SEG-RCH-01".
    """
    q = road.strip().lower()
    segments = [
        s for s in _of_type("road_segment")
        if q in f"{s.get('id', '')} {s.get('road_name', '')} {s.get('segment', '')}".lower()
    ]
    return {"query": road, "segments": segments, "count": len(segments), "source": "ADS operations backend"}


@server.tool()
def list_road_closures(region: str = "", include_reopened: bool = False) -> dict:
    """List road closures with reason, closing authority, start time and estimated reopening time.

    Args:
        region: Optional ADS region filter. Leave empty for all regions.
        include_reopened: Also include closures that have already reopened today.
    """
    closures = [
        c for c in _of_type("road_closure", region)
        if include_reopened or c.get("status") == "active"
    ]
    return {"closures": closures, "count": len(closures), "source": "ADS operations backend"}


@server.tool()
def get_plow_fleet_status(region: str = "") -> dict:
    """Get plow fleet availability: each unit's status and assignment, counts by status, and whether
    the region meets the ADS-EM-200 requirement that at least 85% of units are in service.

    Args:
        region: Optional ADS region filter. Leave empty for the whole fleet.
    """
    units = _of_type("plow_unit", region)
    counts: dict[str, int] = {}
    for u in units:
        counts[u.get("status", "unknown")] = counts.get(u.get("status", "unknown"), 0) + 1
    available = counts.get("in_service", 0) + counts.get("standby", 0) + counts.get("fueling", 0)
    pct = round(100 * available / len(units), 1) if units else 0.0
    near_limit = [u["id"] for u in units if float(u.get("operator_hours_today") or 0) >= 14]
    return {
        "units": units,
        "counts_by_status": counts,
        "available_pct": pct,
        "meets_85pct_requirement": pct >= 85,
        "operators_near_16h_limit": near_limit,
        "note": "Available = in_service + standby + fueling. Hours-of-service limit is 16 h per 24 h (ADS-SAF-400).",
        "source": "ADS operations backend",
    }


@server.tool()
def list_incidents(region: str = "", status: str = "open") -> dict:
    """List operational incidents (avalanche debris, vehicles in ditch, stranded motorists, equipment failures).

    Args:
        region: Optional ADS region filter. Leave empty for all regions.
        status: "open", "cleared" or "all".
    """
    incidents = [
        i for i in _of_type("incident", region)
        if status == "all" or i.get("status") == status
    ]
    return {"incidents": incidents, "count": len(incidents), "source": "ADS operations backend"}


@server.tool()
def get_service_request_status(request_id: str) -> dict:
    """Get the status of a public service request by its ID (e.g. "SR-2026-11-0412").
    Personal details of the requester are never returned.

    Args:
        request_id: The service request ID given to the requester.
    """
    rid = request_id.strip().upper()
    for r in _of_type("service_request"):
        if r.get("id", "").upper() == rid:
            return {"found": True, "request": r, "source": "ADS operations backend"}
    return {"found": False, "request_id": request_id, "message": "No service request with that ID."}


@server.tool()
def create_service_request(request_type: str, location: str, description: str, region: str = "Southcentral") -> dict:
    """Create a new public service request in the ADS backend and return its request ID.
    Do not include personal names or phone numbers in any field.

    Args:
        request_type: One of "Unplowed or missed road", "Icy road or intersection needing sand",
            "Blocked storm drain or flooding", "Damaged mailbox", "Damaged property", "Snow berm assistance".
        location: Street address or intersection, with the city.
        description: Short description of the problem.
        region: ADS region, e.g. "Southcentral".
    """
    now = datetime.now(AK)
    rid = f"SR-{now:%Y-%m}-{uuid.uuid4().hex[:4].upper()}"
    record = {
        "id": rid, "record_type": "service_request", "type": request_type, "location": location,
        "description": description, "region": region, "status": "received",
        "created": now.isoformat(timespec="seconds"),
        "target": "See ADS-PUB-300 section 2 for the target response time for this request type.",
    }
    doc = de.Document(id=rid, struct_data=record)
    _docs_client().create_document(parent=BRANCH, document=doc, document_id=rid)
    _cache["at"] = 0.0  # refresh on next read
    return {"created": True, "request_id": rid, "request": record, "source": "ADS operations backend"}


@server.tool()
def search_operations_records(query: str, record_type: str = "") -> dict:
    """Keyword search across all ADS operations records (useful when the other tools don't fit).

    Args:
        query: Words to look for, e.g. "Milepost 26", "Girdwood", "ADS-PL-105".
        record_type: Optional filter: storm_declaration, road_segment, plow_unit, road_closure,
            incident, service_request.
    """
    words = [w for w in query.lower().split() if w]
    hits = []
    for r in _records():
        if record_type and r.get("record_type") != record_type:
            continue
        text = " ".join(str(v) for k, v in r.items() if k not in PRIVATE_FIELDS).lower()
        score = sum(w in text for w in words)
        if score:
            hits.append((score, _public(r)))
    hits.sort(key=lambda h: -h[0])
    return {"query": query, "results": [h[1] for h in hits[:10]], "count": len(hits), "source": "ADS operations backend"}


if __name__ == "__main__":
    server.run("stdio")
