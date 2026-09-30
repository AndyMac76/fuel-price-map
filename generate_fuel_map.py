"""
generate_fuel_map.py

Builds a self-contained HTML map of UK fuel prices from the official
government Fuel Finder open data scheme.

Two data sources, in priority order:

  1. The Fuel Finder API (fuel_finder_api.py) - fully automated, no
     browser or manual step needed. Used automatically whenever
     FUEL_FINDER_CLIENT_ID and FUEL_FINDER_CLIENT_SECRET are set (get
     them once from developer.fuel-finder.service.gov.uk, behind a
     GOV.UK One Login - a one-time registration, not a recurring one).
     The API's real base URL/endpoints aren't the ones shown in its own
     example docs (which don't resolve) - see fuel_finder_api.py for
     what was actually confirmed working.
  2. The CSV export - a manual fallback if API credentials aren't set,
     or forced with --csv/--csv-url. The CSV lives in an S3 bucket
     behind a pre-signed URL you copy from the developer portal - the
     signed URL itself needs no login/cookies once you have it, but
     it's only valid for ~12 hours and points at one specific publish,
     so there's no single permanent link like the API's credentials are.

Real-world data quirks handled here:
  - brand_name casing is inconsistent across retailers (ESSO/Esso/esso,
    TEXACO/Texaco, etc.) - normalized to uppercase for grouping/display,
    otherwise the brand filter would list the same chain multiple times.
  - country field is too inconsistent to be usable (WALES/England/
    ENGLAND/''/UNITED KINGDOM/E/W/S/UK/N all appear for what should be
    4 values) - not used for anything, lat/lon (always present) drives
    the map instead.
  - Permanently closed stations are excluded; temporarily closed ones
    are kept but flagged, since that's often just a short outage.
  - A station only sells some fuel grades - missing prices are just
    left out rather than shown as zero.

Usage:
    python generate_fuel_map.py                   # uses the API if
                                                    # FUEL_FINDER_CLIENT_ID/
                                                    # SECRET are set, else
                                                    # falls back to the
                                                    # newest CSV in Downloads
    python generate_fuel_map.py --csv path\to.csv  # force a specific CSV
    python generate_fuel_map.py --csv-url "https://...s3...&X-Amz-Signature=..."
                                                    # force a fresh pre-signed
                                                    # CSV link
"""

import argparse
import csv
import glob
import io
import json
import os
import urllib.request
from datetime import datetime

OUTPUT_FILE = "fuel_map.html"

FUEL_CODES = ["E10", "E5", "B7S", "B7P", "B10", "HVO"]
FUEL_LABEL = {
    "E10": "Unleaded (E10)",
    "E5": "Super Unleaded (E5)",
    "B7S": "Diesel (B7)",
    "B7P": "Premium Diesel (B7)",
    "B10": "Diesel (B10)",
    "HVO": "HVO (Renewable Diesel)",
}


def find_latest_csv(downloads_dir=None):
    downloads_dir = downloads_dir or os.path.join(os.path.expanduser("~"), "Downloads")
    candidates = glob.glob(os.path.join(downloads_dir, "UpdatedFuelPrice-*.csv"))
    if not candidates:
        return None
    return max(candidates, key=os.path.getmtime)


def parse_timestamp(raw):
    """'Fri Sep 25 2026 15:21:25 GMT+0000 (Coordinated Universal Time)' ->
    '25 Sep 2026, 15:21'. Falls back to the raw string if the format ever
    changes - a display glitch, not a reason to crash the whole build."""
    if not raw:
        return None
    try:
        cleaned = raw.split(" (")[0]
        dt = datetime.strptime(cleaned, "%a %b %d %Y %H:%M:%S GMT%z")
        # %-d (no leading zero) isn't portable to Windows' strftime, so pad
        # with %d and manually strip a leading zero instead.
        return dt.strftime("%d %b %Y, %H:%M").lstrip("0")
    except (ValueError, IndexError):
        return raw


def parse_price(raw):
    if not raw:
        return None
    try:
        return round(float(raw), 1)
    except ValueError:
        return None


def build_address(row):
    parts = [
        row.get("forecourts.location.address_line_1", ""),
        row.get("forecourts.location.address_line_2", ""),
        row.get("forecourts.location.city", ""),
        row.get("forecourts.location.county", ""),
        row.get("forecourts.location.postcode", ""),
    ]
    return ", ".join(p.strip() for p in parts if p and p.strip())


