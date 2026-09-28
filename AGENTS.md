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
| `model_download.py` | Current Hub revision resolution, snapshot downloads, dynamic verification, and cache completion checks |
| `web_portal.py`, `portal/` | Loopback web testing portal, device selection, and browser assets |
| `board_worker.py` | Direct Linux worker: loads Laya and handles JSON-lines requests |
| `laya_runtime.py` | Shared offline CPU loader, INT8 encoder conversion, warmup and FP32 fallback |
| `status_bridge.py` | Direct worker's MessagePack RPC client for STM32 status |
| `app_lab/laya_status/app.yaml` | App Lab manifest for the full **Laya Q** app |
| `app_lab/laya_status/python/main.py` | Persistent App Lab inference service and bundled checkpoint assembly |
| `app_lab/laya_status/python/requirements.txt` | App Lab Python dependencies |
| `app_lab/laya_status/sketch/` | STM32 matrix animations and Bridge RPC |
| `scripts/build_app_lab.py` | Public model download, checksum verification, and App Lab ZIP packaging |
| `examples/triage.json` | Example request used for board smoke checks |
| `tests/` | Host protocol, HTTP API, and checkpoint assembly tests |
| `.github/workflows/` | CI builds on main/PRs; automatic releases on main, version tags, or manual dispatch |

The source folder name `laya_status` is historical: it now contains the full inference app, not just a status companion.

## Two runtime modes

**Direct worker:** `setup` installs code and a private virtual environment under `/home/arduino/laya-q`. `predict` starts the worker through an ADB shell and keeps it loaded for that invocation's requests.

```powershell
python laya_q.py setup --download-on-host
python laya_q.py predict examples/triage.json
python laya_q.py predict requests.jsonl --jsonl
```

Host checkpoint downloads are mandatory. Verify downloads against current Hub metadata and compare transferred files with the computer's freshly computed digests. Publish a completion manifest after all files are installed. `--skip-warmup` skips loading after setup and still transfers weights.

The worker emits exactly one `LAYA_Q_RESPONSE `-prefixed JSON response per request. Preserve this framing and the `ok`, `result`, and `error` fields. Keep diagnostic output separate from protocol responses.

**App Lab:** import the release ZIP and run **Laya Q**. Its Python process keeps the model loaded and exposes `POST /predict` and `GET /health` on port 8765. The host CLI creates a temporary ADB forward and removes it after use.

The default ZIP contains code only. `python laya_q.py setup --app-lab <APP_ID>` downloads the latest model on the computer and transfers its original safetensors file and support files into the imported app's `.cache/model`. Missing models must produce setup instructions, never a board download. Stop the app before updating its cache, then restart it. Cached models do not update automatically on every boot.

```powershell
python laya_q.py predict examples/triage.json --app-lab
```

Use `--app-lab` while the app is running. Stop the App Lab inference app before running a separate direct worker to avoid holding two model instances in board memory. The API has no authentication and its port is also exposed on the board's network interface; preserve accurate documentation of this behavior.

Both transports accept a JSON object containing `state` (string, object, or list) and a nonempty `questions` object. Preserve request validation and Laya's prediction result structure. Serialize App Lab inference with its existing lock.

**Browser testing:** `python laya_q.py portal` opens a loopback-only web portal. `AppLabConnection` is shared by the CLI and portal; close its ADB forward when disconnecting or shutting down. The portal uses Python ADB, not native browser WebUSB. Keep its Host/Origin checks, JSON-only mutation endpoints, and local bind. Serve browser assets locally without CDN dependencies. No model runs in the browser or host portal.

## Matrix and board operations

- Keep the `laya_status` RPC contract synchronized across Python and the sketch: 0 idle, 1 receiving, 2 working, 3 success, 4 error.
- Current visuals are a filled heart with an eased double beat, incoming arrow, scanning line, check, and flashing X respectively. Editable icon rows must have 13 columns and 8 rows.
- The matrix uses 3-bit grayscale (0 to 7). Keep ordinary status pixels at 7; idle blends three heart sizes at roughly 30 frames per second.
- Matrix animation runs on the STM32. Keep updates responsive; avoid long blocking delays in the sketch.
- `Arduino_LED_Matrix` comes with the tested `arduino:zephyr` platform. Adding it as a separately installed library caused App Lab library resolution failures.
- Discover the board with ADB; do not hardcode a developer's device serial. `--serial` belongs before the CLI subcommand. `find_adb()` can locate App Lab's bundled ADB on Windows.
- Check `arduino-app-cli app list` and relevant command help before deployment. App IDs depend on import names; do not assume a particular app ID or overwrite unrelated apps.
- Flash, restart, or install on the connected board when needed for the requested task. Explain which app is affected. Documentation-only changes do not need board deployment.
- Put large downloads, environments, and caches under `/home/arduino`, which has a separate partition. Check free space before large installs; avoid filling the smaller root partition.

## Dependency and checkpoint constraints

