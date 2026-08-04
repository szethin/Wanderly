# visualize.py
from agent.graph import wanderly_graph

def save_graph_image():
    """
    Extracts the LangGraph structure and saves it as a PNG image file.
    """
    try:
        # get_graph() extracts the internal structure.
        # draw_mermaid_png() converts it to a PNG byte string using a default web API.
        png_data = wanderly_graph.get_graph().draw_mermaid_png()
        
        # Open a new file in 'wb' (write binary) mode and save the image
        with open("wanderly_v2_graph.png", "wb") as f:
            f.write(png_data)
            
        print("📸 Success! Graph visualization saved as 'wanderly_v2_graph.png'")
        
    except Exception as e:
        print(f"❌ Failed to generate graph: {e}")

if __name__ == "__main__":
    save_graph_image()