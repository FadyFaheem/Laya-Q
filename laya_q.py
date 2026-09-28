"""Host-side setup and USB JSON-lines client for an Arduino UNO Q."""

import argparse
from contextlib import contextmanager
import getpass
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import warnings
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


def list_devices():
    try:
        result = subprocess.run([find_adb(), "devices"], check=True, capture_output=True, text=True)
    except subprocess.CalledProcessError as exc:
        raise ToolError(f"ADB device discovery failed (exit {exc.returncode}).") from exc
    lines = [line.split() for line in result.stdout.splitlines()[1:] if line.strip()]
    return [{"serial": line[0], "state": line[1], "description": " ".join(line[2:])}
            for line in lines if len(line) >= 2]


def check_device(serial):
    ready = [device["serial"] for device in list_devices() if device["state"] == "device"]
    if serial and serial not in ready:
        raise ToolError(f"ADB device {serial!r} is not ready. Run 'adb devices'.")
    if not serial and len(ready) != 1:
        raise ToolError(f"Expected one ready UNO Q; found {len(ready)}. Run 'adb devices' or pass --serial.")
    return serial or ready[0]


def read_hf_token(from_stdin=False):
    if from_stdin:
        token = sys.stdin.readline().strip()
    else:
        try:
            with warnings.catch_warnings():
                warnings.simplefilter("error", getpass.GetPassWarning)
                token = getpass.getpass("Hugging Face token (hidden): ").strip()
        except (getpass.GetPassWarning, EOFError) as exc:
            raise ToolError("A masked token prompt is unavailable. Use --hf-token-stdin for automation.") from exc
    if not token.startswith("hf_"):
        raise ToolError("Expected a Hugging Face token starting with hf_.")
    return token


def download_model_on_host(serial, token):
    """Fetch one fixed checkpoint on the computer and copy it over USB."""
    with tempfile.TemporaryDirectory(prefix="laya-q-") as temporary:
        for filename in MODEL_FILES:
            destination = Path(temporary) / filename
            destination.parent.mkdir(parents=True, exist_ok=True)
            url = f"https://huggingface.co/convaiinnovations/laya/resolve/{MODEL_REVISION}/{filename}"
            headers = {"Authorization": f"Bearer {token}"} if token else {}
            print(f"Downloading {filename} on the computer...", flush=True)
            for attempt in range(2):
                try:
                    with urlopen(Request(url, headers=headers), timeout=120) as source, destination.open("wb") as target:
                        shutil.copyfileobj(source, target, length=1024 * 1024)
                    break
                except HTTPError as exc:
                    if exc.code in (401, 403, 429) and not token and attempt == 0 and sys.stdin.isatty():
                        print("The Hub requested authentication or rate-limited this download.", flush=True)
                        token = read_hf_token()
                        headers = {"Authorization": f"Bearer {token}"}
                        continue
                    raise ToolError(f"Host download failed for {filename} (HTTP {exc.code}). Use --hf-token to enter a token privately.") from exc
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
            remote = BOARD_MODEL + "/" + filename
            if filename == "model.safetensors":
                remote += ".partial"
            adb_run(serial, "push", str(Path(temporary) / filename), remote)
        verification = subprocess.run(
            adb_base(serial) + ["shell", "-T", f"sha256sum {BOARD_MODEL}/model.safetensors.partial"],
            check=True, capture_output=True, text=True)
        if not verification.stdout.split() or verification.stdout.split()[0] != MODEL_SHA256:
            raise ToolError("The board's model checksum did not match after USB transfer.")
        adb_run(serial, "shell", "-T", f"mv {BOARD_MODEL}/model.safetensors.partial {BOARD_MODEL}/model.safetensors")
        print("Checkpoint verified on the computer and board after USB transfer.", flush=True)


def setup(serial, skip_warmup, token_stdin=False, download_on_host=True, token_prompt=False):
    token = read_hf_token(from_stdin=token_stdin) if token_stdin or token_prompt else None
    serial = check_device(serial)
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
        print("Loading the English checkpoint on the board; this can take a while.", flush=True)
        if token and not download_on_host:
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
    if not isinstance(value["state"], (str, dict, list)):
        raise ToolError("state must be a string, object, or list.")
    if not isinstance(value["questions"], dict) or not value["questions"]:
        raise ToolError("questions must be a nonempty object.")
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


