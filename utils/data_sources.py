"""
data_sources.py
================
All external-data plumbing for the Boba x Mochi dashboard lives here, so the
page files (pages/*.py) only ever call a small, well-named function and never
touch requests/JSON parsing directly.

Data sources used
------------------
1. Open-Meteo Geocoding API   -> turns a place name the user types ("Richmond, VA")
   into (lat, lon). Free, no API key. https://geocoding-api.open-meteo.com
2. Overpass API (OpenStreetMap) -> the actual boba/tea/dessert shop points near
   that lat/lon. Free, no API key, but IP rate-limited.
   https://overpass-api.de/api/interpreter
3. Open-Meteo Forecast API      -> current weather for that lat/lon, used to
   nudge the recommended mood (hot day -> "Refreshing", cold/rainy -> "Cozy").
   Free, no API key. https://api.open-meteo.com
4. Yelp Fusion API (OPTIONAL)   -> if YELP_API_KEY is set in .env, we enrich
   each shop with a real price level and rating. If no key is present, we
   generate a clearly-labeled deterministic "sample" price/rating so the
   Compare page still has numbers to chart -- this is placeholder data only
   and is flagged with is_demo_data=True on every row it touches.

Every network call is wrapped in try/except with a short timeout. If Overpass
or geocoding fails (rate limit, network hiccup, bad location text), we fall
back to the bundled CSV of sample shops in data/fallback_boba_shops.csv so the
dashboard always has something to show instead of erroring out.
"""

import os
import hashlib
import random
import time

import pandas as pd
import requests

GEOCODE_URL = "https://geocoding-api.open-meteo.com/v1/search"
WEATHER_URL = "https://api.open-meteo.com/v1/forecast"
OVERPASS_URL = "https://overpass-api.de/api/interpreter"
YELP_SEARCH_URL = "https://api.yelp.com/v3/businesses/search"

FALLBACK_CSV = os.path.join(os.path.dirname(__file__), "..", "data", "fallback_boba_shops.csv")

REQUEST_TIMEOUT = 10  # seconds -- fail fast rather than hang the callback


# ---------------------------------------------------------------------------
# Geocoding
# ---------------------------------------------------------------------------
def geocode_location(place_text):
    """
    Turn free-text like 'Williamsburg, VA' into (lat, lon, display_name).
    Returns (None, None, None) if it can't be resolved.
    """
    if not place_text or not place_text.strip():
        return None, None, None
    try:
        resp = requests.get(
            GEOCODE_URL,
            params={"name": place_text.strip(), "count": 1, "language": "en", "format": "json"},
            timeout=REQUEST_TIMEOUT,
        )
        resp.raise_for_status()
        results = resp.json().get("results")
        if not results:
            return None, None, None
        top = results[0]
        display = f"{top.get('name')}, {top.get('admin1', '')}".strip(", ")
        return top["latitude"], top["longitude"], display
    except (requests.RequestException, KeyError, ValueError):
        return None, None, None


# ---------------------------------------------------------------------------
# Weather + mood nudge
# ---------------------------------------------------------------------------
# Open-Meteo "weather code" groups, simplified for our mood nudge.
_RAINY_CODES = set(range(51, 68)) | set(range(80, 100))
_SNOWY_CODES = set(range(71, 78)) | {85, 86}


def get_weather(lat, lon):
    """
    Return a small dict: {temperature_f, weathercode, condition_label} or
    None if the call fails. Temperature is converted to Fahrenheit.
    """
    if lat is None or lon is None:
        return None
    try:
        resp = requests.get(
            WEATHER_URL,
            params={
                "latitude": lat,
                "longitude": lon,
                "current_weather": True,
                "temperature_unit": "fahrenheit",
            },
            timeout=REQUEST_TIMEOUT,
        )
        resp.raise_for_status()
        current = resp.json().get("current_weather", {})
        code = current.get("weathercode", 0)
        if code in _SNOWY_CODES:
            condition = "Snowy"
        elif code in _RAINY_CODES:
            condition = "Rainy"
        elif code == 0:
            condition = "Clear"
        else:
            condition = "Cloudy"
        return {
            "temperature_f": current.get("temperature"),
            "weathercode": code,
            "condition_label": condition,
        }
    except (requests.RequestException, KeyError, ValueError):
        return None


