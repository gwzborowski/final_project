# AI Usage
# Claude was prompted to develop functions when experiencing technical 
# difficulties with API calls. The functions were tested by us to 
# make sure that the data was being used correctly in our app. When there
# were issues, we used Claude to help troubleshoot and fix the problems.

"""
diagnose_apis.py
================
Run this directly (python diagnose_apis.py) to check, independent of the
Dash app, whether:
  1. Each Overpass mirror is reachable from your network right now.
  2. A real Overpass query for a known city (Richmond, VA) returns results.
  3. Your YELP_API_KEY in .env is valid and can authenticate.

This isolates network/API problems from the app's UI, so you know exactly
which piece is failing before digging further.
"""

import os

import requests
from dotenv import load_dotenv

load_dotenv()

OVERPASS_URLS = [
    "https://overpass-api.de/api/interpreter",
    "https://overpass.kumi.systems/api/interpreter",
    "https://lz4.overpass-api.de/api/interpreter",
]

# Richmond, VA -- known to have real boba/tea shops on OpenStreetMap, so an
# empty result here points at a network/rate-limit problem rather than "no
# shops exist in this area."
TEST_LAT, TEST_LON, TEST_RADIUS_MILES = 37.5407, -77.4360, 5


def check_overpass_reachability():
    print("\n=== 1. Overpass mirror reachability ===")
    for url in OVERPASS_URLS:
        try:
            # /api/status is a lightweight endpoint -- confirms the server
            # answers at all, separate from whether a full query succeeds.
            resp = requests.get(url.replace("/api/interpreter", "/api/status"), timeout=10)
            print(f"  {url}: HTTP {resp.status_code}")
        except requests.RequestException as exc:
            print(f"  {url}: FAILED -- {type(exc).__name__}: {exc}")


def check_overpass_query():
    print("\n=== 2. Real Overpass query near Richmond, VA ===")
    radius_m = int(TEST_RADIUS_MILES * 1609.34)
    query = f"""
    [out:json][timeout:25];
    (
      node["shop"="tea"](around:{radius_m},{TEST_LAT},{TEST_LON});
      node["cuisine"="bubble_tea"](around:{radius_m},{TEST_LAT},{TEST_LON});
      node["amenity"="cafe"]["cuisine"~"bubble_tea|tea",i](around:{radius_m},{TEST_LAT},{TEST_LON});
      node["amenity"="cafe"]["name"~"boba|bubble tea|tea|mochi",i](around:{radius_m},{TEST_LAT},{TEST_LON});
      node["shop"="confectionery"]["name"~"mochi|boba|bubble",i](around:{radius_m},{TEST_LAT},{TEST_LON});
    );
    out center tags;
    """
    for url in OVERPASS_URLS:
        try:
            resp = requests.post(url, data={"data": query}, timeout=25)
            resp.raise_for_status()
            elements = resp.json().get("elements", [])
            named = [e for e in elements if e.get("tags", {}).get("name")]
            print(f"  {url}: {len(elements)} raw element(s), {len(named)} named shop(s)")
            if named:
                for e in named[:5]:
                    print(f"      - {e['tags']['name']}")
                return  # success -- no need to try other mirrors
        except requests.RequestException as exc:
            print(f"  {url}: FAILED -- {type(exc).__name__}: {exc}")
        except ValueError:
            print(f"  {url}: FAILED -- response was not valid JSON")


def check_yelp_key():
    print("\n=== 3. Yelp API key ===")
    key = os.getenv("YELP_API_KEY", "")
    if not key or key == "your_yelp_api_key_here":
        print("  No real YELP_API_KEY found in .env -- still using the placeholder.")
        return
    try:
        resp = requests.get(
            "https://api.yelp.com/v3/businesses/search",
            headers={"Authorization": f"Bearer {key}"},
            params={"term": "boba tea", "latitude": TEST_LAT, "longitude": TEST_LON, "limit": 3},
            timeout=10,
        )
        if resp.status_code == 200:
            businesses = resp.json().get("businesses", [])
            print(f"  Key is valid -- Yelp returned {len(businesses)} business(es) near Richmond, VA.")
            for b in businesses:
                print(f"      - {b['name']} ({b.get('price', 'no price')}, {b.get('rating')} stars)")
        elif resp.status_code == 401:
            print("  Key was REJECTED (401 Unauthorized). Double-check you copied the API Key, not the Client ID.")
        else:
            print(f"  Unexpected response: HTTP {resp.status_code} -- {resp.text[:200]}")
    except requests.RequestException as exc:
        print(f"  FAILED to reach Yelp -- {type(exc).__name__}: {exc}")


if __name__ == "__main__":
    check_overpass_reachability()
    check_overpass_query()
    check_yelp_key()
    print("\nDone. The app now tries Yelp first (if step 3 above shows a valid key),")
    print("then Overpass, then sample data -- so a working Yelp key should mean you")
    print("rarely see 'rate-limited' anymore, even if Overpass itself is struggling.")
