"""Custom MCP server: trout fishing conditions at Georgetown Reservoir (Georgetown Lake), Colorado.

Exposes plain Python functions as MCP tools over stdio:
  - get_reservoir_info        location, elevation, species, access, regulations pointers
  - get_seasonal_conditions   season phase, estimated water temperature, ice status, where trout hold
  - get_sun_and_moon          sunrise/sunset, low-light bite windows, moon phase (computed locally)
  - rate_fishing_conditions   1-10 fishing score from weather inputs (e.g. from the NWS weather agent)
  - recommend_tactics         baits, lures and flies for the season and sky conditions

Everything is computed locally: no API keys and no network calls. Water temperature and ice
status are seasonal-model ESTIMATES for a ~8,440 ft mountain lake, not live measurements.

Run standalone (for debugging):  python mcp_servers/trout_conditions_server.py
"""

import math
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from mcp.server.mcpserver import MCPServer

TZ = ZoneInfo("America/Denver")
LAT, LON = 39.7269, -105.6919  # OpenStreetMap: Georgetown Lake, Clear Creek County, CO
ELEVATION_FT = 8445  # USGS Elevation Point Query Service at the lake coordinates

server = MCPServer(
    name="georgetown-trout",
    instructions=(
        "Trout fishing information for Georgetown Reservoir (Georgetown Lake) in "
        "Georgetown, Colorado. Dates use YYYY-MM-DD; omit the date for today."
    ),
)


# --------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------
def _parse_date(value: str | None) -> date:
    if not value:
        return datetime.now(TZ).date()
    return date.fromisoformat(value.strip()[:10])


# Seasonal phases for a ~8,400 ft Colorado lake (approximate; varies year to year).
# (start month, start day, phase key)
_PHASES = [
    ((1, 1), "ice_season"),
    ((4, 16), "ice_out_spring"),
    ((6, 1), "early_summer"),
    ((7, 11), "midsummer"),
    ((9, 1), "fall"),
    ((11, 1), "late_fall_ice_up"),
    ((12, 25), "ice_season"),
]

_PHASE_INFO = {
    "ice_season": {
        "label": "Ice fishing season (hard water)",
        "ice_status": "Usually ice-covered. Ice thickness varies; always check it yourself.",
        "trout_location": "Cruising near bottom in 6-15 ft, often along drop-offs and near the inlet.",
        "activity": "Slow metabolism; short feeding windows, often mid-morning and late afternoon.",
    },
    "ice_out_spring": {
        "label": "Ice-out and spring turnover",
        "ice_status": "Ice breaking up (typically late April to May). Rotten ice: stay off.",
        "trout_location": "Shallow, near shore and inlets, chasing food in warming water.",
        "activity": "Often the best shore fishing of the year right after ice-out.",
    },
    "early_summer": {
        "label": "Early summer",
        "ice_status": "Open water.",
        "trout_location": "Shallow to mid-depth; evening rises near the surface.",
        "activity": "Active all day in cool water; strong dawn and dusk bites.",
    },
    "midsummer": {
        "label": "Midsummer",
        "ice_status": "Open water.",
        "trout_location": "Deeper, cooler water (15+ ft) during the day; shallows at dawn and dusk.",
        "activity": "Best early morning and evening; midday is slow on bright days.",
    },
    "fall": {
        "label": "Fall",
        "ice_status": "Open water.",
        "trout_location": "Moving shallower again as water cools; feeding heavily before winter.",
        "activity": "Good all day; browns become aggressive in the fall.",
    },
    "late_fall_ice_up": {
        "label": "Late fall / ice-up transition",
        "ice_status": "Skim ice or thin new ice is possible. NOT safe to walk on.",
        "trout_location": "Shallow to mid-depth; fish from shore while it is open.",
        "activity": "Fair to good on mild afternoons; cold fronts shut the bite down.",
    },
}