def fetch_csv_text(url):
    """Fetches a Fuel Finder pre-signed S3 URL directly - confirmed this
    needs no browser/cookies/login, the auth is entirely in the URL's own
    query-string signature. Only works for ~12 hours from when the link
    was generated (X-Amz-Expires in the URL) and only for that specific
    publish (the S3 key changes every time a new one's published), so
    there's no single reusable link - always needs a fresh one from the
    portal's download page."""
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=60) as resp:
        return resp.read().decode("utf-8-sig")


def load_stations(csv_file):
    """csv_file: an already-open text-mode file-like object (a local file,
    or an io.StringIO wrapping fetched CSV text)."""
    stations = []
    skipped_closed = 0
    with csv_file as f:
        reader = csv.DictReader(f)
        for row in reader:
            if row.get("forecourts.permanent_closure", "").strip().lower() == "true":
                skipped_closed += 1
                continue

            try:
                lat = float(row["forecourts.location.latitude"])
                lon = float(row["forecourts.location.longitude"])
            except (ValueError, KeyError):
                continue

            prices = {}
            for code in FUEL_CODES:
                p = parse_price(row.get(f"forecourts.fuel_price.{code}"))
                if p is not None:
                    prices[code] = p

            brand = (row.get("forecourts.brand_name") or "").strip().upper() or "INDEPENDENT"

            stations.append({
                "id": row.get("forecourts.node_id"),
                "name": row.get("forecourts.trading_name", "").strip(),
                "brand": brand,
                "lat": lat,
                "lon": lon,
                "address": build_address(row),
                "phone": row.get("forecourts.public_phone_number", "").strip(),
                "motorway": row.get("forecourts.is_motorway_service_station", "").lower() == "true",
                "supermarket": row.get("forecourts.is_supermarket_service_station", "").lower() == "true",
                "temp_closed": row.get("forecourts.temporary_closure", "").lower() == "true",
                "prices": prices,
                "updated": parse_timestamp(row.get("forecourt_update_timestamp")),
                "adblue": row.get("forecourts.amenities.fuel_and_energy_services.adblue_pumps", "").lower() == "true",
                "car_wash": row.get("forecourts.amenities.vehicle_services.car_wash", "").lower() == "true",
                "toilets": row.get("forecourts.amenities.customer_toilets", "").lower() == "true",
                "hr24": row.get("forecourts.amenities.twenty_four_hour_fuel", "").lower() == "true",
            })

    return stations, skipped_closed


