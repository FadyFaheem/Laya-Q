"""App Lab entry point: local Laya HTTP API with matrix status on the STM32."""

import json
import os
from pathlib import Path
import hashlib
import shutil
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from arduino.app_utils import App, Bridge


PORT = 8765
APP_ROOT = Path(__file__).resolve().parent.parent
SOURCE_MODEL = APP_ROOT / "model"
MODEL = APP_ROOT / ".cache" / "model"
WEIGHTS_SHA256 = "891102d372688fc2a094dac56a384bc537b87c63f21f9f3dac0be2b7cbc8d86c"
PREDICT_LOCK = threading.Lock()
AGENT = None


def prepare_model():
    MODEL.mkdir(parents=True, exist_ok=True)
    weights = MODEL / "model.safetensors"
    if not weights.is_file():
        parts = sorted((SOURCE_MODEL / "parts").glob("*.bin"))
        if not parts:
            raise FileNotFoundError("Bundled checkpoint parts are missing; import the release ZIP")
        digest = hashlib.sha256()
        temporary = MODEL / "model.safetensors.partial"
        with temporary.open("wb") as output:
            for part in parts:
                with part.open("rb") as source:
                    while chunk := source.read(1024 * 1024):
                        digest.update(chunk)
                        output.write(chunk)
        if digest.hexdigest() != WEIGHTS_SHA256:
            temporary.unlink(missing_ok=True)
            raise ValueError("Bundled checkpoint checksum mismatch")
        temporary.replace(weights)
    for filename in ("rl_agent_config.json", "encoder/config.json",
                     "tokenizer/tokenizer_config.json", "tokenizer/tokenizer.json"):
        target = MODEL / filename
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(SOURCE_MODEL / filename, target)


def status(code):
    try:
        Bridge.call("laya_status", code)
    except Exception as exc:
        print(f"Matrix status unavailable: {exc}", flush=True)


class Handler(BaseHTTPRequestHandler):
    def reply(self, code, value):
        body = json.dumps(value, ensure_ascii=False, allow_nan=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path == "/health":
            self.reply(200, {"ready": AGENT is not None})
        else:
            self.reply(404, {"error": "Use POST /predict or GET /health"})

    def do_POST(self):
        if self.path != "/predict":
            return self.reply(404, {"error": "Use POST /predict"})
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if length <= 0 or length > 1048576:
                return self.reply(413, {"error": "Request must be 1 MB or less"})
            request = json.loads(self.rfile.read(length))
            if not isinstance(request, dict) or not isinstance(request.get("state"), (str, dict, list)):
                raise ValueError("state must be a string, object, or list")
            questions = request.get("questions")
            if not isinstance(questions, dict) or not questions:
                raise ValueError("questions must be a nonempty object")
            status(1)
            time.sleep(0.15)
            with PREDICT_LOCK:
                status(2)
                result = AGENT.predict(request["state"], questions)
            self.reply(200, result)
            status(3)
        except (ValueError, TypeError, json.JSONDecodeError) as exc:
            status(4)
            self.reply(400, {"error": str(exc)})
        except Exception as exc:
            status(4)
            self.reply(500, {"error": str(exc)})


def main():
    global AGENT
    os.environ.setdefault("USE_TF", "0")
    os.environ.setdefault("HF_HUB_DISABLE_XET", "1")
    status(2)
    prepare_model()
    import laya
    AGENT = laya.load(str(MODEL), device="cpu")
    server = ThreadingHTTPServer(("0.0.0.0", PORT), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    status(0)
    App.run(user_loop=lambda: time.sleep(1))


if __name__ == "__main__":
    main()