# Estimated surface water temperature (deg F) anchors by day of year (seasonal model).
_WATER_TEMP_ANCHORS = [
    (1, 35), (105, 36), (135, 42), (166, 52), (206, 62), (232, 61),
    (263, 54), (293, 45), (324, 39), (354, 35), (366, 35),
]


def _phase_for(d: date) -> str:
    key = "ice_season"
    for (m, day), phase in _PHASES:
        if (d.month, d.day) >= (m, day):
            key = phase
    return key


def _est_water_temp_f(d: date) -> float:
    doy = d.timetuple().tm_yday
    for (d0, t0), (d1, t1) in zip(_WATER_TEMP_ANCHORS, _WATER_TEMP_ANCHORS[1:]):
        if d0 <= doy <= d1:
            return round(t0 + (t1 - t0) * (doy - d0) / (d1 - d0), 1)
    return 35.0


def _sun_times(d: date) -> dict:
    """NOAA solar-position approximation for sunrise, sunset and solar noon."""
    doy = d.timetuple().tm_yday
    g = 2 * math.pi / 365 * (doy - 1)
    eqtime = 229.18 * (0.000075 + 0.001868 * math.cos(g) - 0.032077 * math.sin(g)
                       - 0.014615 * math.cos(2 * g) - 0.040849 * math.sin(2 * g))
    decl = (0.006918 - 0.399912 * math.cos(g) + 0.070257 * math.sin(g)
            - 0.006758 * math.cos(2 * g) + 0.000907 * math.sin(2 * g)
            - 0.002697 * math.cos(3 * g) + 0.00148 * math.sin(3 * g))
    lat = math.radians(LAT)
    ha = math.degrees(math.acos(
        math.cos(math.radians(90.833)) / (math.cos(lat) * math.cos(decl)) - math.tan(lat) * math.tan(decl)
    ))
    midnight_utc = datetime(d.year, d.month, d.day, tzinfo=timezone.utc)

    def at(minutes: float) -> datetime:
        return (midnight_utc + timedelta(minutes=minutes)).astimezone(TZ)

    return {
        "sunrise": at(720 - 4 * (LON + ha) - eqtime),
        "solar_noon": at(720 - 4 * LON - eqtime),
        "sunset": at(720 - 4 * (LON - ha) - eqtime),
    }


def _moon(d: date) -> dict:
    """Moon age and illumination from a reference new moon (2000-01-06 18:14 UTC)."""
    synodic = 29.530588853
    ref = datetime(2000, 1, 6, 18, 14, tzinfo=timezone.utc)
    noon = datetime(d.year, d.month, d.day, 12, tzinfo=TZ)
    age = ((noon - ref).total_seconds() / 86400) % synodic
    illum = round((1 - math.cos(2 * math.pi * age / synodic)) / 2 * 100)
    names = [
        (1.85, "New moon"), (5.54, "Waxing crescent"), (9.23, "First quarter"),
        (12.92, "Waxing gibbous"), (16.61, "Full moon"), (20.30, "Waning gibbous"),
        (23.99, "Last quarter"), (27.68, "Waning crescent"), (29.54, "New moon"),
    ]
    phase = next(n for limit, n in names if age < limit)
    return {"phase": phase, "age_days": round(age, 1), "illumination_pct": illum}


def _fmt(t: datetime) -> str:
    return t.strftime("%H:%M %Z")


