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

# --- Session State Initialization ---
# Initialize a list to hold chat history dictionaries (role, content, trace) safely across reruns
if "messages" not in st.session_state:
    st.session_state.messages = []

# Initialize thread tracking to map this frontend session to the backend MemorySaver
if "thread_id" not in st.session_state:
    st.session_state.thread_id = None

# Initialize a tracker to record the sidebar configuration from the last successful execution
if "last_config" not in st.session_state:
    st.session_state.last_config = {}

# Helper function
def render_agent_trace(data: dict):
    """
    Helper function to render Agentic Trace (Planner & Reflection) inside chat messages.
    """
    # --- 1. Planner Node Trace ---
    with st.expander("🧠 Agent Reasoning", expanded=False):  # Set expanded=False by default to keep chat history clean and scannable
        # 1.1. Planner Reasoning
        st.write("**🧠 Planner Node Reasoning**")
        st.write(data.get("planner_reasoning"))

        # 1.2. Planner's step-by-step subtasks
        st.write("**📝 Subtasks Planned:**")
        for i, step in enumerate(data.get("planner_plan", [])):
            st.write(f"{i+1}. {step}")

        # 1.3. Tools Selected
        st.write(f"🛠️ **Tools Selected:** `{data.get('planner_initial_tools')}`")

        # 1.4. Map & Search Queries
        if "maps" in data.get("planner_initial_tools", []):
            st.write(f"📍 **Maps Query:** `{data.get('planner_initial_maps_query')}`")

        if "tavily" in data.get("planner_initial_tools", []):
            st.write(f"🔍 **Search Query:** `{data.get('planner_initial_search_query')}`")
            
        if "weather" in data.get("planner_initial_tools", []):
            st.write(f"🌤️ **Weather Query:** `{data.get('planner_initial_weather_query')}`")


    # --- 2. Reflection Node Trace (Conditonal & Dynamic) ---
    reflection_logs = data.get("reflection_logs", [])
    
    if reflection_logs:
        st.warning("⚠️ **Agent triggered reflection to self-correct errors.**")
        
        st.write(f"**❌ Global Past Failed Queries:** `{data.get('past_queries', [])}`")

        # Dynamically iterate and render every single reflection loop event
        for log in reflection_logs:
            with st.expander(f"🧐 Reflection Trace (Loop {log.get('loop')})", expanded=False):
                st.write(f"**Critique:** {log.get('critique')}")
                
                # Only render updated execution plan if the agent suggested new tools (skips system fallbacks)
                if log.get("tools"):
                    st.write("---")
                    st.write("**✅ Updated Execution Plan:**")
                    st.write(f"🛠️ **New Tools Selected:** `{log.get('tools')}`")

                    if "maps" in log.get("tools", []):
                        st.write(f"📍 **Optimized Maps Query:** `{log.get('maps_query')}`")
                    if "tavily" in log.get("tools", []):
                        st.write(f"🔍 **Optimized Search Query:** `{log.get('search_query')}`")
                    if "weather" in log.get("tools", []):
                        st.write(f"🌤️ **Optimized Weather Query:** `{log.get('weather_query')}`")


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


# --- Action: Initial Generation Request ---
if generate_btn:
    if not destination:
        st.warning("Please enter a destination to proceed.")
    else:
        # Reset memory state to start a completely fresh trip planning session
        st.session_state.messages = []
        st.session_state.thread_id = None

        # Construct a natural language prompt summarizing the user's form inputs (for frontend display)
        user_prompt = f"Plan a {duration}-day trip to {destination} starting {start_date}. Budget: RM {budget}. Style: {', '.join(travel_style)}."
        if constraints: user_prompt += f" Constraints: {', '.join(constraints)}."
        if special_requests: user_prompt += f" Special requests: {special_requests}"

        # Append user message to frontend history
        st.session_state.messages.append({
            "role": "user",
            "content": user_prompt
        })

        # Snapshot the current sidebar configuration for future delta detection
        st.session_state.last_config = {
            "destination": destination,
            "start_date": start_date.strftime("%Y-%m-%d"),
            "duration": duration,
            "budget": budget,
            "travel_style": travel_style,
            "constraints": constraints,
            "special_requests": special_requests
        }
    
        # Execute blocking API call with a spinner UX
        with st.spinner("Agent is analyzing constraints and drafting your itinerary..."):

            # 1. Prepare JSON payload
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
                response = requests.post(API_URL, json=payload, timeout=4200)

                if response.status_code == 200:
                    data = response.json()

                    # Store backend-generated thread id into frontend session state to link future follow-ups
                    st.session_state.thread_id = data.get("thread_id") # from backend api return {}

                    # Safely extract itinerary into clean markdown string
                    raw_itinerary = data.get("itinerary", "")
                    if isinstance(raw_itinerary, dict):
                        # Safely extract 'text' or 'content' depending on how the LLM formatted it
                        clean_itinerary = raw_itinerary.get("text", raw_itinerary.get("content", str(raw_itinerary)))
                    else:
                        clean_itinerary = str(raw_itinerary)

                    # Store assistant response & technical trace payload in memory
                    st.session_state.messages.append({
                        "role": "assistant",
                        "content": clean_itinerary,
                        "trace": data
                    })

                    # Force Streamlit to rerun the script top-down to render the newly populated chat history
                    st.rerun()

                else: 
                    st.error(f"Backend Error: {response.text}")

            except Exception as e:
                st.error(f"Failed to connect to backend: {e}")
                # Remove the hanging user message from memory if the backend fails completely
                st.session_state.messages.pop()