def mood_nudge_from_weather(weather):
    """
    Turn a weather dict into a one-line human suggestion plus a mood tag
    that matches the tags used on the shop data ('Refreshing', 'Cozy', 'Sweet').
    """
    if not weather or weather.get("temperature_f") is None:
        return "Weather unavailable right now -- pick any mood below.", None

    temp = weather["temperature_f"]
    condition = weather["condition_label"]

    if condition in ("Rainy", "Snowy"):
        return f"It's {condition.lower()} and {temp:.0f}°F -- a hot tea or warm mochi sounds right.", "Cozy"
    if temp >= 80:
        return f"It's {temp:.0f}°F and {condition.lower()} -- fruit tea or shaved ice weather.", "Refreshing"
    if temp <= 45:
        return f"It's a brisk {temp:.0f}°F -- something warm and cozy fits best.", "Cozy"
    return f"It's a mild {temp:.0f}°F and {condition.lower()} -- great day for any mood.", "Sweet"


# ---------------------------------------------------------------------------
# Overpass (OpenStreetMap) shop search
# ---------------------------------------------------------------------------
def _build_overpass_query(lat, lon, radius_miles):
    radius_m = int(max(0.5, radius_miles) * 1609.34)
    return f"""
    [out:json][timeout:25];
    (
      node["shop"="tea"](around:{radius_m},{lat},{lon});
      node["cuisine"="bubble_tea"](around:{radius_m},{lat},{lon});
      node["amenity"="cafe"]["cuisine"~"bubble_tea|tea",i](around:{radius_m},{lat},{lon});
      node["amenity"="cafe"]["name"~"boba|bubble tea|tea|mochi",i](around:{radius_m},{lat},{lon});
      node["shop"="confectionery"]["name"~"mochi|boba|bubble",i](around:{radius_m},{lat},{lon});
    );
    out center tags;
    """


def _derive_category(tags):
    name = (tags.get("name") or "").lower()
    if "mochi" in name or tags.get("shop") == "confectionery":
        return "Dessert"
    if "milk tea" in name or "boba" in name:
        return "Boba / Milk Tea"
    if tags.get("cuisine") == "bubble_tea":
        return "Boba / Milk Tea"
    return "Cafe / Tea"


def _derive_mood_tag(tags):
    """Simple keyword heuristic -- OSM has no 'mood' field, so we infer one."""
    name = (tags.get("name") or "").lower()
    if any(k in name for k in ("fruit", "iced", "slush", "fresh", "smoothie")):
        return "Refreshing"
    if any(k in name for k in ("mochi", "dessert", "cake", "sweet")):
        return "Sweet"
    return "Cozy"


def query_overpass_shops(lat, lon, radius_miles=5):
    """
    Query Overpass for boba/tea/dessert POIs near (lat, lon).
    Returns (dataframe, used_fallback: bool, error_message: str|None)
    """
    if lat is None or lon is None:
        df, _ = load_fallback_shops()
        return df, True, "No location provided -- showing sample shops."

    query = _build_overpass_query(lat, lon, radius_miles)
    try:
        resp = requests.post(OVERPASS_URL, data={"data": query}, timeout=25)
        resp.raise_for_status()
        elements = resp.json().get("elements", [])
    except (requests.RequestException, ValueError):
        df, _ = load_fallback_shops()
        return df, True, "Overpass API is unreachable or rate-limited -- showing sample shops instead."

    rows = []
    for el in elements:
        tags = el.get("tags", {}) or {}
        name = tags.get("name")
        if not name:
            continue  # skip unnamed nodes -- not useful for a user-facing list
        rows.append(
            {
                "shop_id": f"osm_{el.get('id')}",
                "name": name,
                "lat": el.get("lat"),
                "lon": el.get("lon"),
                "address": ", ".join(
                    filter(
                        None,
                        [tags.get("addr:housenumber", "") + " " + tags.get("addr:street", ""), tags.get("addr:city", "")],
                    )
                ).strip(", ").strip(),
                "category": _derive_category(tags),
                "mood_tag": _derive_mood_tag(tags),
                "phone": tags.get("phone", tags.get("contact:phone", "")),
                "website": tags.get("website", tags.get("contact:website", "")),
            }
        )

    if not rows:
        df, _ = load_fallback_shops()
        return df, True, "No shops found in that radius from OpenStreetMap -- showing sample shops instead."

    df = pd.DataFrame(rows).dropna(subset=["lat", "lon"])
    df = enrich_price_and_rating(df)
    return df, False, None


