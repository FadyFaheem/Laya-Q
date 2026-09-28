"""Build a clean App Lab ZIP, optionally including an offline model payload."""

import argparse
from pathlib import Path
import sys
import tempfile
from urllib.request import urlopen
import zipfile


ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from model_download import MANIFEST, download_snapshot

APP = ROOT / "app_lab" / "laya_status"
PART_SIZE = 8 * 1024 * 1024
APP_FILES = ("app.yaml", "README.md", "python/main.py", "python/requirements.txt",
             "sketch/sketch.ino", "sketch/sketch.yaml")
PROJECT_FILES = ("laya_q.py", "model_download.py", "board_worker.py", "status_bridge.py",
                 "web_portal.py", "portal/index.html", "portal/portal.css", "portal/portal.js",
                 "examples/triage.json", "README.md")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("output", type=Path, help="output App Lab ZIP")
    parser.add_argument("--include-model", action="store_true", help="include split checkpoint pieces for offline model loading")
    parser.add_argument("--weights-file", type=Path, help="reuse local weights for an offline bundle; checked against current Hub metadata")
    args = parser.parse_args()
    args.output.parent.mkdir(parents=True, exist_ok=True)

    build_dir = ROOT / ".build"
    build_dir.mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="laya-q-release-", dir=build_dir) as temp:
        model = Path(temp)
        include_model = args.include_model or args.weights_file is not None
        if include_model:
            manifest = download_snapshot(model, weights_file=args.weights_file)
            with urlopen("https://www.apache.org/licenses/LICENSE-2.0.txt", timeout=120) as source:
                (model / "LICENSE").write_bytes(source.read())
        with zipfile.ZipFile(args.output, "w", allowZip64=True) as archive:
            for filename in APP_FILES:
                archive.write(APP / filename, filename, compress_type=zipfile.ZIP_DEFLATED)
            for filename in PROJECT_FILES:
                archive.write(ROOT / filename, f"tools/{filename}", compress_type=zipfile.ZIP_DEFLATED)
            archive.write(ROOT / "model_download.py", "python/model_download.py", compress_type=zipfile.ZIP_DEFLATED)
            if include_model:
                for entry in manifest["files"]:
                    filename = entry["path"]
                    if filename != "model.safetensors":
                        archive.write(model / filename, f"model/{filename}", compress_type=zipfile.ZIP_DEFLATED)
                for filename in (MANIFEST, "LICENSE"):
                    archive.write(model / filename, f"model/{filename}", compress_type=zipfile.ZIP_DEFLATED)
                with (model / "model.safetensors").open("rb") as weights:
                    part = 0
                    while data := weights.read(PART_SIZE):
                        archive.writestr(f"model/parts/{part:04d}.bin", data, compress_type=zipfile.ZIP_STORED)
                        part += 1
    print(f"Built {args.output} ({args.output.stat().st_size:,} bytes)")


if __name__ == "__main__":
    main()
