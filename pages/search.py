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

from utils.data_sources import geocode_location, get_weather, mood_nudge_from_weather, query_overpass_shops

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


def _empty_map():
    fig = go.Figure(_MAP_TRACE())
    fig.update_layout(
        **{_MAP_LAYOUT_KEY: dict(style="carto-positron", center=dict(lat=37.5, lon=-77.0), zoom=6)},
        margin=dict(l=0, r=0, t=0, b=0),
    )
    return fig


def _shops_to_map(df):
    fig = go.Figure(
        _MAP_TRACE(
            lat=df["lat"],
            lon=df["lon"],
            mode="markers",
            marker=dict(size=14, color="#c98a4b"),
            text=df["name"] + "<br>" + df["category"] + " · " + df["mood_tag"],
            hoverinfo="text",
        )
    )
    fig.update_layout(
        **{
            _MAP_LAYOUT_KEY: dict(
                style="carto-positron",
                center=dict(lat=df["lat"].mean(), lon=df["lon"].mean()),
                zoom=10,
            )
        },
        margin=dict(l=0, r=0, t=0, b=0),
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

    df, used_fallback, error_message = query_overpass_shops(lat, lon, radius_miles or 5)

    if mood and mood != "Any":
        filtered = df[df["mood_tag"] == mood]
        if not filtered.empty:
            df = filtered

    status = f"Showing {len(df)} spot(s) near {display_name}."
    if used_fallback and error_message:
        status += f" ({error_message})"

    location_data = {"lat": lat, "lon": lon, "display_name": display_name}
    fig = _shops_to_map(df) if not df.empty else _empty_map()

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
