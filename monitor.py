import threading
import time
from flask import Flask, jsonify

app = Flask(__name__)

# Global state to share with the main bot
global_state = {
    "start_time": time.time(),
    "jobs_posted_last_hour": 0,
    "last_token_refresh": None,
    "memory_usage_mb": 0.0,
    "active_urls": 0,
    "errors_last_hour": 0
}

@app.route('/status')
def status():
    uptime_seconds = time.time() - global_state["start_time"]
    uptime_hours = round(uptime_seconds / 3600, 2)
    
    response = {
        "uptime_hours": uptime_hours,
        "jobs_posted_last_hour": global_state["jobs_posted_last_hour"],
        "last_token_refresh": global_state["last_token_refresh"],
        "memory_usage_mb": round(global_state["memory_usage_mb"], 2),
        "active_urls": global_state["active_urls"],
        "errors_last_hour": global_state["errors_last_hour"]
    }
    return jsonify(response)

def start_dashboard():
    """Starts the Flask dashboard in a background thread."""
    def run():
        # run on 0.0.0.0 to be accessible, port 5000, disable reloader and debug
        # suppress werkzeug logging
        import logging
        log = logging.getLogger('werkzeug')
        log.setLevel(logging.ERROR)
        app.run(host='0.0.0.0', port=5000, debug=False, use_reloader=False)

    dashboard_thread = threading.Thread(target=run, daemon=True)
    dashboard_thread.start()
    return dashboard_thread
