# api_helpers.py

import requests

from config import API_SPORTS_KEY, ODDS_API_KEY, WEATHER_API_KEY, MATCH_DATA_URL, WEATHER_PROVIDER

# --- Match Data ---
def get_match_data(match_id):
    headers = {"x-rapidapi-key": API_SPORTS_KEY}
    params = {"fixture": match_id}
    try:
        response = requests.get(MATCH_DATA_URL, headers=headers, params=params)
        if response.status_code == 200 and response.json()['results'] > 0:
            return response.json()['response'][0]
        else:
            return None
    except Exception as e:
        print("Error fetching match data:", str(e))
        return None


# --- Live Odds ---
def get_live_odds(match_id):
    url = f"https://api.the-odds-api.com/v4/sports/soccer_finland_ylisairaus/odds/" 
    params = {
        "apiKey": ODDS_API_KEY,
        "regions": "eu",
        "markets": "h2h",
        "oddsFormat": "decimal"
    }
    try:
        response = requests.get(url, params=params)
        if response.status_code == 200:
            data = response.json()
            for game in data.get("data", []):
                if game['id'] == str(match_id):
                    return game['bookmakers'][0]['markets'][0]['outcomes']
        return []
    except Exception as e:
        print("Error fetching odds:", str(e))
        return []


# --- Live Weather ---
def get_match_weather(location="Espoo"):
    if WEATHER_PROVIDER == "openweathermap":
        base_url = "http://api.openweathermap.org/data/2.5/weather"
        params = {
            "q": location,
            "appid": WEATHER_API_KEY
        }
    elif WEATHER_PROVIDER == "weatherapi":
        base_url = "http://api.weatherapi.com/v1/current.json"
        params = {
            "key": WEATHER_API_KEY,
            "q": location
        }
    else:
        return {"error": "Invalid weather provider"}

    try:
        response = requests.get(base_url, params=params)
        if response.status_code == 200:
            data = response.json()
            if WEATHER_PROVIDER == "openweathermap":
                temp = round(data["main"]["temp"] - 273.15, 1)
                desc = data["weather"][0]["description"]
            else:  # weatherapi
                temp = data["current"]["temp_c"]
                desc = data["current"]["condition"][0]["text"]

            return {"temperature": temp, "description": desc}
        else:
            return {"error": "Failed to fetch weather"}
    except Exception as e:
        print("Weather error:", str(e))
        return {"error": "Weather API failed"}