# --------------------------------------------------------------------------
# MCP tools
# --------------------------------------------------------------------------
@server.tool()
def get_reservoir_info() -> dict:
    """Get reference information about Georgetown Reservoir (Georgetown Lake), Colorado:
    location, elevation, trout species, access and where to check regulations."""
    return {
        "name": "Georgetown Reservoir (Georgetown Lake)",
        "location": "Town of Georgetown, Clear Creek County, Colorado, next to I-70 (about 45 miles west of Denver)",
        "coordinates": {"latitude": LAT, "longitude": LON},
        "elevation_ft": ELEVATION_FT,
        "trout_species": [
            "Rainbow trout (main catch; stocked by Colorado Parks and Wildlife)",
            "Brown trout (reported by anglers)",
        ],
        "fishing_styles": ["Shore fishing", "Ice fishing in winter", "Fly fishing from shore"],
        "regulations": (
            "A Colorado fishing license is required for anglers 16 and older. Check the current "
            "Colorado Parks and Wildlife (CPW) fishing regulations for bag limits and any special "
            "rules for this lake before you go."
        ),
        "stocking_reports": "CPW publishes fish stocking reports on its website (cpw.state.co.us).",
        "notes": [
            "High-altitude weather changes fast; afternoon wind is common.",
            "The lake sits in a narrow valley, so the sun reaches the water later and leaves earlier than the calculated sunrise and sunset.",
        ],
        "data_quality": "Coordinates and elevation verified against OpenStreetMap and USGS; species, access and regulation details should be confirmed with CPW.",
    }


@server.tool()
def get_seasonal_conditions(date: str = "") -> dict:
    """Get the seasonal fishing picture at Georgetown Reservoir for a date: season phase,
    estimated water temperature, ice status, where trout are holding and activity level.

    Args:
        date: Date as YYYY-MM-DD. Leave empty for today.
    """
    d = _parse_date(date)
    phase = _phase_for(d)
    water_f = _est_water_temp_f(d)
    if water_f < 40:
        temp_note = "Cold water: trout are sluggish, so slow presentations work best."
    elif water_f < 50:
        temp_note = "Cool water: trout are moderately active."
    elif water_f <= 62:
        temp_note = "Ideal trout temperature range (about 50-62 F): trout are very active."
    else:
        temp_note = "Warm surface water: trout go deeper; release fish quickly to reduce stress."
    return {
        "date": d.isoformat(),
        "season_phase": _PHASE_INFO[phase]["label"],
        "estimated_surface_water_temp_f": water_f,
        "water_temp_note": temp_note,
        "ice_status": _PHASE_INFO[phase]["ice_status"],
        "where_trout_are": _PHASE_INFO[phase]["trout_location"],
        "activity": _PHASE_INFO[phase]["activity"],
        "ice_safety_rule": "Common guidance: at least 4 inches of clear, solid ice to walk on. Never trust new, dark, slushy or rotten ice.",
        "data_quality": "ESTIMATE from a seasonal model for an ~8,400 ft Colorado lake, not a live measurement.",
    }


@server.tool()
def get_sun_and_moon(date: str = "") -> dict:
    """Get sunrise, sunset, the best low-light bite windows and the moon phase at
    Georgetown Reservoir for a date (computed locally).

    Args:
        date: Date as YYYY-MM-DD. Leave empty for today.
    """
    d = _parse_date(date)
    sun = _sun_times(d)
    return {
        "date": d.isoformat(),
        "sunrise": _fmt(sun["sunrise"]),
        "sunset": _fmt(sun["sunset"]),
        "solar_noon": _fmt(sun["solar_noon"]),
        "daylight_hours": round((sun["sunset"] - sun["sunrise"]).total_seconds() / 3600, 1),
        "best_bite_windows": [
            f"Morning: {_fmt(sun['sunrise'] - timedelta(minutes=30))} - {_fmt(sun['sunrise'] + timedelta(hours=2))}",
            f"Evening: {_fmt(sun['sunset'] - timedelta(hours=2))} - {_fmt(sun['sunset'] + timedelta(minutes=30))}",
        ],
        "moon": _moon(d),
        "note": "Calculated for a flat horizon; surrounding mountains shorten direct sunlight on the water.",
    }


