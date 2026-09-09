# Boba x Mochi Dashboard

A Dash app that helps you find Asian dessert and drink spots — boba, milk
tea, mochi — near a location you choose, filtered by mood and nudged by
today's real weather. Built for Team 3's Dash project lab.

## Project structure

```
boba_mochi_dashboard/
├── app.py                     # App shell: nav bar, shared stores, page routing
├── pages/
│   ├── search.py               # Page 1 — location/radius/mood search, map, results
│   ├── compare.py              # Page 2 — compare selected shops by price/rating
│   └── about.py                 # Page 3 — project blurb + "Surprise Me" mascot
├── utils/
│   └── data_sources.py         # All external API calls + fallback-CSV logic
├── data/
│   └── fallback_boba_shops.csv # 30 sample shops used when live APIs are unreachable
├── assets/
│   └── style.css               # Theme (cream / pink / espresso, matches project flyer)
├── .env.example                # Documents required environment variables
├── .env                        # Your real values (git-ignored; placeholder key for now)
├── .gitignore
└── requirements.txt
```

## Setup

1. **Create a virtual environment and install dependencies**
   ```bash
   python -m venv venv
   source venv/bin/activate        # Windows: venv\Scripts\activate
   pip install -r requirements.txt
   ```

2. **Configure environment variables**
   `.env` is already included with placeholder values so the app runs
   out of the box. When you have a real Yelp Fusion API key, open `.env` and
   replace the placeholder:
   ```
   YELP_API_KEY=your_actual_key_here
   ```
   Without a real key, the Compare page still works — it shows clearly
   labeled **"sample data"** price/rating numbers generated deterministically
   from each shop's name, instead of leaving the chart empty.

3. **Run the app**
   ```bash
   python app.py
   ```
   Then open **http://127.0.0.1:8050** in your browser.

## How it works

- **Search page**: type a location, pick a radius and optional mood, hit
  Search. This geocodes the text with the Open-Meteo Geocoding API, queries
  the Overpass API (OpenStreetMap) for tea/boba/dessert points within that
  radius, and plots them on a map plus a results list. If Overpass is
  unreachable or rate-limited, or returns nothing, the app automatically
  falls back to `data/fallback_boba_shops.csv` (30 sample shops across the
  DMV and Hampton Roads) so the dashboard never shows a blank page.
- **Weather mood nudge**: once a location is searched, a second callback
  calls Open-Meteo's forecast API for that location and suggests a mood
  ("Refreshing" on a hot day, "Cozy" when it's cold or rainy).
- **Compare page**: pick two or more shops from your last search and see a
  bar chart + table comparing average item price, price tier, and rating.
- **About / Mascot page**: hit "Surprise Me" for a random pick from your
  current search results.

## Data dictionary

| Field            | Type    | Source                        | Notes                                                                 |
|-------------------|---------|--------------------------------|------------------------------------------------------------------------|
| `shop_id`         | string  | Overpass node id / fallback CSV | Unique identifier per shop                                            |
| `name`            | string  | Overpass `name` tag / CSV      | Shop display name                                                     |
| `lat`, `lon`      | float   | Overpass / CSV                 | Coordinates used for the map and radius search                       |
| `address`         | string  | Overpass `addr:*` tags / CSV   | May be blank if OSM has no address tags for that node                |
| `category`        | string  | Derived from OSM tags          | "Boba / Milk Tea", "Dessert", or "Cafe / Tea"                        |
| `mood_tag`        | string  | Derived heuristic / CSV        | "Refreshing", "Cozy", or "Sweet" — used for mood filtering            |
| `price_level`     | string  | Yelp (if key set) or generated | `$` / `$$` / `$$$`                                                    |
| `rating`          | float   | Yelp (if key set) or generated | 1–5 scale                                                              |
| `avg_item_price`  | float   | Yelp (if key set) or generated | Used as the y-axis of the Compare bar chart                          |
| `is_demo_data`    | bool    | Set by `enrich_price_and_rating`| `True` when no Yelp key is configured — flags price/rating as sample |
| `phone`, `website`| string  | Overpass tags                  | Optional, often blank from OSM                                       |

## Diagnosing "why am I only seeing sample data?" / Overpass rate limits

As of this version, `find_shops()` in `utils/data_sources.py` tries sources
in this order, so a working Yelp key should make Overpass's rate limiting a
non-issue in practice:
1. **Yelp Business Search** (if a real `YELP_API_KEY` is set) — real shops,
   real price/rating, and a much higher, predictable rate limit (500 free
   calls/day) than Overpass's shared public pool.
2. **Overpass API** (OpenStreetMap), tried across three mirrors — used only
   when no Yelp key is configured, or the Yelp call fails/returns nothing.
3. **Bundled fallback CSV** — last resort, distance-filtered to the searched
   location, always shown as sample data since those shops are fictional.

Repeat searches of the same spot within a session are cached in memory
(`@lru_cache` on `find_shops`, keyed by rounded lat/lon + radius), so
re-clicking Search on the same location doesn't burn additional API quota.

If you're still seeing "unreachable or rate-limited" even with a Yelp key
set, run the standalone diagnostic script to check each piece independently
of the UI:
```bash
python diagnose_apis.py
```
It reports whether each Overpass mirror is reachable, whether a real
Overpass query near Richmond, VA returns named shops, and whether your Yelp
key authenticates — useful for telling a network/rate-limit problem apart
from an app bug.



- OpenStreetMap coverage of small boba shops is inconsistent — some areas
  are well-mapped, others aren't. If a search returns too few results, the
  app falls back to the bundled sample dataset automatically.
- Without a Yelp API key, price and rating numbers are **synthetic sample
  data** (deterministic per shop name, clearly labeled in the UI), not real
  business data. Add a key in `.env` to replace these with real Yelp values.
- Overpass's public instance enforces IP-based rate limiting; heavy repeated
  searches may briefly trigger the fallback dataset.

## Attribution

- Map/POI data: © OpenStreetMap contributors, via the Overpass API (ODbL).
- Weather + geocoding: Open-Meteo.com (free, no API key required).
- Business price/rating enrichment (optional): Yelp Fusion API.
