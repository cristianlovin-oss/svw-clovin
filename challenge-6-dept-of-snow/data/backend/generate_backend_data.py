"""Generates the ADS operations backend records (fictional) as JSONL for Cloud Storage.

Scenario: "Winter Storm Kodiak" on 2026-11-20. Each line is one record with an "id" and a
"record_type": storm_declaration, road_segment, plow_unit, road_closure, incident, service_request.

Usage:  python data/backend/generate_backend_data.py   ->  data/backend/ads_operations.jsonl
The file is uploaded to Cloud Storage and imported into the AI Applications datastore
"ads-operations-backend" by setup_cloud.py.
"""

import json
from pathlib import Path

D = "2026-11-20"

STORMS = [
    {"id": "STORM-2026-07-SC", "storm_name": "Winter Storm Kodiak", "region": "Southcentral", "level": 3,
     "declared_by": "Storm Duty Officer", "declared_at": f"{D}T04:30:00-09:00",
     "nws_warning": "Blizzard Warning", "forecast_snow_in": "14-20", "forecast_wind_mph": "40-55",
     "status": "active", "next_briefing": f"{D}T15:00:00-09:00"},
    {"id": "STORM-2026-07-VZ", "storm_name": "Winter Storm Kodiak", "region": "Copper River / Valdez", "level": 3,
     "declared_by": "Storm Duty Officer", "declared_at": f"{D}T05:15:00-09:00",
     "nws_warning": "Winter Storm Warning", "forecast_snow_in": "24-36", "forecast_wind_mph": "30-45",
     "status": "active", "next_briefing": f"{D}T15:00:00-09:00"},
    {"id": "STORM-2026-07-IN", "storm_name": "Winter Storm Kodiak", "region": "Interior", "level": 2,
     "declared_by": "Regional Operations Supervisor", "declared_at": f"{D}T06:00:00-09:00",
     "nws_warning": "Winter Weather Advisory", "forecast_snow_in": "6-9", "forecast_wind_mph": "10-20",
     "status": "active", "next_briefing": f"{D}T18:00:00-09:00"},
]

SEGMENTS = [
    # id, road, segment, region, priority, mp_from, mp_to, status, surface, last_plowed, avalanche_zone, avalanche_danger
    ("SEG-GLN-01", "Glenn Highway", "Anchorage to Eagle River", "Southcentral", "P1", 0, 13, "open", "snow-packed", "13:20", False, None),
    ("SEG-GLN-02", "Glenn Highway", "Eagle River to Palmer", "Southcentral", "P1", 13, 42, "open", "drifting snow", "12:55", False, None),
    ("SEG-GLN-03", "Glenn Highway", "Sheep Mountain", "Southcentral", "P1", 110, 115, "closed", "drifting snow", "08:10", True, "HIGH"),
    ("SEG-SEW-01", "Seward Highway", "Anchorage to Potter", "Southcentral", "P1", 117, 127, "open", "wet", "13:40", False, None),
    ("SEG-SEW-02", "Seward Highway", "Bird to Girdwood", "Southcentral", "P1", 90, 104, "convoy", "icy", "12:30", True, "CONSIDERABLE"),
    ("SEG-SEW-03", "Seward Highway", "Turnagain Pass", "Southcentral", "P1", 75, 90, "closed", "snow-covered", "07:45", True, "HIGH"),
    ("SEG-PRK-01", "Parks Highway", "Wasilla to Willow", "Southcentral", "P1", 42, 70, "open", "snow-packed", "12:15", False, None),
    ("SEG-RCH-01", "Richardson Highway", "Valdez to Thompson Pass", "Copper River / Valdez", "P1", 0, 37, "closed", "snow-covered", "06:30", True, "EXTREME"),
    ("SEG-STE-01", "Sterling Highway", "Tern Lake to Cooper Landing", "Kenai Peninsula", "P1", 37, 48, "open", "icy", "11:50", False, None),
    ("SEG-AIR-01", "Minnesota Drive", "Ted Stevens Anchorage International Airport access", "Southcentral", "P1", 0, 4, "open", "wet", "13:50", False, None),
    ("SEG-BLD-01", "Boniface Parkway", "Anchorage arterial (Muldoon to Tudor)", "Southcentral", "P2", 0, 3, "open", "snow-packed", "10:05", False, None),
    ("SEG-RES-01", "Hillside residential streets", "Anchorage Hillside (south of O'Malley Rd)", "Southcentral", "P3", 0, 0, "open", "deep snow, not yet plowed", None, False, None),
    ("SEG-FBX-01", "Steese Highway", "Fairbanks to Chena Hot Springs Rd", "Interior", "P1", 0, 5, "open", "snow-packed", "12:40", False, None),
    ("SEG-DAL-01", "Dalton Highway", "Coldfoot to Atigun Pass", "Interior", "P4", 175, 244, "closed", "drifting snow", None, False, None),
    ("SEG-EGN-01", "Egan Drive", "Juneau downtown to Mendenhall", "Southeast", "P1", 0, 9, "open", "wet", "13:10", True, "MODERATE"),
]

