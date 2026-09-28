"""Long-lived JSON-lines Laya worker, executed on the UNO Q Linux processor."""

import argparse
import json
import os
import sys
import time

from status_bridge import StatusBridge


PREFIX = "LAYA_Q_RESPONSE "
LOCAL_MODEL = "/home/arduino/laya-q/model"


def write_response(value):
    sys.stdout.write(PREFIX + json.dumps(value, ensure_ascii=False, allow_nan=False) + "\n")
    sys.stdout.flush()


def load_agent():
    # Avoid importing optional TensorFlow while transformers initializes.
    os.environ.setdefault("USE_TF", "0")
    # Model downloads belong on the computer; fail locally if support files are missing.
    os.environ["HF_HUB_OFFLINE"] = "1"
    os.environ["TRANSFORMERS_OFFLINE"] = "1"
    if not os.path.isfile(os.path.join(LOCAL_MODEL, "model.safetensors")):
        raise FileNotFoundError("Model not installed. Run python laya_q.py setup on your computer first.")
    import laya

    return laya.load(LOCAL_MODEL, device="cpu")


def run(agent, input_stream, status=None):
    status = status or StatusBridge()
    status.set("idle")
    for line in input_stream:
        try:
            request = json.loads(line)
            if not isinstance(request, dict):
                raise ValueError("request must be a JSON object")
            state = request.get("state")
            questions = request.get("questions")
            if not isinstance(state, (str, dict, list)):
                raise ValueError("state must be a string, object, or list")
            if not isinstance(questions, dict) or not questions:
                raise ValueError("questions must be a nonempty object")
            status.set("receiving")
            time.sleep(0.15)
            status.set("working")
            write_response({"ok": True, "result": agent.predict(state, questions)})
            status.set("success")
        except Exception as exc:
            status.set("error")
            write_response({"ok": False, "error": str(exc)})


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--warmup", action="store_true", help="load the installed checkpoint")
    parser.add_argument("--token-stdin", action="store_true", help="read a temporary Hub token from stdin")
    args = parser.parse_args()
    try:
        if args.token_stdin:
            token = sys.stdin.readline().strip()
            if not token.startswith("hf_"):
                raise ValueError("expected a Hugging Face token on stdin")
            os.environ["HF_TOKEN"] = token
        status = StatusBridge()
        if not args.warmup:
            status.set("working")
        agent = load_agent()
        if args.warmup:
            print("Laya checkpoint loaded on UNO Q", file=sys.stderr)
            return 0
        run(agent, sys.stdin, status)
        return 0
    except Exception as exc:
        if not args.warmup:
            status.set("error")
        print(f"Laya startup failed: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
