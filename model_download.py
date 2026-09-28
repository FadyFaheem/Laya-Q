"""Download a consistent, current Laya snapshot without hardcoded revisions or hashes."""

import hashlib
import json
from pathlib import Path, PurePosixPath
import re
import shutil
from urllib.request import Request, urlopen


MODEL_REPO = "convaiinnovations/laya"
MANIFEST = ".laya-model.json"


def safe_path(name):
    path = PurePosixPath(name)
    if not re.fullmatch(r"[A-Za-z0-9_./-]+", name) or path.is_absolute() or ".." in path.parts:
        raise ValueError("Unsafe model filename")
    return name


def cache_complete(folder, expected=None):
    folder = Path(folder)
    try:
        manifest = json.loads((folder / MANIFEST).read_text(encoding="utf-8"))
        if expected is not None and manifest != expected:
            return False
        files = manifest["files"]
        if not {"model.safetensors", "rl_agent_config.json"}.issubset({entry["path"] for entry in files}):
            return False
        return all((folder / safe_path(entry["path"])).stat().st_size == entry["size"] for entry in files)
    except (OSError, ValueError, KeyError, TypeError):
        return False


def file_digest(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def download_snapshot(destination, token=None, weights_file=None, open_remote=None):
    """Resolve main once, then fetch its weights and required support files together."""
    destination = Path(destination)
    destination.mkdir(parents=True, exist_ok=True)
    if open_remote is None:
        def open_remote(url):
            headers = {"Authorization": f"Bearer {token}"} if token else {}
            return urlopen(Request(url, headers=headers), timeout=120)

    with open_remote(f"https://huggingface.co/api/models/{MODEL_REPO}/revision/main?blobs=true") as response:
        info = json.load(response)
    revision = info.get("sha", "")
    if not re.fullmatch(r"[a-f0-9]{40,64}", revision):
        raise ValueError("The Hub did not return a valid model revision")
    files = []
    for entry in info.get("siblings", []):
        name = entry.get("rfilename", "")
        if name not in ("rl_agent_config.json", "model.safetensors") and not name.startswith(("encoder/", "tokenizer/")):
            continue
        safe_path(name)
        files.append(entry)
    if not {"rl_agent_config.json", "model.safetensors"}.issubset({entry["rfilename"] for entry in files}):
        raise ValueError("The current repository does not contain a supported Laya checkpoint")

    manifest = {"repo": MODEL_REPO, "revision": revision, "files": []}
    (destination / MANIFEST).unlink(missing_ok=True)
    print(f"Downloading Laya revision {revision[:12]}...", flush=True)
    for entry in files:
        name = entry["rfilename"]
        target = destination / (name + ".partial")
        target.parent.mkdir(parents=True, exist_ok=True)
        print(f"  {name}", flush=True)
        if name == "model.safetensors" and weights_file:
            shutil.copyfile(weights_file, target)
        else:
            with open_remote(f"https://huggingface.co/{MODEL_REPO}/resolve/{revision}/{name}") as source, target.open("wb") as output:
                shutil.copyfileobj(source, output, length=1024 * 1024)
        size = target.stat().st_size
        digest = file_digest(target)
        expected_size = entry.get("size")
        expected_digest = (entry.get("lfs") or {}).get("sha256")
        if expected_size is not None and size != expected_size:
            raise ValueError(f"Incomplete or outdated model file: {name}; download the current checkpoint again")
        if expected_digest and digest != expected_digest:
            raise ValueError(f"Model checksum does not match the current Hub revision: {name}; download it again")
        target.replace(destination / name)
        manifest["files"].append({"path": name, "size": size, "sha256": digest})
    temporary = destination / (MANIFEST + ".partial")
    temporary.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    temporary.replace(destination / MANIFEST)
    return manifest