PLOWS = [
    # unit, type, region, status, segment, operator_hours_today, note
    ("ADS-PL-101", "Plow truck with wing", "Southcentral", "in_service", "SEG-GLN-01", 9.5, ""),
    ("ADS-PL-102", "Plow truck with wing", "Southcentral", "in_service", "SEG-GLN-02", 9.5, ""),
    ("ADS-PL-103", "Plow truck with wing", "Southcentral", "out_of_service", None, 4.0, "Hydraulic line failure; in shop"),
    ("ADS-PL-104", "Plow truck", "Southcentral", "in_service", "SEG-SEW-01", 8.0, ""),
    ("ADS-PL-105", "Plow truck", "Southcentral", "in_service", "SEG-SEW-02", 15.0, "Operator near 16-hour limit"),
    ("ADS-PL-106", "Rotary snowblower", "Southcentral", "standby", "SEG-SEW-03", 2.0, "Staged at Girdwood for Turnagain Pass reopening"),
    ("ADS-PL-107", "Plow truck", "Southcentral", "in_service", "SEG-PRK-01", 7.5, ""),
    ("ADS-PL-108", "Plow truck", "Southcentral", "in_service", "SEG-AIR-01", 6.0, ""),
    ("ADS-PL-109", "Grader", "Southcentral", "in_service", "SEG-BLD-01", 5.5, ""),
    ("ADS-PL-110", "Plow truck", "Southcentral", "fueling", None, 6.5, "Fueling at Anchorage Central depot"),
    ("ADS-PL-201", "Rotary snowblower", "Copper River / Valdez", "standby", "SEG-RCH-01", 3.0, "Waiting for avalanche control"),
    ("ADS-PL-202", "Plow truck with wing", "Copper River / Valdez", "in_service", "SEG-RCH-01", 10.0, "Valdez side, below Milepost 12"),
    ("ADS-PL-301", "Plow truck", "Kenai Peninsula", "in_service", "SEG-STE-01", 8.5, ""),
    ("ADS-PL-401", "Plow truck", "Interior", "in_service", "SEG-FBX-01", 7.0, ""),
    ("ADS-PL-402", "Grader", "Interior", "maintenance", None, 0.0, "Scheduled maintenance"),
    ("ADS-PL-501", "Plow truck", "Southeast", "in_service", "SEG-EGN-01", 6.0, ""),
]

CLOSURES = [
    {"id": "CL-2026-1120-01", "segment_id": "SEG-SEW-03", "road_name": "Seward Highway",
     "location": "Turnagain Pass, Milepost 75 to 90", "region": "Southcentral",
     "reason": "Avalanche danger HIGH; avalanche control scheduled", "authority": "Storm Duty Officer",
     "started": f"{D}T07:50:00-09:00", "estimated_reopen": f"{D}T18:00:00-09:00", "status": "active"},
    {"id": "CL-2026-1120-02", "segment_id": "SEG-RCH-01", "road_name": "Richardson Highway",
     "location": "Thompson Pass, Milepost 18 to 37", "region": "Copper River / Valdez",
     "reason": "Avalanche danger EXTREME; avalanche reached the road at Milepost 26", "authority": "Storm Duty Officer",
     "started": f"{D}T06:40:00-09:00", "estimated_reopen": "2026-11-21T12:00:00-09:00", "status": "active"},
    {"id": "CL-2026-1120-03", "segment_id": "SEG-GLN-03", "road_name": "Glenn Highway",
     "location": "Sheep Mountain, Milepost 110 to 115", "region": "Southcentral",
     "reason": "Visibility below 1/4 mile from blowing snow; avalanche danger HIGH", "authority": "Storm Duty Officer",
     "started": f"{D}T09:15:00-09:00", "estimated_reopen": f"{D}T20:00:00-09:00", "status": "active"},
    {"id": "CL-2026-1120-04", "segment_id": "SEG-DAL-01", "road_name": "Dalton Highway",
     "location": "Coldfoot to Atigun Pass, Milepost 175 to 244", "region": "Interior",
     "reason": "P4 seasonal route suspended for the storm (ADS-OPS-100)", "authority": "Regional Operations Supervisor",
     "started": f"{D}T06:10:00-09:00", "estimated_reopen": "2026-11-22T12:00:00-09:00", "status": "active"},
    {"id": "CL-2026-1120-00", "segment_id": "SEG-PRK-01", "road_name": "Parks Highway",
     "location": "Wasilla to Willow, Milepost 52", "region": "Southcentral",
     "reason": "Multi-vehicle crash blocking both lanes (Troopers request)", "authority": "Alaska State Troopers",
     "started": f"{D}T05:20:00-09:00", "estimated_reopen": f"{D}T07:30:00-09:00", "status": "reopened",
     "reopened_at": f"{D}T07:05:00-09:00"},
]

