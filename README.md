# Boba x Mochi Dashboard

## Project Overview

### The Problem

Finding a good boba or dessert spot can be difficult when there are so many options. It can also be hard to decide where to go based on location, price, ratings, or even the weather.

Our dashboard brings these factors together in one place to make finding a boba or dessert shop easier.

### Our Audience

This dashboard is designed for people who enjoy boba, milk tea, mochi, and other Asian desserts. It can be especially useful for students, friends looking for somewhere to go, or anyone who wants a quick recommendation based on where they are.

### What the Dashboard Does

Users can:

- Search for a location
- Choose how far they are willing to travel
- Filter results based on their mood
- View nearby boba, tea, and dessert shops on a map
- See information such as ratings, price level, and average item price
- Compare multiple shops
- Get a recommendation based on the current weather
- Use the "Surprise Me" feature for a random shop recommendation

The goal is to make the process of choosing a boba or dessert spot **simple, visual, and fun**.

---

## How to Run

### Run Locally

1. Download or clone the project from GitHub.

2. Open the project folder in VS Code.

3. Create a virtual environment:

```bash
python -m venv venv
```

4. Activate the environment.

**Windows:**

```bash
venv\Scripts\activate
```

5. Install the required packages:

```bash
pip install -r requirements.txt
```

6. Add your API key to a `.env` file if you are using the Yelp API:

```text
YELP_API_KEY=your_actual_key_here
```

7. Start the dashboard:

```bash
python app.py
```

8. Open the address shown in the terminal, usually:

```text
http://127.0.0.1:8050
```

### Deploying the App

The dashboard can also be hosted online using Render.

For deployment, the project needs its required Python packages and environment variables. API keys should be added to Render's **Environment Variables** rather than uploaded to GitHub.

The Render service runs the Dash application using Gunicorn.

Render live at: https://comp-ageai-group-3-final-project-mochi-x.onrender.com/

---

## Data Sources

The dashboard uses several sources to provide information about locations, businesses, and weather.

### OpenStreetMap / Overpass API

Used to find nearby tea, boba, cafe, and dessert locations.

The information can include:

- Shop name
- Location
- Address
- Phone number
- Website
- Business category

OpenStreetMap data can vary depending on how much information has been added for a particular area.

**Important:** Overpass used as second option for finding nearby restaurants, due to technical difficulties, Yelp was used as the primary API for this task.

### Open-Meteo

Used for:

- Weather information
- Location geocoding
- Weather-based recommendations

Open-Meteo does not require an API key.

### Yelp Fusion API

Used to provide additional business information when an API key is available, including:

- Ratings
- Price level
- Average item price

### Sample Data

The dashboard also includes a small sample dataset that can be used when live business information is unavailable. This helps prevent the dashboard from appearing empty when an API cannot return results.

---

## Data Dictionary

| Field            | Description                                                       | Source                      |
| ---------------- | ----------------------------------------------------------------- | --------------------------- |
| `shop_id`        | Unique ID for each shop                                           | OpenStreetMap / Sample Data |
| `name`           | Name of the shop                                                  | OpenStreetMap / Sample Data |
| `lat`            | Latitude of the shop                                              | OpenStreetMap / Sample Data |
| `lon`            | Longitude of the shop                                             | OpenStreetMap / Sample Data |
| `address`        | Address of the shop                                               | OpenStreetMap / Sample Data |
| `category`       | Type of business, such as boba, dessert, or cafe                  | OpenStreetMap               |
| `mood_tag`       | Mood associated with the shop, such as Refreshing, Cozy, or Sweet | Dashboard                   |
| `price_level`    | General price level ($, $$, $$$)                                  | Yelp / Sample Data          |
| `rating`         | Business rating from 1–5                                          | Yelp / Sample Data          |
| `avg_item_price` | Estimated average price used for comparison                       | Yelp / Sample Data          |
| `phone`          | Business phone number, when available                             | OpenStreetMap               |
| `website`        | Business website, when available                                  | OpenStreetMap               |
| `is_demo_data`   | Indicates whether sample data is being used                       | Dashboard                   |

---

## Project Pages

### Search

Search for shops by location, distance, and mood. Results are displayed on a map and in a list.

### Compare

Compare selected shops based on factors such as price and rating.

"$" → average item price ≤ $5
"$$" → average item price > $5 and ≤ $7.50
"$$$" → average item price > $7.50 and ≤ $11
"$$$$" → average item price > $11 and ≤ $15

### About

Learn more about the project and use the "Surprise Me" feature for a random recommendation.

---

## Data Limitations

The information shown in the dashboard depends on the data available from the APIs.

Some smaller businesses may not appear in OpenStreetMap, and some businesses may have missing information such as rating, or price.

When live business information is unavailable, the dashboard may use sample data instead. Sample price and rating information should not be treated as actual business information.

## Attribution

- Map and business location data: OpenStreetMap contributors, through the Overpass API
- Weather and geocoding: Open-Meteo
- Business ratings and price information: Yelp Fusion API
