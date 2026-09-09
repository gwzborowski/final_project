"""
app.py
======
Entry point / app shell for the "Boba x Mochi" dashboard.

This file does three jobs and nothing else:
  1. Creates the Dash app with multi-page routing turned on (use_pages=True).
     Each file in pages/ registers itself as a page with dash.register_page().
  2. Defines the top navigation bar shown on every page.
  3. Defines two app-wide dcc.Store components (shop-data-store,
     location-store) that live OUTSIDE dash.page_container. Because they sit
     in the root layout, they persist as the user clicks between Search /
     Compare / About, which is how results from the Search page reach the
     Compare and About pages without re-querying anything.

Run with:  python app.py
Then open: http://127.0.0.1:8050
"""

import os

import dash
import dash_bootstrap_components as dbc
from dash import Dash, dcc, html
from dotenv import load_dotenv

load_dotenv()  # reads .env into os.environ (see .env.example for the variables used)

app = Dash(
    __name__,
    use_pages=True,
    pages_folder="pages",
    external_stylesheets=[dbc.themes.FLATLY],  # base layout/grid only -- assets/style.css overrides the look
    suppress_callback_exceptions=True,
    title="Boba x Mochi",
)
server = app.server  # exposed for gunicorn / wsgi deployment

NAVBAR = html.Div(
    className="navbar-boba",
    children=[
        html.H1("🧋 Boba x Mochi", className="brand-title"),
        html.Div(
            className="nav-links",
            children=[dcc.Link(page["name"], href=page["relative_path"]) for page in dash.page_registry.values()],
        ),
    ],
)

app.layout = html.Div(
    [
        NAVBAR,
        # ---- App-wide state, shared across every page ----
        dcc.Store(id="shop-data-store", storage_type="session"),  # list[dict] of current search results
        dcc.Store(id="location-store", storage_type="session"),  # {"lat", "lon", "display_name"}
        html.Div(dash.page_container, className="page-shell"),
    ]
)

if __name__ == "__main__":
    debug_mode = os.getenv("DASH_DEBUG", "true").lower() == "true"
    app.run(debug=debug_mode, host="127.0.0.1", port=int(os.getenv("PORT", 8050)))