class AppLabConnection:
    """A reusable USB forward to the persistent App Lab inference service."""

    def __init__(self, serial=None):
        self.serial = check_device(serial)
        self.adb = adb_base(self.serial)
        try:
            result = subprocess.run(self.adb + ["forward", "tcp:0", "tcp:8765"],
                                    check=True, capture_output=True, text=True)
            self.port = int(result.stdout.strip())
        except (subprocess.CalledProcessError, ValueError) as exc:
            raise ToolError("Unable to open the USB connection to App Lab.") from exc

    def request(self, endpoint, value=None, timeout=600):
        if self.port is None:
            raise ToolError("USB connection is closed.")
        request = Request(f"http://127.0.0.1:{self.port}/{endpoint}",
                          data=json.dumps(value).encode("utf-8") if value is not None else None,
                          headers={"Content-Type": "application/json"})
        try:
            with urlopen(request, timeout=timeout) as response:
                return json.load(response)
        except HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise ToolError(f"App Lab request failed (HTTP {exc.code}): {detail}") from exc
        except (URLError, TimeoutError) as exc:
            raise ToolError("App Lab is unavailable or timed out. Run Laya Q in App Lab and wait for it to load.") from exc

    def close(self):
        if self.port is not None:
            subprocess.run(self.adb + ["forward", "--remove", f"tcp:{self.port}"],
                           check=False, capture_output=True)
            self.port = None


@contextmanager
def app_connection(serial=None):
    connection = AppLabConnection(serial)
    try:
        yield connection
    finally:
        connection.close()


def predict_app(serial, path, lines):
    with app_connection(serial) as connection:
        for value in requests_from_file(path, lines):
            print(json.dumps(connection.request("predict", value), ensure_ascii=False), flush=True)


def main():
    parser = argparse.ArgumentParser(description="Run Laya on UNO Q through USB ADB")
    parser.add_argument("--serial", default=os.environ.get("ANDROID_SERIAL"), help="ADB serial if several devices are attached")
    subparsers = parser.add_subparsers(dest="command", required=True)
    install = subparsers.add_parser("setup", help="install the worker and Laya on the board")
    install.add_argument("--skip-warmup", action="store_true", help="skip loading the checkpoint after setup")
    authentication = install.add_mutually_exclusive_group()
    authentication.add_argument("--hf-token", action="store_true", help="prompt privately for a temporary Hugging Face token")
    authentication.add_argument("--hf-token-stdin", action="store_true", help="read a temporary Hub token from stdin for automation")
    location = install.add_mutually_exclusive_group()
    location.add_argument("--download-on-host", dest="download_on_host", action="store_true", help="download on this computer and transfer over USB (default)")
    location.add_argument("--download-on-board", dest="download_on_host", action="store_false", help="download the checkpoint from the board instead")
    install.set_defaults(download_on_host=True)
    ask = subparsers.add_parser("predict", help="send JSON requests to the board")
    ask.add_argument("input", help="JSON file, or '-' for stdin")
    ask.add_argument("--jsonl", action="store_true", help="read multiple newline-delimited JSON requests")
    ask.add_argument("--app-lab", action="store_true", help="use the running imported App Lab app over USB")
    portal = subparsers.add_parser("portal", help="open a local browser testing portal for the App Lab app")
    portal.add_argument("--port", type=int, default=8080, help="local web portal port (default: 8080)")
    portal.add_argument("--no-browser", action="store_true", help="print the URL without opening a browser")
    args = parser.parse_args()
    try:
        if args.command == "setup":
            setup(args.serial, args.skip_warmup, args.hf_token_stdin, args.download_on_host, args.hf_token)
        elif args.command == "portal":
            from web_portal import serve
            serve(port=args.port, serial=args.serial, open_browser=not args.no_browser)
        else:
            if args.app_lab:
                predict_app(args.serial, args.input, args.jsonl)
            else:
                predict(args.serial, args.input, args.jsonl)
        return 0
    except (ToolError, OSError, subprocess.CalledProcessError, json.JSONDecodeError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