# ---------------------------------------------------------------------------
# Price / rating enrichment (Yelp if key present, else deterministic demo data)
# ---------------------------------------------------------------------------
def _demo_price_and_rating(name):
    """
    Deterministic 'sample' price + rating derived from a hash of the shop
    name, so the same shop always gets the same demo numbers across reruns.
    Clearly NOT real data -- used only when no Yelp API key is configured.
    """
    seed = int(hashlib.md5(name.encode()).hexdigest(), 16) % (2**32)
    rng = random.Random(seed)
    price_level = rng.choice(["$", "$$", "$$$"])
    rating = round(rng.uniform(3.5, 5.0), 1)
    avg_item_price = {"$": rng.uniform(3.5, 6), "$$": rng.uniform(6, 9), "$$$": rng.uniform(9, 13)}[price_level]
    return price_level, rating, round(avg_item_price, 2)


def enrich_price_and_rating(df):
    """
    Adds price_level, rating, avg_item_price, and is_demo_data columns.
    Uses Yelp Fusion API when YELP_API_KEY is set; otherwise falls back to
    deterministic demo numbers (is_demo_data=True) so the Compare page still
    has something real to plot.
    """
    yelp_key = os.getenv("YELP_API_KEY", "")
    use_yelp = bool(yelp_key) and yelp_key != "your_yelp_api_key_here"

    price_levels, ratings, avg_prices, demo_flags = [], [], [], []
    for _, row in df.iterrows():
        yelp_row = _yelp_lookup(row["name"], row["lat"], row["lon"], yelp_key) if use_yelp else None
        if yelp_row:
            price_levels.append(yelp_row["price_level"])
            ratings.append(yelp_row["rating"])
            avg_prices.append(yelp_row["avg_item_price"])
            demo_flags.append(False)
        else:
            p, r, a = _demo_price_and_rating(row["name"])
            price_levels.append(p)
            ratings.append(r)
            avg_prices.append(a)
            demo_flags.append(True)

    df = df.copy()
    df["price_level"] = price_levels
    df["rating"] = ratings
    df["avg_item_price"] = avg_prices
    df["is_demo_data"] = demo_flags
    return df


def _yelp_lookup(name, lat, lon, api_key):
    """Best-effort Yelp Fusion lookup by name + coordinates. Returns None on any failure."""
    try:
        resp = requests.get(
            YELP_SEARCH_URL,
            headers={"Authorization": f"Bearer {api_key}"},
            params={"term": name, "latitude": lat, "longitude": lon, "radius": 200, "limit": 1},
            timeout=REQUEST_TIMEOUT,
        )
        resp.raise_for_status()
        businesses = resp.json().get("businesses", [])
        if not businesses:
            return None
        biz = businesses[0]
        price_str = biz.get("price", "$$")
        avg_item_price = {"$": 5, "$$": 7.5, "$$$": 11, "$$$$": 15}.get(price_str, 7.5)
        return {"price_level": price_str, "rating": biz.get("rating", 4.0), "avg_item_price": avg_item_price}
    except (requests.RequestException, ValueError, KeyError):
        return None


# ---------------------------------------------------------------------------
# Fallback dataset (per the team's proposal Sticking Points section)
# ---------------------------------------------------------------------------
_fallback_cache = None


def load_fallback_shops():
    """
    Loads the bundled sample CSV (30 fictional-but-realistic shops across the
    DMV + Hampton Roads areas). Cached after first read.
    Returns (dataframe, error_message_or_None)
    """
    global _fallback_cache
    if _fallback_cache is not None:
        return _fallback_cache.copy(), None
    try:
        df = pd.read_csv(FALLBACK_CSV)
        df = enrich_price_and_rating(df)
        _fallback_cache = df
        return df.copy(), None
    except (FileNotFoundError, pd.errors.ParserError) as exc:
        return pd.DataFrame(
            columns=["shop_id", "name", "lat", "lon", "address", "category", "mood_tag", "phone", "website"]
        ), f"Could not load fallback data: {exc}"
