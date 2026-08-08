import os
import requests
from typing import Dict, Any
from dotenv import load_dotenv

# Import the resilient session builder
from tools.http_client import get_retry_session

load_dotenv()

OPENWEATHER_API_KEY = os.getenv("OPENWEATHER_API_KEY", "")

def get_weather_forecast(destination: str) -> Dict[str, Any]:
    """
    Fetches the 5-day weather forecast for the specified destination using OpenWeather API.
    CRITICAL LIMITATION: This tool ONLY provides data for the next 5 days. 
    If the trip date is beyond 5 days from today, do NOT use this tool. Use web search for historical climate instead.
    """

    if not OPENWEATHER_API_KEY:
        print("⚠️ [Weather Tool] Missing API Key. Returning fallback weather.")
        return {
            "status": "FALLBACK",
            "forecast": "Sunny / Mild rain expected (Fallback weather info) "
        }

    try:
        # OpenWeather Weather Forecast Data Endpoint
        endpoint = "https://api.openweathermap.org/data/2.5/forecast"
        params = {
            "q": destination,
            "appid": OPENWEATHER_API_KEY,
            "units": "metric"   # Standardize units to Celsius
        }

        # Instantiate the resilient HTTP session
        session = get_retry_session()

        # Replaced standard 'requests.get' with 'session.get' to enforce deterministic backoff
        response = session.get(endpoint, params=params, timeout=30)

        # Success
        if response.status_code == 200:
            data = response.json()

            # The API returns 40 items (5 days * 8 intervals of 3 hours). 
            forecast_list = data.get("list", [])
            
            # Filter the list: Keep ONLY the forecast for 12:00:00 PM each day.
            # This reduces 40 noisy data points down to just 5 concise daily summaries.
            simplified_forecast = [
                {
                    "datetime": item.get("dt_txt"),
                    "weather": item.get("weather", [{}])[0].get("description", "Unknown"),
                    "temp_celsius": item.get("main", {}).get("temp", "N/A")
                }
                for item in forecast_list if "12:00:00" in item.get("dt_txt", "")
            ]
            
            print(f"✅ [Weather Tool] Fetched 5-day forecast for {destination}.")
            return {
                "status": "SUCCESS",
                "forecast": simplified_forecast
            }

        else:
            print(f"⚠️ [Weather Tool] HTTP {response.status_code}")

            return {
                "status": "ERROR", 
                "forecast": []
            }

    except Exception as e:
        print(f"❌ [Weather Tool] Exception: {e}")
        return {
            "status": "ERROR", 
            "error": str(e), 
            "forecast": []
        }
