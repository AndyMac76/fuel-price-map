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
2. **Fuel price data**: the CSV comes from the
   [Fuel Finder developer portal](https://www.developer.fuel-finder.service.gov.uk/access-latest-fuelprices),
   gated behind a free GOV.UK One Login. Either:
   - Download the CSV by hand and drop it in your Downloads folder (the
     script auto-finds the newest `UpdatedFuelPrice-*.csv` there), or
   - Copy the pre-signed S3 URL shown on the download page and pass it
     with `--csv-url` - fetched directly, no file needed. That link is
     only valid for ~12 hours and one specific publish, so it has to be a
     fresh one each time, not a saved one.

## Usage

```
python generate_fuel_map.py                    # auto-finds newest CSV in Downloads
python generate_fuel_map.py --csv path\to.csv   # or point at one directly
python generate_fuel_map.py --csv-url "https://...&X-Amz-Signature=..."
```

Writes `fuel_map.html` - open it in a browser. `refresh_and_open.ps1`
does the same and opens it automatically (handy as a desktop shortcut).

Map tiles are from [MapTiler](https://www.maptiler.com/), built on
[OpenStreetMap](https://www.openstreetmap.org/copyright) data.