def generate_html(stations, source_file, maptiler_key):
    brands = sorted({s["brand"] for s in stations})
    generated_at = datetime.now().strftime("%d %b %Y, %H:%M")

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>UK Fuel Price Map</title>
<link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css" />
<link rel="stylesheet" href="https://unpkg.com/leaflet.markercluster@1.5.3/dist/MarkerCluster.css" />
<link rel="stylesheet" href="https://unpkg.com/leaflet.markercluster@1.5.3/dist/MarkerCluster.Default.css" />
<style>
    :root {{
        --bg: #0f1420;
        --card-bg: #171d2c;
        --border: #2e3a52;
        --text: #e8e8e8;
        --text-dim: #9fb3d9;
        --muted: #6d7891;
        --accent: #3b82f6;
        --accent-dim: #1e3a5f;
        --green: #3fbf5f;
        --amber: #e0a83c;
        --red: #d95c5c;
    }}
    * {{ box-sizing: border-box; }}
    html, body {{ height: 100%; margin: 0; }}
    body {{
        font-family: -apple-system, Segoe UI, Arial, sans-serif;
        background: var(--bg);
        color: var(--text);
        display: flex;
        flex-direction: column;
    }}
    header {{
        padding: 12px 18px;
        border-bottom: 1px solid var(--border);
        background: var(--card-bg);
        display: flex;
        flex-wrap: wrap;
        align-items: center;
        gap: 14px;
    }}
    header h1 {{ font-size: 18px; margin: 0; white-space: nowrap; }}
    .meta {{ font-size: 12px; color: var(--text-dim); white-space: nowrap; }}
    .controls {{ display: flex; flex-wrap: wrap; gap: 10px; margin-left: auto; align-items: center; }}
    .controls label {{ font-size: 11px; color: var(--text-dim); display: block; margin-bottom: 2px; }}
    select, button {{
        background: var(--bg);
        color: var(--text);
        border: 1px solid var(--border);
        border-radius: 6px;
        padding: 6px 10px;
        font-size: 13px;
    }}
    select {{ max-width: 220px; }}
    button {{ cursor: pointer; background: var(--accent-dim); border-color: var(--accent); }}
    button:hover {{ background: var(--accent); }}
    .main {{ flex: 1; display: flex; min-height: 0; }}
    #map {{ flex: 1; }}
    #sidebar {{
        width: 300px;
        min-width: 300px;
        background: var(--card-bg);
        border-left: 1px solid var(--border);
        overflow-y: auto;
        padding: 12px;
    }}
    #sidebar h2 {{ font-size: 13px; color: var(--text-dim); margin: 4px 0 10px 0; text-transform: uppercase; letter-spacing: 0.03em; }}

    /* Below tablet-portrait width: a fixed 300px sidebar beside the map
       would crush the map to almost nothing on a phone. Stack them
       instead - map gets a fixed height so it's still genuinely usable,
       sidebar goes full-width below it (arguably the more useful half
       on mobile anyway - "where's cheap fuel near me" is a list
       question more than a map-browsing one). */
    @media (max-width: 700px) {{
        header {{ padding: 10px 12px; gap: 8px; }}
        header h1 {{ font-size: 16px; }}
        .meta {{ white-space: normal; }}
        .controls {{ margin-left: 0; width: 100%; gap: 8px; }}
        .controls > div {{ flex: 1 1 calc(50% - 8px); min-width: 110px; }}
        select {{ max-width: none; width: 100%; }}
        button {{ width: 100%; }}
        .main {{ flex-direction: column; }}
        #map {{ flex: none; height: 50vh; min-height: 260px; }}
        #sidebar {{ width: 100%; min-width: 0; border-left: none; border-top: 1px solid var(--border); flex: 1; }}
        select, button {{ padding: 10px 12px; font-size: 14px; }}
    }}
    .cheap-row {{
        display: flex;
        justify-content: space-between;
        align-items: center;
        padding: 8px 6px;
        border-bottom: 1px solid var(--border);
        cursor: pointer;
        font-size: 13px;
    }}
    .cheap-row:hover {{ background: var(--accent-dim); }}
    .cheap-row .name {{ font-weight: 600; }}
    .cheap-row .sub {{ font-size: 11px; color: var(--muted); }}
    .cheap-row .price {{ font-weight: 700; color: var(--green); font-size: 15px; }}
    .popup-title {{ font-weight: 700; font-size: 14px; margin-bottom: 2px; }}
    .popup-sub {{ font-size: 11px; color: #666; margin-bottom: 8px; }}
    .popup-prices {{ display: grid; grid-template-columns: 1fr auto; gap: 3px 10px; font-size: 13px; margin-bottom: 6px; }}
    .popup-badges {{ display: flex; flex-wrap: wrap; gap: 4px; margin-top: 6px; }}
    .badge {{ font-size: 10px; background: #eee; color: #333; border-radius: 4px; padding: 2px 6px; }}
    .badge.closed {{ background: var(--red); color: white; }}
    .popup-updated {{ font-size: 10px; color: #888; margin-top: 6px; }}
    .leaflet-popup-content-wrapper {{ border-radius: 8px; }}
</style>
</head>
<body>
    <header>
        <h1>&#9981; UK Fuel Price Map</h1>
        <span class="meta">Last updated: {generated_at} &middot; {len(stations)} stations &middot; {source_file}</span>
        <div class="controls">
            <div>
                <label for="fuelSelect">Fuel type</label>
                <select id="fuelSelect"></select>
            </div>
            <div>
                <label for="brandSelect">Brand</label>
                <select id="brandSelect"><option value="">All brands</option></select>
            </div>
            <div>
                <label for="radiusSelect">Radius</label>
                <select id="radiusSelect">
                    <option value="">All stations</option>
                    <option value="5">5 miles</option>
                    <option value="10" selected>10 miles</option>
                    <option value="20">20 miles</option>
                </select>
            </div>
            <div>
                <label>&nbsp;</label>
                <button id="locateBtn">Use my location</button>
            </div>
        </div>
    </header>
    <div class="main">
        <div id="map"></div>
        <div id="sidebar">
            <h2 id="cheapestTitle">Cheapest overall</h2>
            <div id="cheapestList"></div>
        </div>
    </div>

<script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
<script src="https://unpkg.com/leaflet.markercluster@1.5.3/dist/leaflet.markercluster.js"></script>
<script>
    const STATIONS = {json.dumps(stations)};
    const FUEL_LABEL = {json.dumps(FUEL_LABEL)};
    const FUEL_CODES = {json.dumps(FUEL_CODES)};
    const BRANDS = {json.dumps(brands)};

    const fuelSelect = document.getElementById('fuelSelect');
    FUEL_CODES.forEach(code => {{
        const opt = document.createElement('option');
        opt.value = code;
        opt.textContent = FUEL_LABEL[code];
        fuelSelect.appendChild(opt);
    }});
    fuelSelect.value = 'E10';

    const brandSelect = document.getElementById('brandSelect');
    BRANDS.forEach(b => {{
        const opt = document.createElement('option');
        opt.value = b;
        opt.textContent = b.charAt(0) + b.slice(1).toLowerCase();
        brandSelect.appendChild(opt);
    }});

    const radiusSelect = document.getElementById('radiusSelect');

    const map = L.map('map').setView([54.5, -3.5], 6);
    // MapTiler, with a real API key - free-tier OSM tile CDNs (osm.org
    // itself, then CARTO) both ended up blocking requests from a locally-
    // opened file:// page (no legitimate web Referer to show them). A
    // registered key sidesteps that entirely.
    L.tileLayer('https://api.maptiler.com/maps/streets-v4/{{z}}/{{x}}/{{y}}.png?key={maptiler_key}', {{
        attribution: '<a href="https://www.maptiler.com/copyright/" target="_blank">&copy; MapTiler</a> &copy; OpenStreetMap contributors',
        maxZoom: 19,
        crossOrigin: true,
    }}).addTo(map);

    let markerCluster = null;
    let markersById = {{}};

    function priceColor(price, min, max) {{
        if (price === undefined || min === max) return '#3b82f6';
        const t = (price - min) / (max - min);
        // green (cheap) -> amber -> red (expensive)
        if (t < 0.5) {{
            const u = t / 0.5;
            return interpolateColor('#3fbf5f', '#e0a83c', u);
        }}
        const u = (t - 0.5) / 0.5;
        return interpolateColor('#e0a83c', '#d95c5c', u);
    }}

    function interpolateColor(a, b, t) {{
        const pa = hexToRgb(a), pb = hexToRgb(b);
        const r = Math.round(pa[0] + (pb[0] - pa[0]) * t);
        const g = Math.round(pa[1] + (pb[1] - pa[1]) * t);
        const bl = Math.round(pa[2] + (pb[2] - pa[2]) * t);
        return `rgb(${{r}},${{g}},${{bl}})`;
    }}

    function hexToRgb(hex) {{
        const n = parseInt(hex.slice(1), 16);
        return [(n >> 16) & 255, (n >> 8) & 255, n & 255];
    }}

    function makeIcon(color) {{
        return L.divIcon({{
            className: '',
            html: `<div style="background:${{color}};width:14px;height:14px;border-radius:50%;border:2px solid white;box-shadow:0 0 3px rgba(0,0,0,0.6);"></div>`,
            iconSize: [14, 14],
            iconAnchor: [7, 7],
        }});
    }}

    function popupHtml(s) {{
        const priceRows = FUEL_CODES
            .filter(c => s.prices[c] !== undefined)
            .map(c => `<div>${{FUEL_LABEL[c]}}</div><div><strong>${{s.prices[c].toFixed(1)}}p</strong></div>`)
            .join('');
        const badges = [];
        if (s.motorway) badges.push('Motorway services');
        if (s.supermarket) badges.push('Supermarket');
        if (s.hr24) badges.push('24hr fuel');
        if (s.adblue) badges.push('AdBlue');
        if (s.car_wash) badges.push('Car wash');
        if (s.toilets) badges.push('Toilets');
        if (s.temp_closed) badges.push('<span class="badge closed">Temporarily closed</span>');
        return `
            <div class="popup-title">${{s.name}}</div>
            <div class="popup-sub">${{s.brand.charAt(0) + s.brand.slice(1).toLowerCase()}} &middot; ${{s.address}}</div>
            <div class="popup-prices">${{priceRows || '<div class="muted">No current prices reported</div>'}}</div>
            <div class="popup-badges">${{badges.filter(b => !b.startsWith('<span')).map(b => `<span class="badge">${{b}}</span>`).join('')}}${{s.temp_closed ? '<span class="badge closed">Temporarily closed</span>' : ''}}</div>
            <div class="popup-updated">Updated: ${{s.updated || 'unknown'}}</div>
        `;
    }}

    function haversine(lat1, lon1, lat2, lon2) {{
        const R = 3958.8; // miles
        const dLat = (lat2 - lat1) * Math.PI / 180;
        const dLon = (lon2 - lon1) * Math.PI / 180;
        const a = Math.sin(dLat/2)**2 + Math.cos(lat1*Math.PI/180) * Math.cos(lat2*Math.PI/180) * Math.sin(dLon/2)**2;
        return R * 2 * Math.asin(Math.sqrt(a));
    }}

    let userLocation = null;

    function render() {{
        const fuel = fuelSelect.value;
        const brand = brandSelect.value;
        const radius = radiusSelect.value ? parseFloat(radiusSelect.value) : null;

        if (markerCluster) map.removeLayer(markerCluster);
        markerCluster = L.markerClusterGroup();
        markersById = {{}};

        let visible = STATIONS.filter(s => (!brand || s.brand === brand) && s.prices[fuel] !== undefined);

        // Radius only means anything once we know where "here" is - with
        // no location set yet, the dropdown's selection just sits ready
        // for when "Use my location" is pressed.
        if (userLocation) {{
            visible = visible.map(s => ({{ ...s, dist: haversine(userLocation.lat, userLocation.lon, s.lat, s.lon) }}));
            if (radius) visible = visible.filter(s => s.dist <= radius);
        }}

        const prices = visible.map(s => s.prices[fuel]);
        const min = Math.min(...prices), max = Math.max(...prices);

        visible.forEach(s => {{
            const marker = L.marker([s.lat, s.lon], {{ icon: makeIcon(priceColor(s.prices[fuel], min, max)) }});
            marker.bindPopup(popupHtml(s));
            markerCluster.addLayer(marker);
            markersById[s.id] = marker;
        }});
        map.addLayer(markerCluster);

        renderCheapest(visible, fuel);
    }}

    function renderCheapest(visible, fuel) {{
        const title = document.getElementById('cheapestTitle');
        const list = document.getElementById('cheapestList');
        let candidates = visible.slice();

        if (!userLocation) {{
            // A nationwide "cheapest overall" is pointless when the actual
            // cheapest station could be 200 miles away - only show a
            // distance-bounded list, never an unbounded one.
            title.textContent = 'Cheapest near you';
            list.innerHTML = `
                <p style="color:var(--muted);font-size:13px;">
                    Enable location access (or click "Use my location" above) to see prices near you.
                </p>`;
            return;
        }}

        title.textContent = radiusSelect.value ? `Cheapest within ${{radiusSelect.value}} miles` : 'Cheapest near you';
        candidates = candidates.sort((a, b) => a.prices[fuel] - b.prices[fuel]);

        list.innerHTML = candidates.slice(0, 25).map(s => `
            <div class="cheap-row" data-id="${{s.id}}">
                <div>
                    <div class="name">${{s.name}}</div>
                    <div class="sub">${{s.brand.charAt(0) + s.brand.slice(1).toLowerCase()}}${{s.dist !== undefined ? ' &middot; ' + s.dist.toFixed(1) + ' mi' : ''}}</div>
                </div>
                <div class="price">${{s.prices[fuel].toFixed(1)}}p</div>
            </div>
        `).join('') || '<p style="color:var(--muted);font-size:13px;">No stations within this radius.</p>';

        list.querySelectorAll('.cheap-row').forEach(row => {{
            row.addEventListener('click', () => {{
                const marker = markersById[row.dataset.id];
                if (!marker) return;
                map.setView(marker.getLatLng(), 14);
                markerCluster.zoomToShowLayer(marker, () => marker.openPopup());
            }});
        }});
    }}

    function locate(onDenied) {{
        if (!navigator.geolocation) {{ if (onDenied) onDenied(); return; }}
        navigator.geolocation.getCurrentPosition(pos => {{
            userLocation = {{ lat: pos.coords.latitude, lon: pos.coords.longitude }};
            map.setView([userLocation.lat, userLocation.lon], 12);
            render();
        }}, () => {{ if (onDenied) onDenied(); }});
    }}

    document.getElementById('locateBtn').addEventListener('click', () => {{
        locate(() => alert('Could not get your location - check this browser/site has location permission.'));
    }});

    fuelSelect.addEventListener('change', render);
    brandSelect.addEventListener('change', render);
    radiusSelect.addEventListener('change', render);

    render();
    // Ask for location straight away rather than waiting for the button -
    // renderCheapest() shows a plain prompt instead of a list until this
    // resolves one way or the other, so there's never a moment where it's
    // silently showing something a few hundred miles away.
    locate(() => {{}});
</script>
</body>
</html>"""


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--csv", help="Path to the Fuel Finder CSV export. Forces the CSV route "
                                       "instead of the API even if API credentials are set.")
    parser.add_argument("--csv-url", help="A fresh pre-signed S3 URL copied from the Fuel Finder "
                                           "developer portal's download page - fetched directly, no "
                                           "file download needed. Only valid for ~12 hours and one "
                                           "specific publish. Forces the CSV route.")
    parser.add_argument("--maptiler-key", help="MapTiler API key (free, from "
                                                "cloud.maptiler.com/account/keys). Defaults to the "
                                                "MAPTILER_KEY environment variable - kept out of this "
                                                "file itself so it's never sitting in plain text in git.")
    args = parser.parse_args()

    maptiler_key = args.maptiler_key or os.environ.get("MAPTILER_KEY")
    if not maptiler_key:
        print("No MapTiler API key found. Get a free one from cloud.maptiler.com/account/keys, "
              "then either set the MAPTILER_KEY environment variable or pass --maptiler-key <key>.")
        return

    client_id = os.environ.get("FUEL_FINDER_CLIENT_ID")
    client_secret = os.environ.get("FUEL_FINDER_CLIENT_SECRET")
    use_api = bool(client_id and client_secret) and not (args.csv or args.csv_url)

    if use_api:
        import fuel_finder_api
        print("Fetching live data from the Fuel Finder API...")
        try:
            stations, skipped_closed = fuel_finder_api.fetch_stations(client_id, client_secret, progress=print)
        except Exception as e:
            print(f"API fetch failed: {e}\nFalling back to CSV - grab one from the developer portal "
                  "and pass --csv <path> or --csv-url <link>, or drop a file in your Downloads folder.")
            return
        source_label = f"Fuel Finder API ({datetime.now().strftime('%d %b %Y, %H:%M')})"
    elif args.csv_url:
        print("Fetching CSV from the provided URL...")
        try:
            csv_text = fetch_csv_text(args.csv_url)
        except Exception as e:
            print(f"Couldn't fetch --csv-url: {e}\n"
                  "The link may have expired (~12 hours) or already been superseded by a newer "
                  "publish - grab a fresh one from the portal's download page and try again.")
            return
        csv_file = io.StringIO(csv_text)
        source_label = f"live fetch ({datetime.now().strftime('%d %b %Y, %H:%M')})"
        stations, skipped_closed = load_stations(csv_file)
    else:
        csv_path = args.csv or find_latest_csv()
        if not csv_path or not os.path.exists(csv_path):
            print("No FUEL_FINDER_CLIENT_ID/SECRET set and no CSV found. Either set those two "
                  "environment variables for full automation, or download a CSV from "
                  "developer.fuel-finder.service.gov.uk/access-latest-fuelprices and pass "
                  "--csv <path>, --csv-url <link>, or drop a file in your Downloads folder.")
            return
        csv_file = open(csv_path, encoding="utf-8-sig")
        source_label = os.path.basename(csv_path)
        stations, skipped_closed = load_stations(csv_file)

    print(f"Loaded {len(stations)} station(s) from {source_label} "
          f"({skipped_closed} permanently closed station(s) excluded).")

    html = generate_html(stations, source_label, maptiler_key)
    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"Wrote {OUTPUT_FILE}.")


if __name__ == "__main__":
    main()
