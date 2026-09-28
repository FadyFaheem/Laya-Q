"""Local browser portal using the UNO Q's existing App Lab USB ADB service."""

import json
import threading
import time
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from laya_q import AppLabConnection, ROOT, ToolError, list_devices, validate_request


class PortalState:
    def __init__(self, serial=None):
        self.preferred_serial = serial
        self.connection = None
        self.lock = threading.Lock()

    def connect(self, serial):
        with self.lock:
            connection = AppLabConnection(serial or self.preferred_serial)
            try:
                health = connection.request("health", timeout=10)
                if not health.get("ready"):
                    raise ToolError("Laya Q is still loading. Wait, then connect again.")
            except Exception:
                connection.close()
                raise
            if self.connection:
                self.connection.close()
            self.connection = connection
            return {"connected": True, "serial": connection.serial}

    def disconnect(self):
        with self.lock:
            if self.connection:
                self.connection.close()
                self.connection = None

    def predict(self, request):
        validate_request(request)
        with self.lock:
            if not self.connection:
                raise ToolError("Connect to your UNO Q first.")
            started = time.perf_counter()
            result = self.connection.request("predict", request)
            return {"result": result, "elapsed_ms": round((time.perf_counter() - started) * 1000)}


class PortalServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, address, state):
        self.state = state
        super().__init__(address, Handler)

    def server_close(self):
        self.state.disconnect()
        super().server_close()


class Handler(BaseHTTPRequestHandler):
    def local_request(self):
        expected = f"127.0.0.1:{self.server.server_port}"
        if self.headers.get("Host") != expected:
            self.reply(403, {"error": "Open the portal using its printed 127.0.0.1 URL."})
            return False
        origin = self.headers.get("Origin")
        if origin and origin != f"http://{expected}":
            self.reply(403, {"error": "Cross-origin requests are not allowed."})
            return False
        return True

    def reply(self, code, value):
        data = json.dumps(value, ensure_ascii=False, allow_nan=False).encode("utf-8")
        self.send_data(code, data, "application/json; charset=utf-8")

    def send_data(self, code, data, content_type):
        self.send_response(code)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Content-Security-Policy", "default-src 'self'; frame-ancestors 'none'; base-uri 'none'")
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        if not self.local_request():
            return
        try:
            if self.path == "/api/devices":
                return self.reply(200, {"devices": list_devices(), "preferred_serial": self.server.state.preferred_serial})
            if self.path == "/api/example":
                return self.reply(200, json.loads((ROOT / "examples/triage.json").read_text(encoding="utf-8")))
            files = {"/": ("index.html", "text/html; charset=utf-8"),
                     "/portal.css": ("portal.css", "text/css; charset=utf-8"),
                     "/portal.js": ("portal.js", "text/javascript; charset=utf-8")}
            if self.path not in files:
                return self.reply(404, {"error": "Not found"})
            filename, content_type = files[self.path]
            self.send_data(200, (ROOT / "portal" / filename).read_bytes(), content_type)
        except ToolError as exc:
            self.reply(503, {"error": str(exc)})
        except OSError:
            self.reply(500, {"error": "A required portal file or executable is unavailable."})

    def do_POST(self):
        if not self.local_request():
            return
        if self.headers.get_content_type() != "application/json":
            return self.reply(415, {"error": "Send application/json"})
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if length <= 0 or length > 1048576:
                return self.reply(413, {"error": "Request must be 1 MB or less"})
            value = json.loads(self.rfile.read(length))
            if not isinstance(value, dict):
                raise ValueError("Request must be a JSON object")
            if self.path == "/api/connect":
                serial = value.get("serial")
                if serial is not None and not isinstance(serial, str):
                    raise ValueError("Device serial must be a string")
                return self.reply(200, self.server.state.connect(serial))
            if self.path == "/api/disconnect":
                self.server.state.disconnect()
                return self.reply(200, {"connected": False})
            if self.path == "/api/predict":
                return self.reply(200, self.server.state.predict(value))
            self.reply(404, {"error": "Not found"})
        except (ValueError, ToolError) as exc:
            self.reply(400, {"error": str(exc)})
        except OSError:
            self.reply(503, {"error": "The USB connection is unavailable. Reconnect the board and try again."})


def serve(port=8080, serial=None, open_browser=True):
    server = PortalServer(("127.0.0.1", port), PortalState(serial))
    url = f"http://127.0.0.1:{server.server_port}"
    print(f"Laya Q portal: {url}\nRun Laya Q in App Lab, then connect in the browser. Press Ctrl+C to stop.", flush=True)
    if open_browser:
        webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
