"""
pages/compare.py
=================
Page 2 -- "Compare". Answers Q2 (compare shops by price / preference) using
whatever results the Search page put into shop-data-store.

Callbacks defined here:
  3a. populate_shop_dropdown -- shop-data-store changes -> dropdown options
  3b. update_comparison      -- dropdown selection -> bar chart + table
"""

import dash
import pandas as pd
import plotly.express as px
from dash import Input, Output, callback, dash_table, dcc, html

dash.register_page(__name__, path="/compare", name="Compare", order=1)

layout = html.Div(
    [
        html.Div(
            className="card-boba",
            children=[
                html.H2("Compare shops"),
                html.P("Pick two or more spots from your last search to compare price and rating."),
                dcc.Dropdown(id="compare-shop-dropdown", multi=True, placeholder="Search results will appear here..."),
            ],
        ),
        html.Div(
            className="card-boba",
            children=[
                html.H3("Average Item Price"),
                dcc.Graph(id="compare-bar-chart"),
            ],
        ),
        html.Div(
            className="card-boba",
            children=[
                html.H3("Details"),
                html.Div(id="compare-table-wrapper"),
            ],
        ),
    ]
)


# ---------------------------------------------------------------------------
# Callback 3a -- shop-data-store -> dropdown options
# ---------------------------------------------------------------------------
@callback(
    Output("compare-shop-dropdown", "options"),
    Output("compare-shop-dropdown", "value"),
    Input("shop-data-store", "data"),
)
def populate_shop_dropdown(shop_data):
    if not shop_data:
        return [], []
    df = pd.DataFrame(shop_data)
    options = [{"label": name, "value": name} for name in df["name"]]
    # Default to the first two shops so the page isn't empty on arrival.
    default_value = list(df["name"].head(2))
    return options, default_value


# ---------------------------------------------------------------------------
# Callback 3b -- selected shops -> comparison chart + table
# ---------------------------------------------------------------------------
@callback(
    Output("compare-bar-chart", "figure"),
    Output("compare-table-wrapper", "children"),
    Input("compare-shop-dropdown", "value"),
    Input("shop-data-store", "data"),
)
def update_comparison(selected_names, shop_data):
    if not shop_data or not selected_names:
        fig = px.bar(title="Select shops above to compare")
        fig.update_layout(paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)")
        return fig, html.P("No shops selected yet.")

    df = pd.DataFrame(shop_data)
    subset = df[df["name"].isin(selected_names)]
    if subset.empty:
        fig = px.bar(title="No matching shops")
        return fig, html.P("No matching shops.")

    fig = px.bar(
        subset.sort_values("avg_item_price"),
        x="name",
        y="avg_item_price",
        color="mood_tag",
        labels={"name": "Shop", "avg_item_price": "Avg. item price ($)", "mood_tag": "Mood"},
        title="Average item price by shop",
        color_discrete_map={"Refreshing": "#94ab74", "Cozy": "#c98a4b", "Sweet": "#f0c6d2"},
    )
    fig.update_layout(paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)", font_color="#3b2418")

    display_cols = ["name", "category", "mood_tag", "price_level", "rating", "avg_item_price", "is_demo_data"]
    table_df = subset[[c for c in display_cols if c in subset.columns]].rename(
        columns={
            "name": "Shop",
            "category": "Category",
            "mood_tag": "Mood",
            "price_level": "Price",
            "rating": "Rating",
            "avg_item_price": "Avg item $",
            "is_demo_data": "Sample data?",
        }
    )
    table = dash_table.DataTable(
        data=table_df.to_dict("records"),
        columns=[{"name": c, "id": c} for c in table_df.columns],
        style_cell={"fontFamily": "Nunito, sans-serif", "padding": "8px", "textAlign": "left"},
        style_header={"backgroundColor": "#f0c6d2", "fontWeight": "bold"},
        style_table={"borderRadius": "12px", "overflow": "hidden"},
    )
    return fig, table