INCIDENTS = [
    {"id": "INC-2026-1120-11", "type": "Avalanche debris on road", "segment_id": "SEG-RCH-01", "region": "Copper River / Valdez",
     "location": "Richardson Highway Milepost 26", "status": "open", "reported": f"{D}T06:35:00-09:00",
     "notes": "Debris about 8 ft deep across both lanes; no vehicles involved."},
    {"id": "INC-2026-1120-12", "type": "Vehicles in ditch", "segment_id": "SEG-GLN-02", "region": "Southcentral",
     "location": "Glenn Highway Milepost 31 northbound", "status": "cleared", "reported": f"{D}T10:40:00-09:00",
     "notes": "Two vehicles; Troopers on scene; no injuries; towed at 11:55."},
    {"id": "INC-2026-1120-13", "type": "Stranded motorists", "segment_id": "SEG-SEW-03", "region": "Southcentral",
     "location": "Seward Highway Milepost 80 (Turnagain Pass parking area)", "status": "open", "reported": f"{D}T08:05:00-09:00",
     "notes": "Three vehicles stopped before the closure; Troopers notified via 911; ADS-PL-106 standing by."},
    {"id": "INC-2026-1120-14", "type": "Plow equipment failure", "segment_id": "SEG-GLN-01", "region": "Southcentral",
     "location": "Anchorage Central depot", "status": "open", "reported": f"{D}T09:30:00-09:00",
     "notes": "ADS-PL-103 hydraulic line failure; out of service, repair estimate 6 hours."},
]

SERVICE_REQUESTS = [
    # Personal data (name, phone) is stored but must never be returned by the MCP tools.
    {"id": "SR-2026-11-0412", "type": "Unplowed or missed road", "location": "Hillside Drive near O'Malley Rd, Anchorage",
     "region": "Southcentral", "road_priority": "P3", "status": "scheduled", "created": f"{D}T08:12:00-09:00",
     "target": "Passable within 48 hours after snowfall stops (P3)", "requester_name": "Dana Whitfield", "requester_phone": "907-555-0141"},
    {"id": "SR-2026-11-0413", "type": "Icy road or intersection needing sand", "location": "Boniface Pkwy & Debarr Rd, Anchorage",
     "region": "Southcentral", "road_priority": "P2", "status": "in_progress", "created": f"{D}T09:02:00-09:00",
     "target": "Sanding within 6 hours (P2)", "requester_name": "Luis Ortega", "requester_phone": "907-555-0172"},
    {"id": "SR-2026-11-0414", "type": "Damaged mailbox", "location": "1204 Raspberry Rd, Anchorage",
     "region": "Southcentral", "road_priority": "P2", "status": "received", "created": f"{D}T10:20:00-09:00",
     "target": "Inspection within 5 business days", "requester_name": "Priya Raman", "requester_phone": "907-555-0118"},
    {"id": "SR-2026-11-0415", "type": "Snow berm assistance", "location": "Lake Otis Pkwy area, Anchorage",
     "region": "Southcentral", "road_priority": "P3", "status": "received", "created": f"{D}T11:05:00-09:00",
     "target": "Berm cleared within 24 hours after the street is plowed (registered program participant)",
     "requester_name": "Harold Nygaard", "requester_phone": "907-555-0163"},
    {"id": "SR-2026-11-0416", "type": "Blocked storm drain or flooding", "location": "Egan Drive & Main St, Juneau",
     "region": "Southeast", "road_priority": "P1", "status": "completed", "created": f"{D}T07:40:00-09:00",
     "target": "Within 24 hours", "requester_name": "Mei Chen", "requester_phone": "907-555-0190"},
]


def records():
    for s in STORMS:
        yield {"record_type": "storm_declaration", **s}
    for (sid, road, seg, region, prio, mpf, mpt, status, surface, last, avz, avd) in SEGMENTS:
        yield {"id": sid, "record_type": "road_segment", "road_name": road, "segment": seg, "region": region,
               "priority": prio, "milepost_from": mpf, "milepost_to": mpt, "status": status,
               "surface_condition": surface,
               "last_plowed": f"{D}T{last}:00-09:00" if last else None,
               "avalanche_zone": avz, "avalanche_danger": avd}
    for (unit, typ, region, status, seg, hours, note) in PLOWS:
        yield {"id": unit, "record_type": "plow_unit", "unit_type": typ, "region": region, "status": status,
               "assigned_segment": seg, "operator_hours_today": hours, "note": note or None,
               "last_update": f"{D}T13:55:00-09:00"}
    for c in CLOSURES:
        yield {"record_type": "road_closure", **c}
    for i in INCIDENTS:
        yield {"record_type": "incident", **i}
    for r in SERVICE_REQUESTS:
        yield {"record_type": "service_request", **r}


if __name__ == "__main__":
    out = Path(__file__).parent / "ads_operations.jsonl"
    rows = [{k: v for k, v in r.items() if v is not None} for r in records()]
    out.write_text("\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8")
    print(f"Wrote {out} ({len(rows)} records)")
