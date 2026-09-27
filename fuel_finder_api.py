"""
fuel_finder_api.py

Real, fully-automated access to the Fuel Finder Information Recipient API -
no browser, no login, no manually-copied link, unlike the CSV route.
Confirmed working 2026-09-27 by testing directly against the live API
(the official docs' own example domain/paths didn't work - the real ones
were only found by opening the portal's rendered Swagger pages by hand):

  Token:  POST https://www.fuel-finder.service.gov.uk/api/v1/oauth/generate_access_token
          grant_type=client_credentials&client_id=...&client_secret=...&scope=fuelfinder.read
          -> {access_token, token_type, expires_in (3600s), refresh_token, refresh_token_expires_in (172800s)}

  Prices: GET https://www.fuel-finder.service.gov.uk/api/v1/pfs/fuel-prices?batch-number=N
          -> [{node_id, public_phone_number, trading_name, fuel_prices: [{fuel_type, price, ...}]}]

  Info:   GET https://www.fuel-finder.service.gov.uk/api/v1/pfs?batch-number=N
          -> [{node_id, trading_name, brand_name, location: {...}, amenities: [...], fuel_types: [...], ...}]

Both list endpoints page via batch-number, 500 stations per batch, and
return a 404 ("Requested batch N is not available") once you're past the
last page - that 404 is the normal, expected end-of-data signal, not an
error to alarm about.

client_id/client_secret come from FUEL_FINDER_CLIENT_ID /
FUEL_FINDER_CLIENT_SECRET environment variables - never hardcoded here.
"""

import json
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime

BASE_URL = "https://www.fuel-finder.service.gov.uk/api/v1"
BATCH_SIZE = 500

# The CSV export's fuel-grade codes differ slightly from the API's -
# normalized to the CSV's shorter codes so the rest of this project
# (generate_fuel_map.py's FUEL_CODES/FUEL_LABEL, the map's JS) doesn't
# need to know or care which data source it came from.
FUEL_TYPE_MAP = {
    "E5": "E5", "E10": "E10",
    "B7_STANDARD": "B7S", "B7_PREMIUM": "B7P",
    "B10": "B10", "HVO": "HVO",
}


def _request(method, path, token=None, data=None):
    url = f"{BASE_URL}{path}"
    headers = {"User-Agent": "Mozilla/5.0"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    body = None
    if data is not None:
        headers["Content-Type"] = "application/x-www-form-urlencoded"
        body = urllib.parse.urlencode(data).encode("utf-8")
    req = urllib.request.Request(url, data=body, headers=headers, method=method)
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read().decode("utf-8"))


def get_access_token(client_id, client_secret):
    result = _request("POST", "/oauth/generate_access_token", data={
        "grant_type": "client_credentials",
        "client_id": client_id,
        "client_secret": client_secret,
        "scope": "fuelfinder.read",
    })
    return result["data"]["access_token"]


def fetch_all_batches(path, token):
    """Pages through batch-number=1,2,3... until the API 404s (the normal
    end-of-data signal), returning every item concatenated."""
    items = []
    batch = 1
    while True:
        try:
            page = _request("GET", f"{path}?batch-number={batch}", token=token)
        except urllib.error.HTTPError as e:
            if e.code == 404:
                break
            raise
        if not page:
            break
        items.extend(page)
        batch += 1
    return items


def fetch_stations(client_id, client_secret, progress=None):
    """Returns (stations, skipped_closed) - the same shape
    generate_fuel_map.load_stations() produces from the CSV, so the rest
    of the pipeline (generate_html etc.) doesn't need to know which
    source it came from."""
    token = get_access_token(client_id, client_secret)
    if progress: progress("Got access token, fetching station info...")

    info_rows = fetch_all_batches("/pfs", token)
    if progress: progress(f"Fetched info for {len(info_rows)} stations, fetching prices...")

    price_rows = fetch_all_batches("/pfs/fuel-prices", token)
    if progress: progress(f"Fetched prices for {len(price_rows)} stations.")

    prices_by_node = {}
    for row in price_rows:
        prices = {}
        for fp in row.get("fuel_prices", []):
            code = FUEL_TYPE_MAP.get(fp["fuel_type"], fp["fuel_type"])
            price = fp.get("price")
            if price is not None:
                prices[code] = round(float(price), 1)
        prices_by_node[row["node_id"]] = {
            "prices": prices,
            "updated": max((fp.get("price_last_updated") for fp in row.get("fuel_prices", []) if fp.get("price_last_updated")), default=None),
        }

    stations = []
    skipped_closed = 0
    for row in info_rows:
        if row.get("permanent_closure"):
            skipped_closed += 1
            continue

        loc = row.get("location", {})
        try:
            lat, lon = float(loc["latitude"]), float(loc["longitude"])
        except (KeyError, TypeError, ValueError):
            continue

        address = ", ".join(p.strip() for p in [
            loc.get("address_line_1", ""), loc.get("address_line_2", ""),
            loc.get("city", ""), loc.get("county", ""), loc.get("postcode", ""),
        ] if p and p.strip())

        amenities = set(row.get("amenities") or [])
        price_info = prices_by_node.get(row["node_id"], {"prices": {}, "updated": None})

        updated_display = None
        if price_info["updated"]:
            # '2026-09-27T16:50:39.000Z' -> '27 Sep 2026, 16:50'
            try:
                dt = datetime.strptime(price_info["updated"], "%Y-%m-%dT%H:%M:%S.%fZ")
                updated_display = dt.strftime("%d %b %Y, %H:%M").lstrip("0")
            except ValueError:
                updated_display = price_info["updated"]

        stations.append({
            "id": row["node_id"],
            "name": (row.get("trading_name") or "").strip(),
            "brand": (row.get("brand_name") or "").strip().upper() or "INDEPENDENT",
            "lat": lat, "lon": lon,
            "address": address,
            "phone": (row.get("public_phone_number") or "").strip(),
            "motorway": bool(row.get("is_motorway_service_station")),
            "supermarket": bool(row.get("is_supermarket_service_station")),
            "temp_closed": bool(row.get("temporary_closure")),
            "prices": price_info["prices"],
            "updated": updated_display,
            "adblue": "adblue_pumps" in amenities or "adblue_packaged" in amenities,
            "car_wash": "car_wash" in amenities,
            "toilets": "customer_toilets" in amenities,
            "hr24": "twenty_four_hour_fuel" in amenities,
        })

    return stations, skipped_closed
