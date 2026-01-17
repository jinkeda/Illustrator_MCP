
import time
import logging
import json
from illustrator_mcp.websocket_bridge import WebSocketBridge

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger("demo_server")
# Enable debug logging for the bridge
logging.getLogger("illustrator_mcp.websocket_bridge").setLevel(logging.DEBUG)


def run_demo_server():
    # Kill any existing server on this port (manually if needed, but assuming clear)
    bridge = WebSocketBridge(port=8081)
    
    # Start the bridge (starts in a dedicated thread)
    logger.info("Starting WebSocket Bridge on port 8081...")
    bridge.start()
    
    logger.info("="*50)
    logger.info("WAITING FOR CEP PANEL TO CONNECT...")
    logger.info("Please RELOAD the MCP Control panel in Illustrator")
    logger.info("="*50)
    
    # Wait for client connection
    while not bridge.is_connected():
        time.sleep(1)
    
    logger.info("CEP Panel Connected! Running demo...")
    time.sleep(2)  # Give it a moment to settle
    
    try:
        # 1. Create Document
        logger.info("Creating document...")
        script1 = """
        (function() {
            var doc = app.documents.add(DocumentColorSpace.RGB, 500, 500);
            doc.name = "Hybrid Demo";
            return JSON.stringify({success: true, name: doc.name});
        })()
        """
        # Using sync execute_script which handles thread safety
        res = bridge.execute_script(script1, command_type="create_document", tool_name="demo_setup")
        logger.info(f"Result: {res}")
        
        # 2. Draw Rectangles (Hybrid)
        colors = ['#FF5733', '#33FF57', '#3357FF']
        for i, color in enumerate(colors):
            logger.info(f"Drawing rectangle {i+1}...")
            script = f"""
            (function() {{
                var doc = app.activeDocument;
                var rect = doc.pathItems.rectangle({-100}, {50 + i*110}, 100, 100);
                var col = new RGBColor();
                col.red = {int(color[1:3], 16)};
                col.green = {int(color[3:5], 16)};
                col.blue = {int(color[5:7], 16)};
                rect.fillColor = col;
                return JSON.stringify({{success: true}});
            }})()
            """
            res = bridge.execute_script(
                script, 
                command_type="draw_rectangle", 
                tool_name=f"demo_rect_{i+1}",
                params={"color": color}
            )
            logger.info(f"Result: {res}")
            time.sleep(0.5)

        logger.info("Demo complete! Check Illustrator panel logs.")
        
    except Exception as e:
        logger.error(f"Error during demo: {e}")
    
    # Keep running so connection stays open
    logger.info("Server running. Press Ctrl+C to stop.")
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        logger.info("Stopping...")
        bridge.stop()

if __name__ == "__main__":
    run_demo_server()
