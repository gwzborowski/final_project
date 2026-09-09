"""
pages/search.py
================
Page 1 -- "Search". Answers Q1 (find boba/mochi spots near me, within a
radius I choose) and feeds the weather-based mood nudge for Q3.

Callbacks defined here:
  1. update_search_results  -- location + radius + mood button click
                                -> geocode -> Overpass query -> map + list + stores
  2. update_weather_nudge   -- location-store changes -> Open-Meteo call -> mood nudge text
"""

import dash
import plotly.graph_objects as go
from dash import Input, Output, State, callback, dcc, html

from utils.data_sources import find_shops, geocode_location, get_weather, mood_nudge_from_weather

dash.register_page(__name__, path="/", name="Search", order=0)

MOOD_OPTIONS = [
    {"label": "Any mood", "value": "Any"},
    {"label": "🍧 Refreshing", "value": "Refreshing"},
    {"label": "☕ Cozy", "value": "Cozy"},
    {"label": "🍡 Sweet", "value": "Sweet"},
]

layout = html.Div(
    [
        html.Div(
            className="card-boba",
            children=[
                html.H2("Find a boba or mochi spot"),
                html.P("Type a city or address, set a radius, and optionally filter by mood."),
                html.Label("Location", className="control-label"),
                dcc.Input(
                    id="location-input",
                    type="text",
                    placeholder="e.g. Williamsburg, VA",
                    debounce=True,
                    style={"width": "100%", "padding": "10px"},
                ),
                html.Br(),
                html.Br(),
                html.Div(
                    style={"display": "flex", "gap": "24px", "flexWrap": "wrap"},
                    children=[
                        html.Div(
                            style={"flex": "1", "minWidth": "220px"},
                            children=[
                                html.Label("Search radius (miles)", className="control-label"),
                                dcc.Slider(id="radius-input", min=1, max=15, step=1, value=5, marks={1: "1", 5: "5", 10: "10", 15: "15"}),
                            ],
                        ),
                        html.Div(
                            style={"flex": "1", "minWidth": "220px"},
                            children=[
                                html.Label("Mood", className="control-label"),
                                dcc.Dropdown(id="mood-dropdown", options=MOOD_OPTIONS, value="Any", clearable=False),
                            ],
                        ),
                    ],
                ),
                html.Br(),
                html.Button("Search", id="search-button", n_clicks=0, className="btn-boba"),
                html.Div(id="search-status", style={"marginTop": "10px", "fontStyle": "italic"}),
            ],
        ),
        html.Div(
            id="weather-nudge-card",
            className="card-boba",
            children=[html.H3("Weather mood check"), html.P("Search a location to see today's mood nudge.", id="weather-nudge-text")],
        ),
        html.Div(
            className="card-boba",
            children=[
                html.H3("Map"),
                dcc.Loading(dcc.Graph(id="shop-map", style={"height": "480px"})),
            ],
        ),
        html.Div(
            className="card-boba",
            children=[
                html.H3("Results"),
                html.Div(id="results-list"),
            ],
        ),
    ]
)


# Plotly renamed/replaced the Mapbox-token-based trace (go.Scattermapbox /
# layout.mapbox) with a token-free MapLibre trace (go.Scattermap /
# layout.map) starting in plotly 5.24. Newer plotly releases have dropped
# Scattermapbox entirely, while older pinned installs may not yet have
# Scattermap. This small shim picks whichever the installed version supports
# so the app works across plotly versions without you having to think about it.
if hasattr(go, "Scattermap"):
    _MAP_TRACE = go.Scattermap
    _MAP_LAYOUT_KEY = "map"
else:  # pragma: no cover - only hit on plotly < 5.24
    _MAP_TRACE = go.Scattermapbox
    _MAP_LAYOUT_KEY = "mapbox"


# Default view when nothing has been searched yet (roughly centered on the
# continental US so the map isn't blank/zoomed into the ocean).
_DEFAULT_CENTER = dict(lat=39.5, lon=-98.35)
_DEFAULT_ZOOM = 3


def _empty_map(center=None, zoom=None):
    fig = go.Figure(_MAP_TRACE())
    fig.update_layout(
        **{_MAP_LAYOUT_KEY: dict(style="carto-positron", center=center or _DEFAULT_CENTER, zoom=zoom or _DEFAULT_ZOOM)},
        margin=dict(l=0, r=0, t=0, b=0),
    )
    return fig


_DEFAULT_ICON = {"emoji": "📍", "color": "#3b2418"}
CATEGORY_ICONS = {
    "Boba / Milk Tea": {"emoji": "🧋", "color": "#c98a4b"},
    "Dessert": {"emoji": "🍡", "color": "#e3aec2"},
    "Coffee": {"emoji": "☕", "color": "#6b4a3a"},
    "Cafe / Tea": {"emoji": "🍵", "color": "#94ab74"},
}