- Host scripts and CI require Python 3.11+ and use the standard library. Local tests do not require Laya, PyTorch, or an attached board.
- Keep CPU PyTorch pinned to `2.14.0+cpu` and Laya to `0.3.20` unless a deliberate upgrade is verified on hardware. The official Python 3.13 ARM64 CPU wheel of 2.14 passed full-model inference on the tested UNO Q. Version 2.10 previously crashed with an illegal instruction; 2.9.1 remains the tested rollback version. Use the official CPU index, not a CUDA build. See `docs/uno-q-performance.md`: the version upgrade alone did not improve speed.
- Both runtimes use `laya_runtime.load_cpu_agent`: four intra-op threads, one inter-op thread, QNNPACK dynamic INT8 on encoder Linear layers only; decision layers remain FP32. The user requested INT8 as the default. Warm it with synthetic text before accepting traffic. Keep original checkpoint files intact. `LAYA_PRECISION=fp32` or the helper's `DEFAULT_PRECISION` enables fallback. App Lab health reports runtime settings. Never silently fall back if quantization fails. Quantization may affect outputs; the synthetic shipping test is not a broad accuracy guarantee.
- The builder copies the root `laya_runtime.py` into `python/` and `tools/`; the direct installer transfers it alongside the worker. Keep these paths synchronized. Legacy `torch.ao` quantization still works in 2.14 but emits deprecation warnings; future upgrades must check the actual model, not only import success.
- The direct installer uses `venv --without-pip` and official `get-pip.py` because the board image may lack Debian's venv package.
- Model downloads on the board are slow. Keep them on the computer, with offline Hugging Face/Transformers loading enforced in both board runtimes. Do not reintroduce a network fallback for missing model files.
- Do not hardcode model revisions or checkpoint hashes. `model_download.py` resolves the current upstream commit once per download and retrieves matching files. Digests in generated manifests are per-download verification data, not permanent source constants. Future weights should not require source edits merely because their hashes changed.
- The original `.safetensors` contains weights only; Laya requires tokenizer/configuration support files. Keep these in the hidden app cache. The default bundle contains no model directory or parts. The builder copies the shared download helper into both `python/` and `tools/`; do not maintain divergent copies.
- App Lab limits individual imported files to 100 MiB. Only the optional `--include-model` offline bundle uses 8 MiB pieces, with dynamically generated verification metadata. Preserve its ordered assembly and completion marker checks.
- The tested checkpoint warns about invalid calibration temperatures. Treat affected confidence values as uncalibrated; do not describe them as guaranteed calibrated probabilities.

## Secrets, packaging, and releases

- Never put Hugging Face tokens, passwords, or personal credentials in source, Git, logs, examples, ZIPs, or board credential files. Do not repeat a supplied token in messages or command arguments.
- The model is public; ordinary downloads and release builds need no Hugging Face token. `setup --hf-token` uses a masked Python prompt; interactive host downloads can prompt after authentication or rate-limit responses. Preserve `--hf-token-stdin` for automation. Never fall back to echoing a secret when masked input is unavailable.
- Keep weights, generated ZIPs, `.build`, environments, and caches out of Git. Do not add personal request data to bundles.
- The builder includes explicit file allowlists, not the entire working directory. Update those lists intentionally when release contents change.
- Bundles containing weights include the upstream model's Apache 2.0 license. Keep its attribution and license when changing packaging.
- Build the small default ZIP with `python scripts/build_app_lab.py Laya-Q-App-Lab.zip`. Use `--include-model` for an offline model bundle. `--weights-file <path>` also selects an offline bundle and checks those weights against current Hub metadata; metadata and license downloads still require network access.
- The release workflow tests, builds, and publishes the small ZIP on pushes to `main`, pushes of `v*` tags, and manual dispatch on main or a version tag. Main releases use `build-<run-number>-<short-sha>` tags and target the exact tested commit. CI also saves build artifacts for PR review. Use GitHub's built-in token, preserve the test gate, and do not replace published assets on reruns. Pushing main now publishes a release automatically. Make commits, pushes, tags, and releases only as requested by the user; preserve unrelated working changes.

## Verification and reporting

Run from the repository root for relevant Python changes:

```powershell
python -m unittest discover -s tests -v
python -m compileall -q laya_q.py model_download.py laya_runtime.py web_portal.py board_worker.py status_bridge.py app_lab/laya_status/python/main.py scripts/build_app_lab.py
```

Use tests that check observable protocol behavior, error handling, or integrity checks. Documentation-only edits need a review for accuracy, not model downloads or board tests.

For hardware or deployment changes, verify the affected sketch compiles and uploads. For inference changes, use the example request on the intended backend and inspect app logs. Historical checks succeeded for App Lab import, matrix compilation/flashing, and USB prediction returning `billing`; this is not evidence that new changes have passed.

Report what changed, what was actually tested, and what remains local versus deployed or published. Do not claim visual confirmation of physical LEDs without observing them or receiving user confirmation.