@server.tool()
def rate_fishing_conditions(
    air_temp_high_f: float,
    wind_mph: float,
    sky: str,
    date: str = "",
    precipitation_chance_pct: float = 0,
    pressure_trend: str = "steady",
) -> dict:
    """Rate trout fishing conditions at Georgetown Reservoir on a 1-10 scale.

    Use weather values from a forecast (for example from the NWS weather agent).

    Args:
        air_temp_high_f: Forecast daytime high air temperature in deg F.
        wind_mph: Typical forecast wind speed in mph (use the middle of a range like "10 to 15 mph").
        sky: Sky cover, one of: "sunny", "partly cloudy", "cloudy", "rain", "snow".
        date: Date as YYYY-MM-DD. Leave empty for today.
        precipitation_chance_pct: Chance of precipitation, 0-100.
        pressure_trend: Barometric pressure trend: "falling", "steady" or "rising".
    """
    d = _parse_date(date)
    phase = _phase_for(d)
    water_f = _est_water_temp_f(d)
    factors = []

    # Water temperature (0-3 points)
    if 50 <= water_f <= 62:
        pts, why = 3.0, "water near the ideal trout range"
    elif 44 <= water_f < 50 or 62 < water_f <= 65:
        pts, why = 2.0, "water a little outside the ideal range"
    elif water_f >= 40:
        pts, why = 1.0, "cold water slows trout down"
    elif water_f < 40:
        pts, why = 0.5, "very cold water: trout are sluggish"
    else:
        pts, why = 0.5, "warm water stresses trout"
    factors.append(("Estimated water temperature", pts, 3, f"{water_f} F: {why}"))

    # Sky / light (0-2)
    s = sky.lower()
    if "snow" in s or "rain" in s:
        pts, why = 1.5, "light precipitation and low light often trigger feeding"
    elif "cloud" in s and "partly" not in s:
        pts, why = 2.0, "overcast skies keep trout feeding longer"
    elif "partly" in s:
        pts, why = 1.5, "mixed light"
    else:
        pts, why = 0.75, "bright sun: fish early and late"
    factors.append(("Sky / light", pts, 2, why))

    # Wind (0-2)
    if wind_mph < 5:
        pts, why = 1.25, "calm: clear water makes trout wary"
    elif wind_mph <= 15:
        pts, why = 2.0, "light chop hides the angler and stirs up food"
    elif wind_mph <= 25:
        pts, why = 0.75, "strong wind makes casting hard; fish the windward shore"
    else:
        pts, why = 0.0, "very windy: difficult and unsafe for small craft"
    factors.append(("Wind", pts, 2, f"{wind_mph} mph: {why}"))

    # Barometric pressure (0-2)
    trend = pressure_trend.lower()
    pts, why = {
        "falling": (2.0, "falling pressure before a front often sparks a bite"),
        "rising": (0.75, "rising pressure after a front often slows the bite"),
    }.get(trend, (1.25, "steady pressure"))
    factors.append(("Pressure trend", pts, 2, why))

    # Air temperature comfort / ice-forming cold (0-1)
    if phase in ("ice_season", "late_fall_ice_up"):
        pts = 1.0 if air_temp_high_f >= 25 else 0.5
        why = "mild winter day" if pts == 1.0 else "bitter cold"
    else:
        pts = 1.0 if 45 <= air_temp_high_f <= 80 else 0.5
        why = "comfortable" if pts == 1.0 else "uncomfortable temperatures"
    factors.append(("Air temperature", pts, 1, f"{air_temp_high_f} F: {why}"))

    raw = sum(f[1] for f in factors)  # max 10
    if precipitation_chance_pct >= 70 and ("rain" in s or "snow" in s):
        raw -= 1.0
        factors.append(("Heavy precipitation risk", -1.0, 0, f"{precipitation_chance_pct}% chance"))
    score = max(1, min(10, round(raw)))
    verdict = (
        "Excellent - go fishing!" if score >= 8 else
        "Good" if score >= 6 else
        "Fair - fish the low-light windows" if score >= 4 else
        "Poor - consider another day"
    )
    warnings = []
    if phase == "late_fall_ice_up":
        warnings.append("Ice-up transition: do NOT walk on new ice; fish from shore only.")
    if phase == "ice_out_spring":
        warnings.append("Ice-out period: stay off rotten ice.")
    if wind_mph > 25:
        warnings.append("High wind: dangerous for float tubes and small boats.")

    return {
        "date": d.isoformat(),
        "season_phase": _PHASE_INFO[phase]["label"],
        "score_1_to_10": score,
        "verdict": verdict,
        "factors": [
            {"factor": f[0], "points": f[1], "max_points": f[2], "reason": f[3]} for f in factors
        ],
        "warnings": warnings,
        "data_quality": "Heuristic score from forecast inputs plus a seasonal water-temperature ESTIMATE.",
    }


