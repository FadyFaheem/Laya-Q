# Laya on Arduino UNO Q over USB

This project runs the [Laya English checkpoint](https://huggingface.co/convaiinnovations/laya) on the UNO Q's **Linux processor**. Your computer sends requests and receives results over USB using ADB. The STM32 drives the onboard **8×13 LED matrix** to show request status.

Laya answers typed `choice`, `score`, and yes/no questions about a supplied state. It is not a chat text generator. This starter uses the English checkpoint in CPU mode. A UNO Q with 4 GB RAM is recommended; inference speed on this board has not been benchmarked.

## Requirements

- Arduino UNO Q connected to the computer with a USB **data** cable and configured through Arduino App Lab.
- Python 3.11+ on the computer. The host script uses only Python's standard library.
- ADB on `PATH`, or Arduino App Lab's bundled ADB on Windows. The host script finds the latter automatically.
- Internet access from the **board** to install Python packages and from the **computer** to download the checkpoint during setup. Later requests use the installed model.
- Several GB free in `/home/arduino`. The virtual environment, package cache, and checkpoint are stored there, not in the smaller root partition.

App Lab itself opens a USB board shell with its bundled `adb -s <serial> shell`. This tool uses the same connection. `adb devices` must show the board with status `device`.

## Set up

From this repository on the computer:

```powershell
python laya_q.py setup
```

Setup downloads the current checkpoint on your computer by default, transfers it over USB, and verifies the board's copy before installing it. There is no hardcoded model revision or checksum: each download resolves the latest upstream revision once and reads its verification data from the Hub. `--download-on-host` remains available as an explicit option:

```powershell
python laya_q.py setup --download-on-host
```

If more than one ADB device is attached, supply `--serial` before the subcommand:

```powershell
python laya_q.py --serial 116087906 setup
```

Setup copies the worker to `/home/arduino/laya-q`, creates a private virtual environment, installs CPU-only PyTorch 2.9.1 and `laya==0.3.20`, and loads the transferred checkpoint from `/home/arduino/laya-q/model`. Python dependencies are installed on the board; model downloads always use your computer's connection. The first setup may take a while. The script downloads the official `get-pip.py` bootstrap into that virtual environment because the stock UNO Q Python image may lack Debian's `python3.13-venv` package. PyTorch 2.10 crashed with an illegal instruction on the tested UNO Q, so the installer pins 2.9.1. Board model loading is forced offline to prevent slow fallback downloads.

To transfer the checkpoint without loading it immediately, run `python laya_q.py setup --skip-warmup`. If the checkpoint is missing, the worker asks you to install it from the computer; it never downloads a model on the UNO Q.

For authentication, ask Python to prompt for your token with hidden input. The token stays in memory for this setup and is not saved to Git, the project, or a board credential file:

```powershell
python laya_q.py setup --hf-token
```

During an interactive host download, the script also prompts privately if the Hub returns an authentication or rate-limit response. `--hf-token-stdin` remains supported for automation. The public checkpoint normally needs no token; entering a token does not guarantee that every rate limit will be lifted.

## Predict

```powershell
python laya_q.py predict examples/triage.json
```

The command prints one JSON result. Pass `-` to read from standard input. For multiple requests, put one JSON object per line in a file and run:

```powershell
python laya_q.py predict requests.jsonl --jsonl
```

The board worker stays loaded for all requests in that invocation. Each request has this shape:

```json
{
  "state": "I was charged twice. Please refund the duplicate payment.",
  "questions": {
    "department": {
      "type": "choice",
      "instructions": "Which team should handle this?",
      "criteria": {
        "billing": "invoices, payments, refunds",
        "technical": "bugs and outages"
      }
    }
  }
}
```

The output is Laya's full prediction result, including `answers`. No model inference runs on the computer. The first request in each command loads the checkpoint into board memory, so it is slower than subsequent requests in the same invocation.

The tested checkpoint reports invalid calibration temperatures and clamps them at load time. Treat its confidence values as uncalibrated.

## Connection checks

On Windows, if `adb` is not on `PATH`, App Lab commonly installs it under `%LOCALAPPDATA%\Arduino15\packages\arduino\tools\adb\<version>\adb.exe`. Check the board with that executable's `devices -l` command. If you see `unauthorized` or no device, reconnect the USB data cable and make sure App Lab can open the board shell.

The board runs Debian Linux on a Qualcomm processor. ADB over USB is separate from the Arduino IDE's serial monitor and separate from Wi-Fi SSH. Inference requests and results go through USB ADB.

## Arduino App Lab bundle

Download `Laya-Q-App-Lab.zip` from a GitHub release and import it in App Lab. The default ZIP contains the Python service, STM32 sketch, example request, and host tools. Model files live in the app's hidden `.cache/model` directory, keeping them out of the editable project. Allow several GB of free storage and use the tested 4 GB UNO Q configuration.

Install the model from your computer after importing the ZIP and before running the app:

```powershell
python laya_q.py setup --app-lab user:laya-q-app-lab
```

Replace the app ID with the imported app's ID if App Lab gives it a different name. This downloads the latest model on the computer and transfers the original `model.safetensors` plus matching support files into the app cache. It does not install a second Python runtime. Run or restart **Laya Q** in App Lab afterward. Add `--hf-token` if authentication is needed.

If you skip host installation, the app reports that the model is missing and displays the setup command. It never starts a model download on the UNO Q. Subsequent starts reuse the installed snapshot; run the setup command again while the app is stopped to update it. App Lab installs pinned Python dependencies on first run, which still requires board internet access.

The original safetensors file contains only weights. Laya also requires its tokenizer and configuration files, so these are kept together in the cache. The default ZIP contains no model pieces or tokenizer folders. A fully offline model bundle remains available with `--include-model`; only that optional format splits the weights because [App Lab limits imported files to 100 MiB](https://github.com/arduino/arduino-app-cli/blob/main/internal/orchestrator/archive.go).

The matrix shows a filled heart that expands and contracts with a soft double beat when ready, an incoming arrow for requests, a scanning animation during inference, a check for returned results, and a flashing X for errors.

Use the imported app's persistent model through USB:

```powershell
python laya_q.py predict examples/triage.json --app-lab
```

This creates and removes an ADB port forward automatically. The app also exposes `POST /predict` and `GET /health` on port 8765. The API is intended for your local board connection and has no authentication; the port is also exposed on the board's network interface.

Use `--app-lab` while the App Lab app is running. Stop that app before using the direct worker mode so the board only holds one model in memory.

## Local web testing portal

Run **Laya Q** in App Lab, then start the portal on your computer:

```powershell
python laya_q.py portal
```

The script opens `http://127.0.0.1:8080` in your browser. Select your USB board, click **Connect over USB**, load the example or edit the state and questions, then send the request. The portal displays typed answers, full JSON results, and elapsed time. The model remains on the UNO Q, and its matrix shows request activity.

Use `--port 8081` if port 8080 is occupied, or `--no-browser` to open the printed URL yourself. The portal binds only to your computer's loopback interface and needs no additional Python packages. Release bundles include it under `tools/`; use `python tools/laya_q.py portal` there.

Chrome works with this portal through the Python ADB connection. Direct browser WebUSB is not implemented: it would need a browser-side ADB client, compatible USB drivers, and exclusive access to the interface. The current portal can use the existing App Lab USB connection without taking over that interface. See [Chrome's WebUSB documentation](https://developer.chrome.com/docs/capabilities/usb) for browser interface requirements.

## Build and automatic releases

```powershell
python scripts/build_app_lab.py Laya-Q-App-Lab.zip
```

The default build is small and needs no model download. For a bundle with an offline model payload:

```powershell
python scripts/build_app_lab.py Laya-Q-Offline-App-Lab.zip --include-model
```

The offline builder resolves the current public model revision, downloads its matching support files, and generates verification metadata for that bundle. No checkpoint hash is fixed in source code. `--weights-file <path>` can reuse existing weights if they match the current Hub revision. The builder includes only an explicit list of project files. Model weights and generated ZIPs are ignored by Git. An upstream change to the model's architecture or format may still require a compatible Laya runtime update.

CI runs Python checks and tests, builds the small App Lab ZIP, and saves it as a downloadable Actions artifact on pushes to `main` and pull requests.

The release workflow automatically tests, builds, and publishes `Laya-Q-App-Lab.zip` on pushes to `main`. Automatic releases use tags such as `build-12-abc1234`, identifying the workflow run and source commit. You can also push a version tag such as `v0.1.0`, or open **Actions > Release App Lab bundle > Run workflow** on `main`. Failed tests or builds prevent publication. Rerunning a completed release leaves its published assets unchanged.

Get the ZIP from the [latest release](https://github.com/FadyFaheem/Laya-Q/releases/latest). Releases contain no model weights or credentials; model installation still downloads on the computer and transfers over USB. Publishing uses GitHub's built-in workflow token, so no personal or Hugging Face secret is required. App Lab compiles the included STM32 sketch when you run the imported app.

Sources: [Arduino UNO Q user manual](https://docs.arduino.cc/tutorials/uno-q/user-manual/), [Arduino App Lab shell implementation](https://github.com/arduino/arduino-app-lab/blob/al-0.5.0/standalone-apps/app-lab-desktop/internal/terminal/terminal.go), [Laya model card](https://huggingface.co/convaiinnovations/laya).
