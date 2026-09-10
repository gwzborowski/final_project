# AI Usage
# Claude was prompted to help style the layout of the home page, we supplied
# the assets and the general layout we wanted, and Claude helped us with the
# CSS and HTML to achieve the desired layout. The result was reviewed by us
# and edited to our liking.

"""
pages/home.py

Landing page for the "Mochi x Boba" dashboard. Recreates the flyer's layout:
donut + boba drink straddling a dashed divider, stamp-style title, and the
"feeling thirsty / feeling snacky" mood prompts (now clickable) over a soft
pink blob accent.
"""

import dash
from dash import html, dcc

dash.register_page(__name__, path="/", name="Home", order=0)

layout = html.Div(
    className="hero-boba",
    children=[
        html.Div(
            className="hero-card",
            children=[
                html.Img(src="/assets/mochi_donut.png", className="hero-image hero-image-donut"),
                html.Img(src="/assets/matcha_donut.png", className="hero-image hero-image-donut-2"),
                html.Img(src="/assets/boba_drink.png", className="hero-image hero-image-drink"),
                html.Div(className="hero-dash-line hero-dash-top"),
                html.Div(className="hero-blob"),
                html.Div(className="hero-blob-2"),
                html.H1(["MOCHI", html.Br(), "X", html.Br(), "BOBA"], className="hero-title"),
                html.Div(className="hero-dash-line hero-dash-bottom"),
                html.Div(
                    className="hero-moods",
                    children=[
                        dcc.Link("feeling thirsty...", href="/search", className="mood-link"),
                        dcc.Link("feeling snacky...", href="/search", className="mood-link"),
                    ],
                ),
            ],
        ),
    ],
)