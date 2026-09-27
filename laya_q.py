"""Host-side setup and USB JSON-lines client for an Arduino UNO Q."""

import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


ROOT = Path(__file__).resolve().parent
BOARD_DIR = "/home/arduino/laya-q"
BOARD_PYTHON = BOARD_DIR + "/.venv/bin/python"
BOARD_WORKER = BOARD_DIR + "/board_worker.py"
BOARD_MODEL = BOARD_DIR + "/model"
PREFIX = "LAYA_Q_RESPONSE "
MODEL_REVISION = "55cf4c4ebb4ebe31b2550e8bdf3bd21b99753851"
MODEL_SHA256 = "891102d372688fc2a094dac56a384bc537b87c63f21f9f3dac0be2b7cbc8d86c"
MODEL_FILES = ("rl_agent_config.json", "model.safetensors", "encoder/config.json",
               "tokenizer/tokenizer_config.json", "tokenizer/tokenizer.json")


class ToolError(Exception):
    pass


def adb_base(serial):
    return [find_adb()] + (["-s", serial] if serial else [])


def find_adb():
    """Use Arduino App Lab's bundled ADB when it is not on PATH."""
    on_path = shutil.which("adb")
    if on_path:
        return on_path
    local = os.environ.get("LOCALAPPDATA")
    if local:
        for base in (Path(local) / "Arduino15" / "packages" / "arduino" / "tools" / "adb",
                     Path(local) / "AppLab" / "a15" / "data" / "packages" / "arduino" / "tools" / "adb"):
            if base.is_dir():
                candidates = sorted(base.glob("*/adb.exe"), reverse=True)
                if candidates:
                    return str(candidates[0])
    raise ToolError("ADB is missing. Install Arduino App Lab or Android platform-tools.")


def adb_run(serial, *arguments):
    try:
        return subprocess.run(adb_base(serial) + list(arguments), check=True, text=True)
    except FileNotFoundError as exc:
        raise ToolError("ADB is missing. Install Android platform-tools and add adb to PATH.") from exc
    except subprocess.CalledProcessError as exc:
        raise ToolError(f"ADB command failed (exit {exc.returncode}).") from exc


def check_device(serial):
    try:
        result = subprocess.run([find_adb(), "devices"], check=True, capture_output=True, text=True)
    except subprocess.CalledProcessError as exc:
        raise ToolError(f"ADB device discovery failed (exit {exc.returncode}).") from exc
    lines = [line.split() for line in result.stdout.splitlines()[1:] if line.strip()]
    ready = [line[0] for line in lines if len(line) >= 2 and line[1] == "device"]
    if serial and serial not in ready:
        raise ToolError(f"ADB device {serial!r} is not ready. Run 'adb devices'.")
    if not serial and len(ready) != 1:
        raise ToolError(f"Expected one ready UNO Q; found {len(ready)}. Run 'adb devices' or pass --serial.")


def download_model_on_host(serial, token):
    """Fetch one fixed checkpoint on the computer and copy it over USB."""
    with tempfile.TemporaryDirectory(prefix="laya-q-") as temporary:
        for filename in MODEL_FILES:
            destination = Path(temporary) / filename
            destination.parent.mkdir(parents=True, exist_ok=True)
            url = f"https://huggingface.co/convaiinnovations/laya/resolve/{MODEL_REVISION}/{filename}"
            headers = {"Authorization": f"Bearer {token}"} if token else {}
            print(f"Downloading {filename} on the computer...", flush=True)
            try:
                with urlopen(Request(url, headers=headers), timeout=120) as source, destination.open("wb") as target:
                    shutil.copyfileobj(source, target, length=1024 * 1024)
            except URLError as exc:
                raise ToolError(f"Host download failed for {filename}: {exc.reason}") from exc
            if filename == "model.safetensors":
                with destination.open("rb") as model_file:
                    digest = hashlib.file_digest(model_file, "sha256").hexdigest()
                if digest != MODEL_SHA256:
                    raise ToolError("Downloaded model checksum did not match the pinned checkpoint.")
        for directory in (BOARD_MODEL, BOARD_MODEL + "/encoder", BOARD_MODEL + "/tokenizer"):
            adb_run(serial, "shell", "-T", f"mkdir -p {directory}")
        for filename in MODEL_FILES:
            adb_run(serial, "push", str(Path(temporary) / filename), BOARD_MODEL + "/" + filename)


