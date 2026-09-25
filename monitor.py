"""
monitor.py — Flask status dashboard and shared telemetry metrics.
Exposes GET /status on :5000 (or :5001 if 5000 is occupied by another terminal).
"""

import socket
import threading
import time
from flask import Flask, jsonify
from logger import get_logger

logger = get_logger(__name__)

app = Flask(__name__)

# Global state to share across bot components
global_state = {
    "start_time": time.time(),
    "jobs_posted_last_hour": 0,
    "last_token_refresh": None,
    "memory_usage_mb": 0.0,
    "active_urls": 0,
    "errors_last_hour": 0,
    "platform": "all",
}


@app.route("/status")
def status():
    uptime_seconds = time.time() - global_state["start_time"]
    uptime_hours = round(uptime_seconds / 3600, 2)

    response = {
        "platform": global_state.get("platform", "all"),
        "uptime_hours": uptime_hours,
        "jobs_posted_last_hour": global_state["jobs_posted_last_hour"],
        "last_token_refresh": global_state["last_token_refresh"],
        "memory_usage_mb": round(global_state["memory_usage_mb"], 2),
        "active_urls": global_state["active_urls"],
        "errors_last_hour": global_state["errors_last_hour"],
    }
    return jsonify(response)


def is_port_in_use(port: int) -> bool:
    """Check if a TCP port is currently in use."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        return s.connect_ex(("127.0.0.1", port)) == 0


def start_dashboard(preferred_port: int = 5000):
    """
    Starts the Flask dashboard in a background daemon thread.
    Gracefully falls back to another port or skips if running in parallel terminals.
    """
    target_port = preferred_port
    if is_port_in_use(target_port):
        target_port = preferred_port + 1
        if is_port_in_use(target_port):
            logger.info(
                f"ℹ️ Dashboard ports {preferred_port} & {target_port} in use (another platform instance is likely running). Status dashboard skipped for this terminal."
            )
            return None

    def run():
        import logging
        from flask import cli

        cli.show_server_banner = lambda *x: None
        log = logging.getLogger("werkzeug")
        log.setLevel(logging.ERROR)

        try:
            app.run(host="0.0.0.0", port=target_port, debug=False, use_reloader=False)
        except OSError as e:
            logger.warning(f"Could not bind dashboard to port {target_port}: {e}")

    dashboard_thread = threading.Thread(target=run, daemon=True)
    dashboard_thread.start()
    logger.info(f"📊 Dashboard active on http://localhost:{target_port}/status")
    return dashboard_thread
