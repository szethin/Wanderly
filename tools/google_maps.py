import os
import requests
from typing import Dict, Any

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
        # Using Google Maps Text Search Endpoint (Places API)
        endpoint = "https://maps.googleapis.com/maps/api/place/textsearch/json"
        params = {
            "query": f"top {query_type} in {destination}",
            "key": GOOGLE_MAPS_API_KEY
        }

        response = requests.get(endpoint, params=params, timeout=30)

        # Success
        if response.status_code == 200: 
            data = response.json()
            results = data.get("results", [])[:5]   # Limit to top 5 places to optimize context window

            # Extract only essential details (Name, Rating, Address)
            places = [
                {
                    "name": item.get("name"),
                    "rating": item.get("rating"),
                    "address": item.get("formatted_address")
                }
                for item in results
            ]

            print(f"✅ [Google Maps Tool] Retrieved {len(places)} places for {destination}.")

            return {
                "status": "SUCCESS",
                "places": places
            }

        # Error
        else:
            print(f"⚠️ [Google Maps Tool] API Error HTTP {response.status_code}")

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



def get_coordinates(location_name: str) -> Dict[str, Any]:
    """
    Converts a human-readable location into latitude and longitude coordinates.
    """
    if not GOOGLE_MAPS_API_KEY:
        return {
            "status": "FALLBACK", 
            "lat": 0.0, 
            "lng": 0.0
        }

    try:
        endpoint = "https://maps.googleapis.com/maps/api/geocode/json"
        params = {
            "address": location_name, 
            "key": GOOGLE_MAPS_API_KEY
        }
        
        response = requests.get(endpoint, params=params, timeout=30)
        
        if response.status_code == 200:
            data = response.json()
            results = data.get("results", [])
            if results:
                location = results[0].get("geometry", {}).get("location", {})
                print(f"✅ [Google Maps] Geocoded {location_name}.")
                return {
                    "status": "SUCCESS", 
                    "lat": location.get("lat"), 
                    "lng": location.get("lng")
                }
        
        return {
            "status": "ERROR", 
            "lat": None, 
            "lng": None
        }
    
    except Exception as e:
        print(f"❌ [Google Maps] Geocode Exception: {e}")
        return {
            "status": "ERROR", 
            "error": str(e)
        }



def get_distance_matrix(origins: str, destinations: str) -> Dict[str, Any]:
    """
    Calculates travel time and distance between origins and destinations.
    """
    if not GOOGLE_MAPS_API_KEY:
        return {
            "status": "FALLBACK", 
            "distance": "N/A", 
            "duration": "N/A"
        }

    try:
        endpoint = "https://maps.googleapis.com/maps/api/distancematrix/json"
        params = {
            "origins": origins,
            "destinations": destinations,
            "key": GOOGLE_MAPS_API_KEY,
            "mode": "transit" # Default to public transport for travel planning
        }
        
        response = requests.get(endpoint, params=params, timeout=30)
        
        if response.status_code == 200:
            data = response.json()
            rows = data.get("rows", [])
            if rows:
                elements = rows[0].get("elements", [])
                if elements and elements[0].get("status") == "OK":
                    distance = elements[0].get("distance", {}).get("text")
                    duration = elements[0].get("duration", {}).get("text")
                    print(f"✅ [Google Maps] Travel time {origins} to {destinations}: {duration}.")
                    return {
                        "status": "SUCCESS", 
                        "distance": distance, 
                        "duration": duration
                    }
                    
        return {
            "status": "ERROR", 
            "distance": None, 
            "duration": None
        }
    
    except Exception as e:
        print(f"❌ [Google Maps] Distance Matrix Exception: {e}")
        return {
            "status": "ERROR", 
            "error": str(e)
        }