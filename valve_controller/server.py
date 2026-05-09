import json
import os
import logging
import queue
from http.server import BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs

logger = logging.getLogger("valve-controller")


class ValveRequestHandler(BaseHTTPRequestHandler):
    """HTTP request handler for valve controller API."""

    controller = None  # Set by main before starting server

    def log_message(self, format, *args):
        logger.info(f"{self.client_address[0]} - {format % args}")

    def _send_json(self, status_code, data):
        body = json.dumps(data).encode("utf-8")
        self.send_response(status_code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(body)

    def _send_html(self, html):
        body = html.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _parse_path(self):
        parsed = urlparse(self.path)
        return parsed.path.rstrip("/"), parse_qs(parsed.query)

    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    def do_GET(self):
        path, params = self._parse_path()

        if path == "" or path == "/":
            self._serve_dashboard()
        elif path == "/api/status":
            status = self.controller.get_status()
            self._send_json(200, status)
        elif path == "/api/config":
            zones = self.controller.relay.zones
            self._send_json(200, {"zones": zones, "num_zones": len(zones)})
        elif path == "/events":
            self._handle_sse()
        else:
            self._send_json(404, {"error": "Not found"})

    def do_POST(self):
        path, params = self._parse_path()

        # POST /api/valve/{zone}/open?duration=X
        if path.startswith("/api/valve/") and path.endswith("/open"):
            parts = path.split("/")
            if len(parts) == 5:
                zone = parts[3]
                duration_list = params.get("duration", [])
                if not duration_list:
                    self._send_json(400, {"error": "Missing required parameter: duration"})
                    return
                try:
                    duration = float(duration_list[0])
                except ValueError:
                    self._send_json(400, {"error": "Invalid duration value"})
                    return

                logger.warning(
                    f"OPEN REQUEST from {self.client_address[0]} — "
                    f"zone={zone}, duration={duration}s"
                )
                success, code, message, detail = self.controller.open_valve(zone, duration)
                logger.warning(
                    f"OPEN RESULT for {self.client_address[0]} — "
                    f"zone={zone}, code={code}, message={message}, detail={detail}"
                )
                self._send_json(code, {"success": success, "message": message, **detail})
                return

        # POST /api/valve/{zone}/close
        if path.startswith("/api/valve/") and path.endswith("/close"):
            parts = path.split("/")
            if len(parts) == 5:
                zone = parts[3]
                success, code, message, detail = self.controller.close_valve(zone)
                self._send_json(code, {"success": success, "message": message, **detail})
                return

        # POST /api/close (close whatever is active)
        if path == "/api/close":
            success, code, message, detail = self.controller.close_valve()
            self._send_json(code, {"success": success, "message": message, **detail})
            return

        self._send_json(404, {"error": "Not found"})

    def _handle_sse(self):
        """Server-Sent Events endpoint for real-time zone status updates."""
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("X-Accel-Buffering", "no")
        self.end_headers()

        q = self.controller.subscribe()
        try:
            # Send initial status as an event
            status = self.controller.get_status()
            init_event = f"event: init\ndata: {json.dumps(status)}\n\n"
            self.wfile.write(init_event.encode("utf-8"))
            self.wfile.flush()

            while True:
                try:
                    message = q.get(timeout=30)
                    event = f"data: {message}\n\n"
                    self.wfile.write(event.encode("utf-8"))
                    self.wfile.flush()
                except queue.Empty:
                    # Send keepalive comment
                    self.wfile.write(b": keepalive\n\n")
                    self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError):
            pass
        finally:
            self.controller.unsubscribe(q)

    def _serve_dashboard(self):
        web_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "web")
        index_path = os.path.join(web_dir, "index.html")
        try:
            with open(index_path, "r") as f:
                self._send_html(f.read())
        except FileNotFoundError:
            self._send_html("<h1>Valve Controller</h1><p>Dashboard not found</p>")
