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
2. Yelp Fusion API (used FIRST if a key is configured) -> real shop discovery
   with real price/rating already included in the same response. This is
   the preferred source when available, since Overpass's public servers are
   frequently rate-limited or reject unheadered requests.
3. Overpass API (OpenStreetMap) -> fallback shop discovery when Yelp isn't
   configured or returns nothing. Free, no API key, but IP rate-limited.
   https://overpass-api.de/api/interpreter
4. Open-Meteo Forecast API      -> current weather for that lat/lon, used to
   nudge the recommended mood (hot day -> "Refreshing", cold/rainy -> "Cozy").
   Free, no API key. https://api.open-meteo.com

Order of operations in find_shops(): try Yelp first (if a real key is
configured) -> if that returns nothing, try Overpass -> if that also fails
or returns nothing, fall back to the bundled sample CSV so the dashboard
always has something to show instead of erroring out.

Every network call is wrapped in try/except with a short timeout.
"""

import os
import hashlib
import random

import pandas as pd
import requests

GEOCODE_URL = "https://geocoding-api.open-meteo.com/v1/search"
WEATHER_URL = "https://api.open-meteo.com/v1/forecast"
OVERPASS_URL = "https://overpass-api.de/api/interpreter"
YELP_SEARCH_URL = "https://api.yelp.com/v3/businesses/search"

# Overpass's public server rejects requests with no identifying header.
OVERPASS_HEADERS = {
    "User-Agent": "BobaXMochiApp/1.0 (class project, William & Mary)",
    "Accept": "application/json",
}

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
_RAINY_CODES = set(range(51, 68)) | set(range(80, 100))
_SNOWY_CODES = set(range(71, 78)) | {85, 86}


def get_weather(lat, lon):
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
# Category / mood heuristics (shared by both Overpass and Yelp rows)
# ---------------------------------------------------------------------------
def _derive_category(name, cuisine="", shop_type="", yelp_categories=None):
    name = (name or "").lower()
    yelp_categories = yelp_categories or []

    if "mochi" in name or shop_type == "confectionery":
        return "Dessert"
    if any(c in yelp_categories for c in ("desserts", "bakeries", "icecream")):
        return "Dessert"
    if "milk tea" in name or "boba" in name or cuisine == "bubble_tea":
        return "Boba / Milk Tea"
    if "bubbletea" in yelp_categories:
        return "Boba / Milk Tea"
    if "coffee" in name or cuisine == "coffee_shop" or shop_type == "coffee":
        return "Coffee"
    if any(c in yelp_categories for c in ("coffee", "coffeeroasteries")):
        return "Coffee"
    return "Cafe / Tea"


def _derive_mood_tag(name):
    name = (name or "").lower()
    if any(k in name for k in ("fruit", "iced", "slush", "fresh", "smoothie")):
        return "Refreshing"
    if any(k in name for k in ("mochi", "dessert", "cake", "sweet")):
        return "Sweet"
    return "Cozy"


_PRICE_TO_AVG = {"$": 5, "$$": 7.5, "$$$": 11, "$$$$": 15}


# ---------------------------------------------------------------------------
# Yelp Fusion -- real shop discovery (tried FIRST when a key is configured)
# ---------------------------------------------------------------------------
def _yelp_key():
    key = os.getenv("YELP_API_KEY", "")
    return key if key and key != "your_yelp_api_key_here" else ""


def _search_yelp_shops(lat, lon, radius_miles):
    """
    Real shop discovery via Yelp (not just enrichment) -- searches for
    boba/mochi/coffee/tea spots near (lat, lon) and returns a DataFrame
    already containing real price/rating, or an empty DataFrame if the
    key is missing, the request fails, or nothing is found.
    """
    api_key = _yelp_key()
    if not api_key or lat is None or lon is None:
        return pd.DataFrame()

    radius_m = min(int(max(0.5, radius_miles) * 1609.34), 40000)  # Yelp caps at 40km
    try:
        resp = requests.get(
            YELP_SEARCH_URL,
            headers={"Authorization": f"Bearer {api_key}"},
            params={
                "term": "boba tea mochi coffee",
                "latitude": lat,
                "longitude": lon,
                "radius": radius_m,
                "limit": 50,
                "sort_by": "distance",
            },
            timeout=REQUEST_TIMEOUT,
        )
        resp.raise_for_status()
        businesses = resp.json().get("businesses", [])
    except (requests.RequestException, ValueError, KeyError):
        return pd.DataFrame()

    if not businesses:
        return pd.DataFrame()

    rows = []
    for biz in businesses:
        name = biz.get("name", "")
        yelp_cats = [c.get("alias", "") for c in biz.get("categories", [])]
        price_str = biz.get("price", "$$")
        coords = biz.get("coordinates", {})
        loc = biz.get("location", {})
        rows.append(
            {
                "shop_id": f"yelp_{biz.get('id')}",
                "name": name,
                "lat": coords.get("latitude"),
                "lon": coords.get("longitude"),
                "address": ", ".join(filter(None, loc.get("display_address", []))),
                "category": _derive_category(name, yelp_categories=yelp_cats),
                "mood_tag": _derive_mood_tag(name),
                "phone": biz.get("display_phone", ""),
                "website": biz.get("url", ""),
                "price_level": price_str,
                "rating": biz.get("rating", 4.0),
                "avg_item_price": _PRICE_TO_AVG.get(price_str, 7.5),
                "is_demo_data": False,
            }
        )

    return pd.DataFrame(rows).dropna(subset=["lat", "lon"])


# ---------------------------------------------------------------------------
# Overpass (OpenStreetMap) shop search -- fallback shop discovery
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


def _search_overpass_shops(lat, lon, radius_miles):
    """Real shop discovery via Overpass. Returns an empty DataFrame on any failure."""
    if lat is None or lon is None:
        return pd.DataFrame()

    query = _build_overpass_query(lat, lon, radius_miles)
    try:
        resp = requests.post(OVERPASS_URL, data={"data": query}, headers=OVERPASS_HEADERS, timeout=25)
        resp.raise_for_status()
        elements = resp.json().get("elements", [])
    except (requests.RequestException, ValueError):
        return pd.DataFrame()

    rows = []
    for el in elements:
        tags = el.get("tags", {}) or {}
        name = tags.get("name")
        if not name:
            continue
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
                "category": _derive_category(name, cuisine=tags.get("cuisine", ""), shop_type=tags.get("shop", "")),
                "mood_tag": _derive_mood_tag(name),
                "phone": tags.get("phone", tags.get("contact:phone", "")),
                "website": tags.get("website", tags.get("contact:website", "")),
            }
        )

    if not rows:
        return pd.DataFrame()

    df = pd.DataFrame(rows).dropna(subset=["lat", "lon"])
    return _enrich_price_and_rating(df)  # Overpass rows have no price/rating yet


# ---------------------------------------------------------------------------
# Price / rating enrichment for rows that didn't come from Yelp directly
# (i.e. Overpass rows, and the fallback CSV)
# ---------------------------------------------------------------------------
def _demo_price_and_rating(name):
    seed = int(hashlib.md5(name.encode()).hexdigest(), 16) % (2**32)
    rng = random.Random(seed)
    price_level = rng.choice(["$", "$$", "$$$"])
    rating = round(rng.uniform(3.5, 5.0), 1)
    avg_item_price = {"$": rng.uniform(3.5, 6), "$$": rng.uniform(6, 9), "$$$": rng.uniform(9, 13)}[price_level]
    return price_level, rating, round(avg_item_price, 2)


def _yelp_lookup_single(name, lat, lon, api_key):
    """Best-effort single-shop Yelp lookup, used only to enrich Overpass/CSV rows."""
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
        return {
            "price_level": price_str,
            "rating": biz.get("rating", 4.0),
            "avg_item_price": _PRICE_TO_AVG.get(price_str, 7.5),
        }
    except (requests.RequestException, ValueError, KeyError):
        return None


def _enrich_price_and_rating(df):
    api_key = _yelp_key()
    price_levels, ratings, avg_prices, demo_flags = [], [], [], []
    for _, row in df.iterrows():
        yelp_row = _yelp_lookup_single(row["name"], row["lat"], row["lon"], api_key) if api_key else None
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


# ---------------------------------------------------------------------------
# Fallback dataset (last resort)
# ---------------------------------------------------------------------------
_fallback_cache = None


def load_fallback_shops():
    global _fallback_cache
    if _fallback_cache is not None:
        return _fallback_cache.copy(), None
    try:
        df = pd.read_csv(FALLBACK_CSV)
        df = _enrich_price_and_rating(df)
        _fallback_cache = df
        return df.copy(), None
    except (FileNotFoundError, pd.errors.ParserError) as exc:
        return pd.DataFrame(
            columns=["shop_id", "name", "lat", "lon", "address", "category", "mood_tag", "phone", "website"]
        ), f"Could not load fallback data: {exc}"


# ---------------------------------------------------------------------------
# Public entry point -- Yelp first, then Overpass, then sample data
# ---------------------------------------------------------------------------
def find_shops(lat, lon, radius_miles=5):
    """
    Returns (dataframe, source, error_message) where source is one of
    "yelp", "overpass", or "fallback" -- matching what pages/search.py expects.
    """
    if lat is None or lon is None:
        df, _ = load_fallback_shops()
        return df, "fallback", "No location provided -- showing sample shops."

    df = _search_yelp_shops(lat, lon, radius_miles)
    if not df.empty:
        return df, "yelp", None

    df = _search_overpass_shops(lat, lon, radius_miles)
    if not df.empty:
        return df, "overpass", None

    df, _ = load_fallback_shops()
    return df, "fallback", "No live results from Yelp or OpenStreetMap -- showing sample shops instead."


# Backward-compatible alias -- older code may still import this name.
query_overpass_shops = find_shops
enrich_price_and_rating = _enrich_price_and_rating
