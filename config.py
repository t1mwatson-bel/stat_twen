# config.py

# 🔐 API Keys
API_SPORTS_KEY = "your_api_sports_key_here"     # For match data (football/soccer)
ODDS_API_KEY = "your_odds_api_key_here"         # For live betting odds
WEATHER_API_KEY = "your_weather_api_key_here"   # For live weather (OpenWeatherMap or WeatherAPI)

# 🏟️ Default Match Location (used for weather lookup)
DEFAULT_LOCATION = "Espoo"  # You can change this to any city

# 📡 API Endpoints (for reference)
MATCH_DATA_URL = "https://v3.football.api-sports.io/matches" 
ODDS_DATA_URL = "https://api.the-odds-api.com/v4/sports/soccer_finland_ylisairaus/odds" 
WEATHER_PROVIDER = "openweathermap"  # or "weatherapi"