"""Build an importable App Lab ZIP with the pinned public Laya checkpoint."""

import argparse
import hashlib
from pathlib import Path
import shutil
import tempfile
from urllib.request import urlopen
import zipfile


ROOT = Path(__file__).resolve().parent.parent
APP = ROOT / "app_lab" / "laya_status"
REVISION = "55cf4c4ebb4ebe31b2550e8bdf3bd21b99753851"
WEIGHTS_SHA256 = "891102d372688fc2a094dac56a384bc537b87c63f21f9f3dac0be2b7cbc8d86c"
PART_SIZE = 8 * 1024 * 1024
MODEL_FILES = (
    "rl_agent_config.json",
    "model.safetensors",
    "encoder/config.json",
    "tokenizer/tokenizer_config.json",
    "tokenizer/tokenizer.json",
)
APP_FILES = ("app.yaml", "README.md", "python/main.py", "python/requirements.txt",
             "sketch/sketch.ino", "sketch/sketch.yaml")
PROJECT_FILES = ("laya_q.py", "board_worker.py", "status_bridge.py",
                 "examples/triage.json", "README.md")


def sha256(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("output", type=Path, help="output App Lab ZIP")
    parser.add_argument("--weights-file", type=Path, help="reuse a locally downloaded model.safetensors")
    args = parser.parse_args()
    args.output.parent.mkdir(parents=True, exist_ok=True)

    build_dir = ROOT / ".build"
    build_dir.mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="laya-q-release-", dir=build_dir) as temp:
        model = Path(temp)
        for filename in MODEL_FILES:
            target = model / filename
            target.parent.mkdir(parents=True, exist_ok=True)
            if filename == "model.safetensors" and args.weights_file:
                shutil.copyfile(args.weights_file, target)
            else:
                url = f"https://huggingface.co/convaiinnovations/laya/resolve/{REVISION}/{filename}"
                print(f"Downloading {filename}", flush=True)
                with urlopen(url, timeout=120) as source, target.open("wb") as destination:
                    shutil.copyfileobj(source, destination, length=1024 * 1024)
        if sha256(model / "model.safetensors") != WEIGHTS_SHA256:
            raise ValueError("Model weights checksum mismatch")
        with urlopen("https://www.apache.org/licenses/LICENSE-2.0.txt", timeout=120) as source:
            (model / "LICENSE").write_bytes(source.read())
        with zipfile.ZipFile(args.output, "w", allowZip64=True) as archive:
            for filename in APP_FILES:
                archive.write(APP / filename, filename, compress_type=zipfile.ZIP_DEFLATED)
            for filename in PROJECT_FILES:
                archive.write(ROOT / filename, f"tools/{filename}", compress_type=zipfile.ZIP_DEFLATED)
            for filename in MODEL_FILES:
                if filename != "model.safetensors":
                    archive.write(model / filename, f"model/{filename}", compress_type=zipfile.ZIP_DEFLATED)
            archive.write(model / "LICENSE", "model/LICENSE", compress_type=zipfile.ZIP_DEFLATED)
            with (model / "model.safetensors").open("rb") as weights:
                part = 0
                while data := weights.read(PART_SIZE):
                    archive.writestr(f"model/parts/{part:04d}.bin", data,
                                     compress_type=zipfile.ZIP_STORED)
                    part += 1
    print(f"Built {args.output} ({args.output.stat().st_size:,} bytes)")


if __name__ == "__main__":
    main()
