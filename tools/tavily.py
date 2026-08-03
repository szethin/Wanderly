import json
from typing import Dict, Any
from langchain_tavily import TavilySearch

def search_travel_info(query: str) -> Dict[str, Any]:
    """
    Executes web search via TavilySearch to retrieve niche local travel insights.
    """

    try:
        search_tool = TavilySearch(max_results=3, search_depth="advanced")

        raw_results = search_tool.invoke({"query": query})

        # --- Defensive Parsing Mechanism ---
        # 1. Parse string to Python dict/list if returned as raw JSON
        if isinstance(raw_results, str):
            try:
                raw_results = json.loads(raw_results)
            except json.JSONDecodeError:
                raw_results = []

        # 2. Extract results list safely
        if isinstance(raw_results, dict) and "results" in raw_results:
            results_list = raw_results["results"]
        elif isinstance(raw_results, list):
            results_list = raw_results
        else:
            results_list = []

        # 3. Clean and format retrieved snippets
        clean_snippets = [
            {
                "title": item.get("title", "No Title"),
                "snippet": item.get("content", ""),
                "url": item.get("url", "")
            }
            for item in results_list if isinstance(item, dict)
        ]

        print(f"✅ [Tavily Tool] Found {len(clean_snippets)} web snippets.")

        return {
            "status": "SUCCESS", 
            "results": clean_snippets
        }

    except Exception as e:
        print(f"❌ [Tavily Tool] Search failed: {e}")

        return {
            "status": "ERROR", 
            "error": str(e), 
            "results": []
        }