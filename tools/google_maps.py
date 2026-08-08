import os
import requests
# Import the resilient session builder
from tools.http_client import get_retry_session
from typing import Dict, Any
from dotenv import load_dotenv

load_dotenv()

# Read API Key from environment variables loaded via python-dotenv
GOOGLE_MAPS_API_KEY = os.getenv("GOOGLE_MAPS_API_KEY", "")

def search_google_maps(destination: str, query_type: str = "attractions") -> Dict[str, Any]:
    """
    Queries Google Places API to fetch locations, geocodes, and structural details.
    """

    # If API Key is missing, return fallback data
    if not GOOGLE_MAPS_API_KEY:
        print("⚠️ [Google Maps Tool] Missing API Key. Returning fallback data.")
        return {
            "status": "FALLBACK",
            "message": "Google Maps API key not configured.",
            "places": [f"Popular {query_type} in {destination} (Fallback Data)"]
        }

    try:
        # Google Places API (New) Endpoint
        endpoint = "https://places.googleapis.com/v1/places:searchText"

        # New API uses POST and strictly requires FieldMask in headers
        headers = {
            "Content-Type": "application/json",
            "X-Goog-Api-Key": GOOGLE_MAPS_API_KEY,
            "X-Goog-FieldMask": "places.displayName,places.rating,places.formattedAddress" 
        }

        payload = {
            "textQuery": f"top {query_type} in {destination}",
            "languageCode": "en",
            "maxResultCount": 5 # Limit results natively
        }

        # Instantiate the resilient HTTP session
        session = get_retry_session()

        # Replaced standard 'requests.post' with 'session.post' to inherit automatic retry behaviors
        response = session.post(endpoint, json=payload, headers=headers, timeout=30)

        # Success (HTTP Level)
        if response.status_code == 200: 
            data = response.json()

            # The new API returns a 'places' array directly, not 'results'
            results = data.get("places", [])
            
            # Extract details using the new JSON structure
            places = [
                {
                    "name": item.get("displayName", {}).get("text", "Unknown"),
                    "rating": item.get("rating", "N/A"),
                    "address": item.get("formattedAddress", "Unknown")
                }
                for item in results
            ]

            print(f"✅ [Google Maps Tool] Retrieved {len(places)} places for {destination}.")

            return {
                "status": "SUCCESS",
                "places": places
            }

        # Error (HTTP Level)
        else:
            # The new API returns detailed error messages in the JSON body on failure
            error_data = response.json()
            error_msg = error_data.get("error", {}).get("message", "Unknown Error")
            print(f"🚨 [Google Maps Tool] API Error {response.status_code}: {error_msg}")

            return {
                "status": "ERROR", 
                "places": []
            }

    except Exception as e:
        print(f"❌ [Google Maps Tool] Exception occurred: {e}")

        # Graceful fallback: Return empty list inside dict instead of throwing exception
        return {
            "status": "ERROR",
            "error": str(e),
            "places": []
        }