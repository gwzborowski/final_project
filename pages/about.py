"""
pages/about.py
==============
Page 3 -- "About / Mascot". Project blurb plus the "Surprise Me" mascot,
which answers the "or additionally Surprise Me to generate a recommendation"
part of Q2 from the team's proposal.

Callback defined here:
  4. surprise_me -- button click + shop-data-store -> mascot message + highlighted shop
"""

import random

import dash
import pandas as pd
from dash import Input, Output, State, callback, html

dash.register_page(__name__, path="/about", name="About", order=2)

MASCOT_LINES = [
    "Feeling thirsty? {shop} is calling your name!",
    "Feeling snacky? {shop} has just the thing.",
    "The boba spirits have chosen... {shop}!",
    "Today's pick: {shop}. Trust the mochi.",
    "Your mood says {mood} -- {shop} matches perfectly.",
]

layout = html.Div(
    [
        html.Div(
            className="card-boba",
            children=[
                html.H2("About Mochi x Boba"),
                html.P(
                    "Mochi x Boba helps you find Asian dessert and drink spots that match your "
                    "mood and today's weather, across the globe! Search a location on the Search " 
                    "page, then come back here and hit Surprise Me if you "
                    "can't decide."
                ),
                html.P(
                    "Built for Competing in the Age of AI -- " 
                    "Team 3: Alex Bailey, Evie Trinh, Chase LaRose, & "
                    "Gavin Zborowski.",
                    style={"fontSize": "13px", "color": "#6b5245"},
            ),
            ],
        ),
        html.Div(
            className="card-boba",
            style={"textAlign": "center"},
            children=[
                html.H2("🧋 🍡"),
                html.P("feeling thirsty... feeling snacky...", style={"fontStyle": "italic"}),
                html.Button("Surprise Me!", id="surprise-me-button", n_clicks=0, className="btn-boba btn-surprise"),
                html.Div(id="mascot-message", className="mascot-message"),
            ],
        ),
    ]
)


# ---------------------------------------------------------------------------
# Callback 4 -- Surprise Me button -> mascot message + shop highlight
# ---------------------------------------------------------------------------
@callback(
    Output("mascot-message", "children"),
    Input("surprise-me-button", "n_clicks"),
    State("shop-data-store", "data"),
)
def surprise_me(n_clicks, shop_data):
    if not n_clicks:
        return ""
    if not shop_data:
        return "Search a location on the Search page first, then come back for a surprise!"

    df = pd.DataFrame(shop_data)
    pick = df.sample(1).iloc[0]
    line = random.choice(MASCOT_LINES)
    return line.format(shop=pick["name"], mood=pick["mood_tag"].lower())
