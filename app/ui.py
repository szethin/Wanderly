import streamlit as st
import requests
import datetime

st.set_page_config(page_title="Wanderly", page_icon="✈️", layout="wide")

# Inject custom CSS for a clean, light orange/minimalist aesthetic
st.markdown("""
    <style>

    /* Subtle orange accent for primary buttons and focus states */
    div.stButton > button:first-child {
        background-color: #FF9F43;
        color: white;
        border-radius: 6px;
        border: none;
    }

    div.stButton > button:first-child:hover {
        background-color: #E6892E;
    }

    /* Light orange background for the Agent Trace expanders */
    .streamlit-expanderHeader {
        background-color: #FFF5EB;
        border-radius: 4px;
    }

    </style>
""", unsafe_allow_html=True)


# FastAPI endpoint URL
API_URL = "http://localhost:8000/plan_trip"

st.title("✈️ Wanderly: Agentic AI Personal Travel Planner")

# --- Left Panel: Trip Configuration ---
with st.sidebar:
    st.header("Trip Configuration")

    # 1. Destination
    destination = st.text_input("Destination", placeholder="e.g., Kyoto, Japan")

    # 2. Start Date -- Calendar picker
    start_date = st.date_input("Start Date", min_value=datetime.date.today())

    # 3. Duration
    duration = st.slider("Duration (Days)", min_value=1, max_value=10, value=5)

    # 4. Budget
    budget = st.number_input("Budget (RM)", min_value=500.0, step=100.0, value=3000.0)

    # 5. Travel Style
    travel_style = st.multiselect(
        "Travel Style",
        options=["Adventure", "Nature", "Anime", "Shopping", "Food", "Culture", "Luxury", "Relaxation"],
        default=["Culture", "Food"]
    )

    # 6. Constraints
    constraints = st.multiselect(
        "Constraints",
        options=["Vegetarian", "Vegan", "Halal", "No hiking", "No early mornings", "Wheelchair friendly", "Kid friendly"],
        default=[]
    )

    # 7. Special Requests
    special_requests = st.text_area(
        "Special Requests", 
        placeholder="e.g., It's our honeymoon! Please make it romantic."
    )

    # Submit Button
    generate_btn = st.button("✨ Plan My Trip")


# --- Right Screen: Agent Trace & Itinerary ---
# Only trigger API call when the button is pressed
if generate_btn:
    if not destination:
        st.warning("Please enter a destination to proceed.")
    else:
        # st.status provides a beautiful spinner UI while waiting for the backend
        with st.status("Agent is planning your trip...", expanded=True) as status:

            # 1. Prepare JSON payload. Convert date object to string YYYY-MM-DD
            payload = {
                "destination": destination,
                "start_date": start_date.strftime("%Y-%m-%d"),
                "duration": duration,
                "budget": budget,
                "travel_style": travel_style,
                "constraints": constraints,
                "special_requests": special_requests
            }

            try:
                # 2. Make synchronous HTTP POST request to FastAPI
                st.write("📡 Sending data to Wanderly Agent Engine...")
                response = requests.post(API_URL, json=payload, timeout=4200)

                if response.status_code == 200:
                    data = response.json()
                    status.update(label="Planning Complete!", state="complete", expanded=False)

                    # --- Transparent Agent Trace  ---
                    st.subheader("Agent Trace")

                    with st.expander("🧠 Planner Node Reasoning", expanded=True):
                        # 1. Planner Reasoning
                        st.write(data.get("planner_reasoning"))

                        # 2. Planner's step-by-step subtasks
                        st.write("**📝 Subtasks Planned:**")
                        for i, step in enumerate(data.get("planner_plan", [])):
                            st.write(f"{i+1}. {step}")
                        st.write("---")

                        # 3. Tools Selected
                        st.write(f"🛠️ **Tools Selected:** `{data.get('required_tools')}`")

                        # 4. Map & Search Queries
                        if "maps" in data.get("required_tools", []):
                            st.write(f"📍 **Maps Query:** `{data.get('maps_query')}`")

                        if "tavily" in data.get("required_tools", []):
                            st.write(f"🔍 **Search Query:** `{data.get('search_query')}`")
                    
                else: 
                    status.update(label="Planning Failed", state="error")
                    st.error(f"Backend Error: {response.text}")
                    st.stop() # Force stop execution here if it fails

            except Exception as e:
                status.update(label="Connection Error", state="error")
                st.error(f"Failed to connect to backend: {e}")
                st.stop()

        # ==========================================
        # OUTSIDE THE st.status BLOCK
        # This ensures the final itinerary is ALWAYS fully visible
        # ==========================================
        if 'data' in locals() and response.status_code == 200:
            st.subheader("🗺️ Generated Itinerary")
            
            # FIX: Clean up the raw dict format if it exists, extracting just the pure markdown text
            raw_itinerary = data.get("itinerary", "")
            if isinstance(raw_itinerary, dict):
                # Safely extract 'text' or 'content' depending on how the LLM formatted it
                clean_itinerary = raw_itinerary.get("text", raw_itinerary.get("content", str(raw_itinerary)))
            else:
                clean_itinerary = str(raw_itinerary)
                
            st.markdown(clean_itinerary)