def setup(serial, skip_warmup, token_stdin=False, download_on_host=False):
    if skip_warmup and download_on_host:
        raise ToolError("Choose --skip-warmup or --download-on-host, not both.")
    token = None
    if token_stdin:
        token = sys.stdin.readline().strip()
        if not token.startswith("hf_"):
            raise ToolError("Expected a Hugging Face token on stdin.")
    check_device(serial)
    adb_run(serial, "shell", "-T", f"mkdir -p {BOARD_DIR}")
    adb_run(serial, "push", str(ROOT / "board_worker.py"), BOARD_WORKER)
    adb_run(serial, "push", str(ROOT / "status_bridge.py"), BOARD_DIR + "/status_bridge.py")
    adb_run(serial, "shell", "-T", f"python3 -m venv --without-pip {BOARD_DIR}/.venv")
    adb_run(serial, "shell", "-T", f"mkdir -p {BOARD_DIR}/tmp {BOARD_DIR}/pip-cache")
    pip_env = f"TMPDIR={BOARD_DIR}/tmp PIP_CACHE_DIR={BOARD_DIR}/pip-cache"
    adb_run(serial, "shell", "-T", f"curl -fLsS --retry 5 --retry-all-errors --retry-delay 2 -o {BOARD_DIR}/get-pip.py https://bootstrap.pypa.io/get-pip.py")
    adb_run(serial, "shell", "-T", f"{pip_env} {BOARD_PYTHON} {BOARD_DIR}/get-pip.py")
    adb_run(serial, "shell", "-T", f"{pip_env} {BOARD_PYTHON} -m pip install torch==2.9.1+cpu --index-url https://download.pytorch.org/whl/cpu")
    adb_run(serial, "shell", "-T", f"{pip_env} {BOARD_PYTHON} -m pip install laya==0.3.20")
    adb_run(serial, "shell", "-T", f"{pip_env} {BOARD_PYTHON} -m pip install msgpack==1.1.1")
    if download_on_host:
        download_model_on_host(serial, token)
    if not skip_warmup:
        print("Downloading and loading the English checkpoint on the board; this can take a while.", flush=True)
        if token_stdin:
            command = adb_base(serial) + ["shell", "-T", f"{BOARD_PYTHON} -u {BOARD_WORKER} --warmup --token-stdin"]
            result = subprocess.run(command, input=token + "\n", text=True)
            if result.returncode:
                raise ToolError(f"Board warmup failed (exit {result.returncode}).")
        else:
            adb_run(serial, "shell", "-T", f"{BOARD_PYTHON} -u {BOARD_WORKER} --warmup")
    print("UNO Q setup complete.")


def validate_request(value):
    if not isinstance(value, dict) or "state" not in value or "questions" not in value:
        raise ToolError("Each request needs 'state' and 'questions' fields.")
    return value


def requests_from_file(path, lines):
    stream = sys.stdin if path == "-" else open(path, encoding="utf-8")
    try:
        if lines:
            for line in stream:
                if line.strip():
                    yield validate_request(json.loads(line))
        else:
            yield validate_request(json.load(stream))
    finally:
        if stream is not sys.stdin:
            stream.close()


def predict(serial, path, lines):
    check_device(serial)
    command = adb_base(serial) + ["shell", "-T", f"{BOARD_PYTHON} -u {BOARD_WORKER}"]
    try:
        with subprocess.Popen(command, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                              stderr=sys.stderr, text=True, encoding="utf-8", bufsize=1) as process:
            for request in requests_from_file(path, lines):
                process.stdin.write(json.dumps(request, ensure_ascii=False) + "\n")
                process.stdin.flush()
                for reply in process.stdout:
                    if reply.startswith(PREFIX):
                        payload = json.loads(reply[len(PREFIX):])
                        if not payload.get("ok"):
                            raise ToolError(payload.get("error", "Board inference failed."))
                        print(json.dumps(payload["result"], ensure_ascii=False), flush=True)
                        break
                else:
                    raise ToolError("Board worker exited before returning a response. Check its error output and run setup again.")
            process.stdin.close()
            if process.wait() != 0:
                raise ToolError("Board worker failed. Check its error output.")
    except FileNotFoundError as exc:
        raise ToolError("ADB is missing. Install Android platform-tools and add adb to PATH.") from exc


def predict_app(serial, path, lines):
    """Connect to a running imported App Lab app using a temporary USB forward."""
    check_device(serial)
    result = subprocess.run(adb_base(serial) + ["forward", "tcp:0", "tcp:8765"],
                            check=True, capture_output=True, text=True)
    port = int(result.stdout.strip())
    try:
        for value in requests_from_file(path, lines):
            request = Request(f"http://127.0.0.1:{port}/predict",
                              data=json.dumps(value).encode("utf-8"),
                              headers={"Content-Type": "application/json"})
            try:
                with urlopen(request, timeout=600) as response:
                    print(json.dumps(json.load(response), ensure_ascii=False), flush=True)
            except HTTPError as exc:
                raise ToolError(f"App Lab prediction failed: {exc.read().decode('utf-8')}") from exc
            except URLError as exc:
                raise ToolError("App Lab endpoint is unavailable. Import the release ZIP and run Laya Q first.") from exc
    finally:
        subprocess.run(adb_base(serial) + ["forward", "--remove", f"tcp:{port}"],
                       check=False, capture_output=True)


def main():
    parser = argparse.ArgumentParser(description="Run Laya on UNO Q through USB ADB")
    parser.add_argument("--serial", default=os.environ.get("ANDROID_SERIAL"), help="ADB serial if several devices are attached")
    subparsers = parser.add_subparsers(dest="command", required=True)
    install = subparsers.add_parser("setup", help="install the worker and Laya on the board")
    install.add_argument("--skip-warmup", action="store_true", help="download checkpoint on first prediction instead")
    install.add_argument("--hf-token-stdin", action="store_true", help="read a Hub token from stdin for this setup only")
    install.add_argument("--download-on-host", action="store_true", help="download checkpoint on this computer and transfer it over USB")
    ask = subparsers.add_parser("predict", help="send JSON requests to the board")
    ask.add_argument("input", help="JSON file, or '-' for stdin")
    ask.add_argument("--jsonl", action="store_true", help="read multiple newline-delimited JSON requests")
    ask.add_argument("--app-lab", action="store_true", help="use the running imported App Lab app over USB")
    args = parser.parse_args()
    try:
        if args.command == "setup":
            setup(args.serial, args.skip_warmup, args.hf_token_stdin, args.download_on_host)
        else:
            if args.app_lab:
                predict_app(args.serial, args.input, args.jsonl)
            else:
                predict(args.serial, args.input, args.jsonl)
        return 0
    except (ToolError, OSError, json.JSONDecodeError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
