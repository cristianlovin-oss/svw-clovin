"""MCP server: National Weather Service (api.weather.gov) weather tools.

Exposes Python functions as MCP tools over stdio. No API key is needed; the
NWS only asks for a descriptive User-Agent.

Run standalone (for debugging):  python mcp_servers/nws_weather_server.py
"""

import logging
import math

import httpx
from mcp.server.mcpserver import MCPServer

logging.getLogger("httpx").setLevel(logging.WARNING)  # keep stderr quiet

NWS_API = "https://api.weather.gov"
HEADERS = {
    "User-Agent": "adk-challenge-3-mcp/1.0 (educational demo)",
    "Accept": "application/geo+json",
}

server = MCPServer(
    name="nws-weather",
    instructions=(
        "Weather data from the US National Weather Service. Works only for "
        "locations in the United States. All tools take latitude/longitude in "
        "decimal degrees."
    ),
)


async def _get(client: httpx.AsyncClient, url: str, **params) -> dict:
    resp = await client.get(url, params=params or None)
    resp.raise_for_status()
    return resp.json()


async def _point(client: httpx.AsyncClient, latitude: float, longitude: float) -> dict:
    """Resolve a lat/lon to the NWS forecast grid for that point."""
    data = await _get(client, f"{NWS_API}/points/{latitude:.4f},{longitude:.4f}")
    return data["properties"]


def _client() -> httpx.AsyncClient:
    return httpx.AsyncClient(headers=HEADERS, timeout=20, follow_redirects=True)


def _c_to_f(value):
    return None if value is None else round(value * 9 / 5 + 32, 1)


def _haversine_miles(lat1, lon1, lat2, lon2) -> float:
    r = 3958.8
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = p2 - p1, math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return round(2 * r * math.asin(math.sqrt(a)), 1)


@server.tool()
async def get_forecast(latitude: float, longitude: float, periods: int = 6) -> dict:
    """Get the NWS multi-day forecast (12-hour day/night periods) for a US location.

    Args:
        latitude: Latitude in decimal degrees (e.g. 39.7269 for Georgetown Lake, CO).
        longitude: Longitude in decimal degrees (e.g. -105.6919).
        periods: Number of 12-hour periods to return (1-14, default 6 = 3 days).
    """
    periods = max(1, min(int(periods), 14))
    async with _client() as client:
        point = await _point(client, latitude, longitude)
        data = await _get(client, point["forecast"])
    loc = point["relativeLocation"]["properties"]
    return {
        "location": f"{loc['city']}, {loc['state']}",
        "nws_office": point["gridId"],
        "generated_at": data["properties"].get("generatedAt"),
        "periods": [
            {
                "name": p["name"],
                "start": p["startTime"],
                "temperature_f": p["temperature"],
                "wind": f"{p['windSpeed']} {p['windDirection']}",
                "precipitation_chance_pct": (p.get("probabilityOfPrecipitation") or {}).get("value"),
                "short_forecast": p["shortForecast"],
                "detailed_forecast": p["detailedForecast"],
            }
            for p in data["properties"]["periods"][:periods]
        ],
        "source": "National Weather Service (api.weather.gov)",
    }


@server.tool()
async def get_hourly_forecast(latitude: float, longitude: float, hours: int = 12) -> dict:
    """Get the NWS hour-by-hour forecast for a US location.

    Args:
        latitude: Latitude in decimal degrees.
        longitude: Longitude in decimal degrees.
        hours: Number of hours to return (1-48, default 12).
    """
    hours = max(1, min(int(hours), 48))
    async with _client() as client:
        point = await _point(client, latitude, longitude)
        data = await _get(client, point["forecastHourly"])
    return {
        "location": "{city}, {state}".format(**point["relativeLocation"]["properties"]),
        "hours": [
            {
                "start": p["startTime"],
                "temperature_f": p["temperature"],
                "wind": f"{p['windSpeed']} {p['windDirection']}",
                "precipitation_chance_pct": (p.get("probabilityOfPrecipitation") or {}).get("value"),
                "short_forecast": p["shortForecast"],
            }
            for p in data["properties"]["periods"][:hours]
        ],
        "source": "National Weather Service (api.weather.gov)",
    }


@server.tool()
async def get_current_conditions(latitude: float, longitude: float) -> dict:
    """Get the latest observed weather from the closest NWS observation station.

    Includes temperature, wind, humidity and barometric pressure. Note that in
    the mountains the closest station can be some distance away.

    Args:
        latitude: Latitude in decimal degrees.
        longitude: Longitude in decimal degrees.
    """
    async with _client() as client:
        point = await _point(client, latitude, longitude)
        stations = (await _get(client, point["observationStations"]))["features"][:15]
        nearest = min(
            stations,
            key=lambda s: _haversine_miles(
                latitude, longitude, s["geometry"]["coordinates"][1], s["geometry"]["coordinates"][0]
            ),
        )
        sid = nearest["properties"]["stationIdentifier"]
        obs = (await _get(client, f"{NWS_API}/stations/{sid}/observations/latest"))["properties"]

    wind_kmh = (obs.get("windSpeed") or {}).get("value")
    pressure_pa = (obs.get("barometricPressure") or {}).get("value")
    return {
        "station": f"{sid} - {nearest['properties']['name']}",
        "station_distance_miles": _haversine_miles(
            latitude, longitude,
            nearest["geometry"]["coordinates"][1], nearest["geometry"]["coordinates"][0],
        ),
        "observed_at": obs.get("timestamp"),
        "description": obs.get("textDescription"),
        "temperature_f": _c_to_f((obs.get("temperature") or {}).get("value")),
        "wind_mph": None if wind_kmh is None else round(wind_kmh * 0.621371, 1),
        "relative_humidity_pct": (obs.get("relativeHumidity") or {}).get("value"),
        "barometric_pressure_inhg": None if pressure_pa is None else round(pressure_pa / 3386.39, 2),
        "source": "National Weather Service (api.weather.gov)",
    }


@server.tool()
async def get_active_alerts(latitude: float, longitude: float) -> dict:
    """Get active NWS weather alerts (warnings, watches, advisories) for a US location.

    Args:
        latitude: Latitude in decimal degrees.
        longitude: Longitude in decimal degrees.
    """
    async with _client() as client:
        data = await _get(client, f"{NWS_API}/alerts/active", point=f"{latitude:.4f},{longitude:.4f}")
    alerts = [
        {
            "event": a["properties"]["event"],
            "severity": a["properties"]["severity"],
            "headline": a["properties"]["headline"],
            "effective": a["properties"]["effective"],
            "expires": a["properties"]["expires"],
            "instruction": a["properties"].get("instruction"),
        }
        for a in data["features"]
    ]
    return {"active_alert_count": len(alerts), "alerts": alerts, "source": "National Weather Service"}


if __name__ == "__main__":
    server.run("stdio")
