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
2. Yelp Fusion Business Search (PRIMARY when a real YELP_API_KEY is set) ->
   finds boba/tea/dessert shops directly, with real price/rating attached.
   Much higher, predictable rate limits (500 free calls/day) than Overpass's
   shared public pool, so this is tried first whenever a key is configured.
3. Overpass API (OpenStreetMap) -> used when no Yelp key is set, or Yelp's
   call fails/returns nothing. Free, no API key, but IP rate-limited and
   shared by everyone -- this is the path most likely to say
   "unreachable or rate-limited."  https://overpass-api.de/api/interpreter
4. Open-Meteo Forecast API      -> current weather for that lat/lon, used to
   nudge the recommended mood (hot day -> "Refreshing", cold/rainy -> "Cozy").
   Free, no API key. https://api.open-meteo.com
5. Bundled fallback CSV (data/fallback_boba_shops.csv) -> last resort if both
   Yelp and Overpass fail. Fictional placeholder shops around the DMV +
   Hampton Roads area, distance-filtered against the searched location, and
   always shown as sample data (never enriched via Yelp, since the shops
   themselves aren't real).

Every network call is wrapped in try/except with a short timeout, and
find_shops() below tries Yelp -> Overpass -> fallback CSV in that order so
the dashboard always has something to show instead of erroring out.
"""

import os
import hashlib
import random
import time
from functools import lru_cache

import pandas as pd
import requests

GEOCODE_URL = "https://geocoding-api.open-meteo.com/v1/search"
WEATHER_URL = "https://api.open-meteo.com/v1/forecast"
# Try the main Overpass instance, then two public mirrors, before giving up.
# The public Overpass server is IP rate-limited and occasionally flaky, so
# trying mirrors first meaningfully cuts down how often we ever need to fall
# back to the sample CSV.
OVERPASS_URLS = [
    "https://overpass-api.de/api/interpreter",
    "https://overpass.kumi.systems/api/interpreter",
    "https://lz4.overpass-api.de/api/interpreter",
]

# The bundled fallback CSV only contains shops around the DMV + Hampton
# Roads areas (see data/fallback_boba_shops.csv). If the user searches
# somewhere far from that region, showing all 30 of those rows is actively
# misleading -- they're not "near" the search at all. We only show fallback
# rows that are within this distance of the searched point.
FALLBACK_MAX_DISTANCE_MILES = 60


def _haversine_miles(lat1, lon1, lat2, lon2):
    """Great-circle distance between two lat/lon points, in miles."""
    from math import atan2, cos, radians, sin, sqrt

    r = 3958.8  # Earth radius in miles
    dlat, dlon = radians(lat2 - lat1), radians(lon2 - lon1)
    a = sin(dlat / 2) ** 2 + cos(radians(lat1)) * cos(radians(lat2)) * sin(dlon / 2) ** 2
    return 2 * r * atan2(sqrt(a), sqrt(1 - a))
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


def _query_overpass_raw(query):
    """
    POST the Overpass QL query to each known Overpass endpoint in turn,
    returning the first successful response's elements. Raises the last
    exception if every mirror fails.
    """
    last_exc = None
    for url in OVERPASS_URLS:
        try:
            resp = requests.post(url, data={"data": query}, timeout=25)
            resp.raise_for_status()
            return resp.json().get("elements", [])
        except (requests.RequestException, ValueError) as exc:
            last_exc = exc
            continue
    raise last_exc


def query_overpass_shops(lat, lon, radius_miles=5):
    """
    Query Overpass for boba/tea/dessert POIs near (lat, lon).
    Returns (dataframe, used_fallback: bool, error_message: str|None)
    """
    if lat is None or lon is None:
        df, _ = load_fallback_shops()
        return df, True, "No location provided -- showing sample shops from the DMV/Hampton Roads area."

    query = _build_overpass_query(lat, lon, radius_miles)
    try:
        elements = _query_overpass_raw(query)
    except (requests.RequestException, ValueError):
        return _fallback_near(lat, lon, radius_miles, reason="Overpass API is unreachable or rate-limited right now")

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
        return _fallback_near(lat, lon, radius_miles, reason="No shops found in that radius on OpenStreetMap")

    df = pd.DataFrame(rows).dropna(subset=["lat", "lon"])
    df = enrich_price_and_rating(df)
    return df, False, None


def _fallback_near(lat, lon, radius_miles, reason):
    """
    Shared fallback logic: only return sample-CSV shops that are actually
    close to the searched point, and say plainly when none are. Prevents
    showing 30 DMV shops for a search in, say, Denver.
    """
    all_fallback, load_err = load_fallback_shops()
    if load_err:
        return all_fallback, True, load_err

    all_fallback["distance_miles"] = all_fallback.apply(
        lambda r: _haversine_miles(lat, lon, r["lat"], r["lon"]), axis=1
    )
    search_radius = max(radius_miles or 5, FALLBACK_MAX_DISTANCE_MILES)
    nearby = all_fallback[all_fallback["distance_miles"] <= search_radius].drop(columns="distance_miles")

    if nearby.empty:
        empty_df = all_fallback.drop(columns="distance_miles").iloc[0:0]
        return (
            empty_df,
            True,
            f"{reason}, and our sample dataset only covers the DMV/Hampton Roads area, "
            f"which isn't near this location -- no results to show.",
        )
    return nearby, True, f"{reason} -- showing {len(nearby)} nearby sample shop(s) instead."


# ---------------------------------------------------------------------------
# Yelp Business Search (primary shop-discovery source when a key is present)
# ---------------------------------------------------------------------------
def _derive_category_from_yelp(categories, name):
    cats = " ".join(categories).lower()
    name_lower = (name or "").lower()
    if "mochi" in name_lower or "dessert" in cats:
        return "Dessert"
    if "bubble tea" in cats or "boba" in name_lower or "milk tea" in name_lower:
        return "Boba / Milk Tea"
    return "Cafe / Tea"


def search_yelp_businesses(lat, lon, radius_miles):
    """
    Search Yelp directly for boba/tea/dessert shops near (lat, lon) -- this
    is a full shop-discovery call, not just enrichment of existing rows.
    Returns a dataframe (already in our standard shop schema, with real
    price/rating and is_demo_data=False) or None if no key is configured,
    the call fails, or nothing came back.
    """
    key = os.getenv("YELP_API_KEY", "")
    if not key or key == "your_yelp_api_key_here":
        return None

    radius_m = min(int(max(0.5, radius_miles) * 1609.34), 40000)  # Yelp caps radius at 40,000m (~24.9 mi)
    try:
        resp = requests.get(
            YELP_SEARCH_URL,
            headers={"Authorization": f"Bearer {key}"},
            params={
                "latitude": lat,
                "longitude": lon,
                "radius": radius_m,
                "term": "boba bubble tea milk tea mochi",
                "limit": 50,
                "sort_by": "distance",
            },
            timeout=15,
        )
        resp.raise_for_status()
        businesses = resp.json().get("businesses", [])
    except (requests.RequestException, ValueError):
        return None

    rows = []
    for biz in businesses:
        name = biz.get("name")
        coords = biz.get("coordinates", {}) or {}
        biz_lat, biz_lon = coords.get("latitude"), coords.get("longitude")
        if not name or biz_lat is None or biz_lon is None:
            continue
        categories = [c.get("title", "") for c in biz.get("categories", [])]
        price_str = biz.get("price", "$$")
        rows.append(
            {
                "shop_id": f"yelp_{biz.get('id')}",
                "name": name,
                "lat": biz_lat,
                "lon": biz_lon,
                "address": ", ".join(biz.get("location", {}).get("display_address", [])),
                "category": _derive_category_from_yelp(categories, name),
                "mood_tag": _derive_mood_tag({"name": name}),
                "phone": biz.get("display_phone", ""),
                "website": biz.get("url", ""),
                "price_level": price_str,
                "rating": biz.get("rating"),
                "avg_item_price": {"$": 5, "$$": 7.5, "$$$": 11, "$$$$": 15}.get(price_str, 7.5),
                "is_demo_data": False,
            }
        )

    if not rows:
        return None
    return pd.DataFrame(rows)


# ---------------------------------------------------------------------------
# Orchestrator -- this is what pages/search.py actually calls
# ---------------------------------------------------------------------------
@lru_cache(maxsize=128)
def find_shops(lat_rounded, lon_rounded, radius_miles):
    """
    Main shop-discovery entry point. Tries, in order:
      1. Yelp Business Search (if a real key is configured) -- highest
         rate limit, so this is the preferred path once you have a key.
      2. Overpass API (OpenStreetMap), across three mirrors.
      3. Bundled fallback CSV, filtered to shops near (lat, lon).

    Cached by (rounded lat, rounded lon, radius) so re-searching the same
    spot within a session doesn't burn additional Overpass/Yelp quota --
    this directly helps with Overpass's rate limiting, since repeated
    identical searches (e.g. while testing) reuse the cached result instead
    of hitting the API again.

    Returns (dataframe, source: "yelp"|"overpass"|"fallback", error_message: str|None)
    """
    yelp_df = search_yelp_businesses(lat_rounded, lon_rounded, radius_miles)
    if yelp_df is not None and not yelp_df.empty:
        return yelp_df, "yelp", None

    df, used_fallback, error_message = query_overpass_shops(lat_rounded, lon_rounded, radius_miles)
    source = "fallback" if used_fallback else "overpass"
    return df, source, error_message


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


def enrich_price_and_rating(df, allow_yelp=True):
    """
    Adds price_level, rating, avg_item_price, and is_demo_data columns.
    Uses Yelp Fusion API when YELP_API_KEY is set AND allow_yelp is True;
    otherwise falls back to deterministic demo numbers (is_demo_data=True)
    so the Compare page still has something real to plot.

    allow_yelp=False is used for the bundled fallback CSV: those shop names
    are fictional placeholders, so looking them up on Yelp would either find
    nothing or -- worse -- fuzzy-match onto some unrelated real business
    near those coordinates. Forcing demo data for fallback rows keeps every
    fallback shop consistently labeled "sample data" instead of an
    unpredictable mix.
    """
    yelp_key = os.getenv("YELP_API_KEY", "")
    use_yelp = allow_yelp and bool(yelp_key) and yelp_key != "your_yelp_api_key_here"

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
        # allow_yelp=False: these are fictional placeholder shops, so they
        # always get consistent demo price/rating data rather than an
        # unpredictable real-or-fake mix from fuzzy Yelp name matching.
        df = enrich_price_and_rating(df, allow_yelp=False)
        _fallback_cache = df
        return df.copy(), None
    except (FileNotFoundError, pd.errors.ParserError) as exc:
        return pd.DataFrame(
            columns=["shop_id", "name", "lat", "lon", "address", "category", "mood_tag", "phone", "website"]
        ), f"Could not load fallback data: {exc}"
