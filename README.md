# Fuel Price Map

A self-contained HTML map of UK fuel prices, built from the UK government's
[Fuel Finder](https://www.gov.uk/government/collections/fuel-finder) open
data scheme.

- Colour-coded stations by price for whichever fuel grade you pick
  (Unleaded, Super Unleaded, Diesel, Premium Diesel, B10, HVO)
- Brand filter
- "Use my location" + a 5/10/20-mile radius filter, with a cheapest-first
  sidebar list tied to that radius (no point knowing about the cheapest
  station in the country if it's 200 miles away)
- Clustered markers so it stays fast with 8,000+ stations

## Setup

1. **Map tiles**: get a free [MapTiler](https://www.maptiler.com/) API key
   from [cloud.maptiler.com/account/keys](https://cloud.maptiler.com/account/keys/),
   then set it as an environment variable:
   ```
   setx MAPTILER_KEY "your-key-here"
   ```
2. **Fuel price data** - two options:
   - **API (recommended, fully automated)**: register once at the
     [Fuel Finder developer portal](https://www.developer.fuel-finder.service.gov.uk/access-latest-fuelprices)
     (free, behind a GOV.UK One Login - a one-time step) to get a
     `client_id`/`client_secret` pair, then set:
     ```
     setx FUEL_FINDER_CLIENT_ID "your-client-id"
     setx FUEL_FINDER_CLIENT_SECRET "your-client-secret"
     ```
     Once set, every run fetches live data with no further login or manual
     step - see `fuel_finder_api.py` for exactly which endpoints this uses
     (the API's own example docs show a domain that doesn't actually
     resolve, so these were found by hand via the portal's Swagger pages).
   - **CSV (manual fallback)**: download the CSV by hand from the same
     portal and drop it in your Downloads folder (auto-detected), or copy
     the pre-signed S3 URL shown on the download page and pass it with
     `--csv-url` - that link is only valid for ~12 hours and one specific
     publish, so it has to be a fresh one each time.

## Usage

```
python generate_fuel_map.py                    # uses the API if credentials are set,
                                                 # else falls back to newest CSV in Downloads
python generate_fuel_map.py --csv path\to.csv   # force a specific CSV
python generate_fuel_map.py --csv-url "https://...&X-Amz-Signature=..."
```

Writes `fuel_map.html` - open it in a browser. `refresh_and_open.ps1`
does the same and opens it automatically (handy as a desktop shortcut).

Map tiles are from [MapTiler](https://www.maptiler.com/), built on
[OpenStreetMap](https://www.openstreetmap.org/copyright) data.
