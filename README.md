# Laya on Arduino UNO Q over USB

This project runs the [Laya English checkpoint](https://huggingface.co/convaiinnovations/laya) on the UNO Q's **Linux processor**. Your computer sends requests and receives results over USB using ADB. The STM32 drives the onboard **8×13 LED matrix** to show request status.

Laya answers typed `choice`, `score`, and yes/no questions about a supplied state. It is not a chat text generator. This starter uses the English checkpoint in CPU mode. A UNO Q with 4 GB RAM is recommended; inference speed on this board has not been benchmarked.

## Requirements

- Arduino UNO Q connected to the computer with a USB **data** cable and configured through Arduino App Lab.
- Python 3.11+ on the computer. The host script uses only Python's standard library.
- ADB on `PATH`, or Arduino App Lab's bundled ADB on Windows. The host script finds the latter automatically.
- Internet access from the **board** during setup to install Python packages and download the checkpoint. Later requests use the cached model.
- Several GB free in `/home/arduino`. The virtual environment, package cache, and checkpoint are stored there, not in the smaller root partition.

App Lab itself opens a USB board shell with its bundled `adb -s <serial> shell`. This tool uses the same connection. `adb devices` must show the board with status `device`.

## Set up

From this repository on the computer:

```powershell
python laya_q.py setup
```

For a faster checkpoint download, use the computer's connection and transfer it over USB:

```powershell
python laya_q.py setup --download-on-host
```

If more than one ADB device is attached, supply `--serial` before the subcommand:

```powershell
python laya_q.py --serial 116087906 setup
```

Setup copies `board_worker.py` to `/home/arduino/laya-q`, creates a private virtual environment, installs CPU-only PyTorch 2.9.1 and `laya==0.3.20`, and loads the checkpoint once to populate the Hugging Face cache. The first setup may take a while. The script downloads the official `get-pip.py` bootstrap into that virtual environment because the stock UNO Q Python image may lack Debian's `python3.13-venv` package. PyTorch 2.10 crashed with an illegal instruction on the tested UNO Q, so the installer pins 2.9.1. The worker disables the Hugging Face Xet downloader because it stalled on this board connection.

To install packages first and defer the checkpoint download until the first prediction, run `python laya_q.py setup --skip-warmup`.

If the Hub asks for authentication or applies a download limit, pass a token through standard input. It is held only for that setup process and is not written to this repository or a board credential file:

```powershell
Read-Host "Hugging Face token" | python laya_q.py setup --hf-token-stdin
```

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

Download `Laya-Q-App-Lab.zip` from a GitHub release, import it in App Lab, and run **Laya Q**. The ZIP contains the App Lab Python service, STM32 sketch, English checkpoint, example request, and host tools. App Lab installs pinned Python dependencies on the first run, which requires internet access; model inference then uses the included checkpoint. Allow several GB of free storage and use the tested 4 GB UNO Q configuration.

App Lab limits individual imported file sizes, so the checkpoint is stored as 8 MB pieces. The first run assembles and verifies it in the app cache. The matrix shows a beating heart when ready, an incoming arrow for requests, a scanning animation during inference, a check for returned results, and a flashing X for errors.

Use the imported app's persistent model through USB:

```powershell
python laya_q.py predict examples/triage.json --app-lab
```

This creates and removes an ADB port forward automatically. The app also exposes `POST /predict` and `GET /health` on port 8765. The API is intended for your local board connection and has no authentication; the port is also exposed on the board's network interface.

Use `--app-lab` while the App Lab app is running. Stop that app before using the direct worker mode so the board only holds one model in memory.

## Build and automatic releases

```powershell
python scripts/build_app_lab.py Laya-Q-App-Lab.zip
```

The builder downloads a fixed public model revision, verifies the weights' SHA256, and includes only an explicit list of project files. It needs no Hugging Face token. Model weights and generated ZIPs are ignored by Git.

CI runs on pushes to `main` and pull requests. The release workflow publishes `Laya-Q-App-Lab.zip` when a version tag such as `v0.1.0` is pushed. It uses GitHub's built-in workflow token.

Sources: [Arduino UNO Q user manual](https://docs.arduino.cc/tutorials/uno-q/user-manual/), [Arduino App Lab shell implementation](https://github.com/arduino/arduino-app-lab/blob/al-0.5.0/standalone-apps/app-lab-desktop/internal/terminal/terminal.go), [Laya model card](https://huggingface.co/convaiinnovations/laya).
