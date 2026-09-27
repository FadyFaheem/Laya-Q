# Working on Laya Q

These instructions apply throughout this repository. Read `README.md` and the relevant source before changing behavior. Keep this file current when the architecture or supported workflows change.

## Purpose and hardware

- Run the English `convaiinnovations/laya` checkpoint on an Arduino UNO Q's Linux processor in CPU mode. The computer sends requests and receives results over USB ADB; inference stays on the board.
- Laya returns typed decisions, scores, and probabilities. It does not generate chat text.
- The STM32 drives the UNO Q's built-in **8 x 13 blue LED matrix**. Use this matrix for status, not the separate RGB LEDs. The user has authorized creative matrix designs.
- The tested board has 4 GB RAM. Do not promise support or performance for other configurations without testing.

## Project map

| Path | Responsibility |
| --- | --- |
| `laya_q.py` | Standard-library host CLI, ADB discovery, setup, host downloads, and both prediction transports |
| `board_worker.py` | Direct Linux worker: loads Laya and handles JSON-lines requests |
| `status_bridge.py` | Direct worker's MessagePack RPC client for STM32 status |
| `app_lab/laya_status/app.yaml` | App Lab manifest for the full **Laya Q** app |
| `app_lab/laya_status/python/main.py` | Persistent App Lab inference service and bundled checkpoint assembly |
| `app_lab/laya_status/python/requirements.txt` | App Lab Python dependencies |
| `app_lab/laya_status/sketch/` | STM32 matrix animations and Bridge RPC |
| `scripts/build_app_lab.py` | Public model download, checksum verification, and App Lab ZIP packaging |
| `examples/triage.json` | Example request used for board smoke checks |
| `tests/` | Host protocol, HTTP API, and checkpoint assembly tests |
| `.github/workflows/` | CI on main/PRs and releases on version tags |

The source folder name `laya_status` is historical: it now contains the full inference app, not just a status companion.

## Two runtime modes

**Direct worker:** `setup` installs code and a private virtual environment under `/home/arduino/laya-q`. `predict` starts the worker through an ADB shell and keeps it loaded for that invocation's requests.

```powershell
python laya_q.py setup --download-on-host
python laya_q.py predict examples/triage.json
python laya_q.py predict requests.jsonl --jsonl
```

The worker emits exactly one `LAYA_Q_RESPONSE `-prefixed JSON response per request. Preserve this framing and the `ok`, `result`, and `error` fields. Keep diagnostic output separate from protocol responses.

**App Lab:** import the release ZIP and run **Laya Q**. Its Python process keeps the model loaded and exposes `POST /predict` and `GET /health` on port 8765. The host CLI creates a temporary ADB forward and removes it after use.

```powershell
python laya_q.py predict examples/triage.json --app-lab
```

Use `--app-lab` while the app is running. Stop the App Lab inference app before running a separate direct worker to avoid holding two model instances in board memory. The API has no authentication and its port is also exposed on the board's network interface; preserve accurate documentation of this behavior.

Both transports accept a JSON object containing `state` (string, object, or list) and a nonempty `questions` object. Preserve request validation and Laya's prediction result structure. Serialize App Lab inference with its existing lock.

## Matrix and board operations

- Keep the `laya_status` RPC contract synchronized across Python and the sketch: 0 idle, 1 receiving, 2 working, 3 success, 4 error.
- Current visuals are a beating heart, incoming arrow, scanning line, check, and flashing X respectively. Editable icon rows must have 13 columns and 8 rows.
- Matrix animation runs on the STM32. Keep updates responsive; avoid long blocking delays in the sketch.
- `Arduino_LED_Matrix` comes with the tested `arduino:zephyr` platform. Adding it as a separately installed library caused App Lab library resolution failures.
- Discover the board with ADB; do not hardcode a developer's device serial. `--serial` belongs before the CLI subcommand. `find_adb()` can locate App Lab's bundled ADB on Windows.
- Check `arduino-app-cli app list` and relevant command help before deployment. App IDs depend on import names; do not assume a particular app ID or overwrite unrelated apps.
- Flash, restart, or install on the connected board when needed for the requested task. Explain which app is affected. Documentation-only changes do not need board deployment.
- Put large downloads, environments, and caches under `/home/arduino`, which has a separate partition. Check free space before large installs; avoid filling the smaller root partition.

## Dependency and checkpoint constraints

- Host scripts and CI require Python 3.11+ and use the standard library. Local tests do not require Laya, PyTorch, or an attached board.
- Keep CPU PyTorch pinned to `2.9.1+cpu` and Laya to `0.3.20` unless a deliberate upgrade is verified on hardware. PyTorch 2.10 produced an illegal-instruction crash on the tested UNO Q.
- The direct installer uses `venv --without-pip` and official `get-pip.py` because the board image may lack Debian's venv package.
- Hugging Face Xet downloads stalled on the tested board. Preserve `HF_HUB_DISABLE_XET=1` and the host-download option unless a replacement is verified.
- Keep checkpoint revision and weight SHA256 consistent in `laya_q.py`, `scripts/build_app_lab.py`, App Lab `main.py`, and documentation. Verify downloaded or assembled weights before loading them.
- App Lab rejected the full weight file during ZIP import. The builder stores it as **8 MiB parts**; App Lab assembles and verifies them in `.cache/model` on first run. Preserve ordered streaming assembly and atomic publication of the verified file.
- The tested checkpoint warns about invalid calibration temperatures. Treat affected confidence values as uncalibrated; do not describe them as guaranteed calibrated probabilities.

## Secrets, packaging, and releases

- Never put Hugging Face tokens, passwords, or personal credentials in source, Git, logs, examples, ZIPs, or board credential files. Do not repeat a supplied token in messages or command arguments.
- The pinned model is public; ordinary downloads and release builds need no Hugging Face token. If authentication is required, preserve the CLI's temporary stdin-based token flow.
- Keep weights, generated ZIPs, `.build`, environments, and caches out of Git. Do not add personal request data to bundles.
- The builder includes explicit file allowlists, not the entire working directory. Update those lists intentionally when release contents change.
- The bundle includes the upstream model's Apache 2.0 license. Keep its attribution and license when changing packaging.
- Build with `python scripts/build_app_lab.py Laya-Q-App-Lab.zip`. To reuse verified local weights, add `--weights-file <path>`; metadata and license downloads still require network access.
- The release workflow publishes the ZIP when a `v*` tag is pushed, using GitHub's built-in token. Make commits, pushes, tags, and releases only as requested by the user; preserve unrelated working changes.

## Verification and reporting

Run from the repository root for relevant Python changes:

```powershell
python -m unittest discover -s tests -v
python -m compileall -q laya_q.py board_worker.py status_bridge.py app_lab/laya_status/python/main.py scripts/build_app_lab.py
```

Use tests that check observable protocol behavior, error handling, or integrity checks. Documentation-only edits need a review for accuracy, not model downloads or board tests.

For hardware or deployment changes, verify the affected sketch compiles and uploads. For inference changes, use the example request on the intended backend and inspect app logs. Historical checks succeeded for App Lab import, matrix compilation/flashing, and USB prediction returning `billing`; this is not evidence that new changes have passed.

Report what changed, what was actually tested, and what remains local versus deployed or published. Do not claim visual confirmation of physical LEDs without observing them or receiving user confirmation.