def _shops_to_map(df, center_lat, center_lon):
    """
    Always centers on the searched location (center_lat/center_lon), never on
    the average of whatever shops came back -- if the shops shown are sample
    data from a different region, averaging their coordinates would center
    the map somewhere unrelated to what the user actually searched.

    Each shop category (Boba / Milk Tea, Dessert, Coffee, Cafe / Tea) is
    plotted as its own trace with a distinct emoji icon rendered at each
    shop's coordinates, so the map visually distinguishes what a place
    specializes in without needing a paid Mapbox account for custom icons.
    """
    traces = []
    if not df.empty:
        for category, group in df.groupby("category"):
            icon = CATEGORY_ICONS.get(category, _DEFAULT_ICON)
            hovertexts = [
                f"{row['name']}<br>{row['category']} · {row['mood_tag']}"
                f"<br>{row.get('price_level', 'N/A')} · ⭐ {row.get('rating', 'N/A')}"
                for _, row in group.iterrows()
            ]
            traces.append(
                _MAP_TRACE(
                    lat=group["lat"],
                    lon=group["lon"],
                    mode="markers+text",
                    marker=dict(size=28, color=icon["color"]),
                    text=[icon["emoji"]] * len(group),
                    textfont=dict(size=15),
                    textposition="middle center",
                    hovertext=hovertexts,
                    hoverinfo="text",
                    name=category,
                )
            )
    # Marker for the searched location itself, so it's always visible even
    # when zero (or only far-away sample) shops are returned.
    traces.append(
        _MAP_TRACE(
            lat=[center_lat],
            lon=[center_lon],
            mode="markers+text",
            marker=dict(size=20, color="#3b2418"),
            text=["📍"],
            textfont=dict(size=13),
            textposition="middle center",
            hovertext=["You searched here"],
            hoverinfo="text",
            name="Search location",
        )
    )
    fig = go.Figure(traces)
    fig.update_layout(
        **{_MAP_LAYOUT_KEY: dict(style="carto-positron", center=dict(lat=center_lat, lon=center_lon), zoom=11)},
        margin=dict(l=0, r=0, t=0, b=0),
        showlegend=True,
        legend=dict(orientation="h", yanchor="bottom", y=1.01, xanchor="left", x=0),
    )
    return fig


def _shops_to_cards(df):
    if df.empty:
        return html.P("No shops matched -- try widening the radius or clearing the mood filter.")
    cards = []
    for _, row in df.iterrows():
        demo_badge = html.Span("sample data", className="demo-tag") if row.get("is_demo_data") else None
        cards.append(
            html.Div(
                className="shop-card",
                children=[
                    html.Span(row["name"], className="shop-name"),
                    demo_badge,
                    html.P(f"{row['category']} · mood: {row['mood_tag']} · {row.get('price_level', 'N/A')} · ⭐ {row.get('rating', 'N/A')}"),
                    html.P(row["address"] or "Address unavailable", style={"fontSize": "13px", "color": "#6b5245"}),
                ],
            )
        )
    return cards


# ---------------------------------------------------------------------------
# Callback 1 -- Location + mood input -> Overpass query -> shop results
# ---------------------------------------------------------------------------
@callback(
    Output("shop-data-store", "data"),
    Output("location-store", "data"),
    Output("shop-map", "figure"),
    Output("results-list", "children"),
    Output("search-status", "children"),
    Input("search-button", "n_clicks"),
    State("location-input", "value"),
    State("radius-input", "value"),
    State("mood-dropdown", "value"),
    prevent_initial_call=False,
)
def update_search_results(n_clicks, location_text, radius_miles, mood):
    if not n_clicks:
        # Initial page load, before the user has searched anything.
        return None, None, _empty_map(), html.P("Enter a location above and click Search to get started."), ""

    if not location_text or not location_text.strip():
        return dash.no_update, dash.no_update, dash.no_update, dash.no_update, "Please enter a location first."

    lat, lon, display_name = geocode_location(location_text)
    if lat is None:
        return (
            dash.no_update,
            dash.no_update,
            dash.no_update,
            dash.no_update,
            f"Couldn't find '{location_text}'. Try a city and state, e.g. 'Norfolk, VA'.",
        )

    # Round coordinates before the lookup so find_shops()'s cache actually
    # hits on repeat searches of "the same place" (e.g. re-clicking Search),
    # instead of missing the cache over tiny floating-point differences.
    df, source, error_message = find_shops(round(lat, 3), round(lon, 3), radius_miles or 5)
    used_fallback = source == "fallback"

    if mood and mood != "Any":
        filtered = df[df["mood_tag"] == mood]
        if not filtered.empty:
            df = filtered

    if df.empty:
        status = f"No shops found near {display_name}."
    else:
        source_label = {"yelp": "via Yelp", "overpass": "via OpenStreetMap"}.get(source, "")
        status = f"Showing {len(df)} spot(s) near {display_name} ({source_label})." if source_label else f"Showing {len(df)} spot(s) near {display_name}."
    if used_fallback and error_message:
        status += f" ({error_message})"

    location_data = {"lat": lat, "lon": lon, "display_name": display_name}
    # Map always centers on the searched point (see _shops_to_map docstring),
    # regardless of whether real Overpass results or sample fallback shops
    # are being shown, and even when there are zero shops to plot.
    fig = _shops_to_map(df, lat, lon)

    return df.to_dict("records"), location_data, fig, _shops_to_cards(df), status


# ---------------------------------------------------------------------------
# Callback 2 -- lat/lon -> live weather call -> mood nudge
# ---------------------------------------------------------------------------
@callback(
    Output("weather-nudge-text", "children"),
    Input("location-store", "data"),
)
def update_weather_nudge(location_data):
    if not location_data:
        return "Search a location to see today's mood nudge."
    weather = get_weather(location_data["lat"], location_data["lon"])
    message, _mood_tag = mood_nudge_from_weather(weather)
    return message