@server.tool()
def recommend_tactics(date: str = "", sky: str = "") -> dict:
    """Recommend baits, lures, flies and approach for trout at Georgetown Reservoir.

    Args:
        date: Date as YYYY-MM-DD. Leave empty for today.
        sky: Optional sky cover ("sunny", "cloudy", ...) to fine-tune the advice.
    """
    d = _parse_date(date)
    phase = _phase_for(d)
    tactics = {
        "ice_season": {
            "bait": ["PowerBait or a nightcrawler fished just off the bottom", "Waxworms or mealworms on a small jig"],
            "lures": ["Small tungsten ice jigs (1/32-1/16 oz)", "Small jigging spoons"],
            "flies": ["Not practical through the ice"],
            "approach": "Drill holes in 6-15 ft near drop-offs. Jig slowly, pause often, and move holes if nothing bites in 20-30 minutes.",
        },
        "ice_out_spring": {
            "bait": ["PowerBait on a slip-sinker rig", "Nightcrawlers"],
            "lures": ["Inline spinners (size 1-2)", "Small spoons in gold or silver"],
            "flies": ["Woolly buggers", "Chironomid (midge) patterns under an indicator"],
            "approach": "Fish from shore near the inlet and along shallow flats; trout cruise the shallows right after ice-out.",
        },
        "early_summer": {
            "bait": ["PowerBait", "Nightcrawlers under a bobber"],
            "lures": ["Inline spinners", "Small spoons", "Small crankbaits"],
            "flies": ["Midges and Blue-Winged Olives at dawn", "Caddis and Adams dry flies in the evening"],
            "approach": "Cover water with spinners during the day; switch to dry flies when trout rise in the evening.",
        },
        "midsummer": {
            "bait": ["Bottom rigs with PowerBait in deeper water", "Nightcrawlers"],
            "lures": ["Spoons cast far and counted down", "Spinners at dawn and dusk"],
            "flies": ["Damselfly nymphs", "Hoppers near grassy banks", "Evening caddis"],
            "approach": "Fish early and late; at midday go deeper. Release fish quickly when the water is warm.",
        },
        "fall": {
            "bait": ["Nightcrawlers", "PowerBait"],
            "lures": ["Spoons", "Spinners", "Minnow-imitating crankbaits for browns"],
            "flies": ["Streamers (woolly bugger, sculpin)", "Midges on calm afternoons"],
            "approach": "Trout feed heavily before winter; cover water and try bigger baits for brown trout.",
        },
        "late_fall_ice_up": {
            "bait": ["PowerBait or nightcrawlers fished slowly near bottom"],
            "lures": ["Small spoons retrieved slowly", "Small jigs"],
            "flies": ["Midges", "Small nymphs under an indicator"],
            "approach": "Fish from shore on the mildest afternoons. Do not walk on new ice.",
        },
    }[phase]
    s = sky.lower()
    if "sun" in s:
        tactics["light_tip"] = "Bright sun: use smaller, natural-colored lures and lighter line; fish shaded or deeper water."
    elif "cloud" in s or "snow" in s or "rain" in s:
        tactics["light_tip"] = "Low light: brighter or flashier lures work well, and trout may feed in shallower water."
    return {"date": d.isoformat(), "season_phase": _PHASE_INFO[phase]["label"], **tactics}


if __name__ == "__main__":
    server.run("stdio")