# --- Right Screen: Conversational Chat UI Rendering ---
# Dynamically loop through session state & render historical messages identically across reruns
for msg in st.session_state.messages:

    # st.chat_message creates the native ChatGPT-style avatar and bubble container
    with st.chat_message(msg["role"]):
        st.markdown(msg["content"])

        #Inject the trace expanders strictly inside the assistant's message bubble if trace data exists
        if msg["role"] == "assistant" and "trace" in msg:
            render_agent_trace(msg["trace"])  # msg["trace"] == data == response.json()



# --- Action: Iterative Refinement Request (Follow-up) ---
# Conditional rendering: Only show the chat input if an active session exists
if st.session_state.thread_id:

    # st.chat_input: Native Streamlit widget that pins a text input bar to the bottom of the screen
    # The walrus operator (:=) assigns the input to user_feedback AND checks if it's not empty
    if user_feedback := st.chat_input("Refine your itinerary (e.g., 'Make it cheaper', 'Add a museum')..."):

        # ==========================================
        # DELTA DETECTION ENGINE (FULL TRACKING)
        # Check if the user modified ANY crucial sidebar inputs before submitting the chat
        # ==========================================
        changed_settings = []
        if destination != st.session_state.last_config.get("destination"):
            changed_settings.append(f"Destination: {destination}")
        if start_date.strftime("%Y-%m-%d") != st.session_state.last_config.get("start_date"):
            changed_settings.append(f"Date: {start_date.strftime('%Y-%m-%d')}")
        if duration != st.session_state.last_config.get("duration"):
            changed_settings.append(f"Duration: {duration} days")
        if budget != st.session_state.last_config.get("budget"):
            changed_settings.append(f"Budget: RM {budget}")
            
        # FIX: Track arrays and strings for holistic memory synchronization
        if travel_style != st.session_state.last_config.get("travel_style"):
            changed_settings.append(f"Style: {', '.join(travel_style)}")
        if constraints != st.session_state.last_config.get("constraints"):
            changed_settings.append(f"Constraints: {', '.join(constraints) if constraints else 'None'}")
        if special_requests != st.session_state.last_config.get("special_requests"):
            changed_settings.append(f"Requests: {special_requests}")
            
        system_note = ""
        if changed_settings:
            # Construct a markdown-formatted system note appending the exact changes
            system_note = f"\n\n*(System Note: Sidebar updated -> {', '.join(changed_settings)})*"
            
        # Seamlessly augment the user's prompt with the system note
        augmented_feedback = user_feedback + system_note

        # Snapshot the newly updated FULL configuration for the next potential chat turn
        st.session_state.last_config = {
            "destination": destination,
            "start_date": start_date.strftime("%Y-%m-%d"),
            "duration": duration,
            "budget": budget,
            "travel_style": travel_style,         # ADDED
            "constraints": constraints,           # ADDED
            "special_requests": special_requests  # ADDED
        }

        # 1. Append augmented request to frontend session memory
        st.session_state.messages.append({
            "role": "user",
            "content": augmented_feedback
        })

        # 2. Render instantly for responsive UX
        with st.chat_message("user"):
            st.markdown(augmented_feedback)

        # 3. Execute block API call to LangGraph backend
        with st.spinner("Agent is refining your itinerary..."):

            # Construct payload
            # Note: We must include sidebar variables (destination, etc.) to satisfy Pydantic's strict schema validation, 
            # even though our FastAPI router will prioritize routing based on user_feedback.
            payload = {
                "destination": destination,
                "start_date": start_date.strftime("%Y-%m-%d"),
                "duration": duration,
                "budget": budget,
                "travel_style": travel_style,
                "constraints": constraints,
                "special_requests": special_requests,
                
                # INJECT NEW DATA: Pass the session key and the specific edit instruction
                "thread_id": st.session_state.thread_id,
                "user_feedback": user_feedback
            }

            try:
                # POST request
                response = requests.post(API_URL, json=payload, timeout=4200)

                if response.status_code == 200:
                    data = response.json()

                    # Safely extract itinerary into clean markdown string
                    raw_itinerary = data.get("itinerary", "")
                    if isinstance(raw_itinerary, dict):
                        # Safely extract 'text' or 'content' depending on how the LLM formatted it
                        clean_itinerary = raw_itinerary.get("text", raw_itinerary.get("content", str(raw_itinerary)))
                    else:
                        clean_itinerary = str(raw_itinerary)

                    # Append updated agent itinerary and trace to frontend memory
                    st.session_state.messages.append({
                        "role": "assistant",
                        "content": clean_itinerary,
                        "trace": data
                    })

                    # Force script rerun to render the newly populated array via the top-down loop
                    st.rerun()

                else:
                    st.error(f"Backend Error: {response.text}")
                    
            except Exception as e:
                st.error(f"Failed to connect to backend: {e}")
                # Remove the hanging user message from memory if the backend fails completely
                st.session_state.messages.pop()

