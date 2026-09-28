# Laya Q

Import the release ZIP into Arduino App Lab and run this app on a 4 GB UNO Q. Linux runs Laya; the STM32 drives the built-in 8×13 blue LED matrix. The default release contains the app and computer-side tools; model files stay in the hidden app cache.

- Beating heart: ready
- Moving arrow: receiving a request
- Scanning line: loading or inference
- Check: result sent
- Flashing X: error

Before running the app, download the current model on your computer and transfer it over USB:

```powershell
python tools/laya_q.py setup --app-lab user:laya-q-app-lab
```

Use your actual imported app ID. The host installs the original `model.safetensors` and its required tokenizer/configuration files in `.cache/model`. No fixed model revision or hash needs editing when upstream weights change. Run this command again while the app is stopped to update the installed model.

The first run installs CPU PyTorch 2.9.1 and Laya 0.3.20, so the board needs internet access for Python dependencies. Model downloads always happen on the computer. If the model is missing, the app displays installation instructions instead of downloading it on the UNO Q. Allow several GB for weights and dependencies. Subsequent starts use the cached model, and predictions keep it loaded until you stop the app. Optional offline bundles include model pieces to work around App Lab's 100 MiB limit on imported files.

From the computer, use the included host tools (or the repository):

```powershell
python tools/laya_q.py predict tools/examples/triage.json --app-lab
```

The host creates a temporary ADB USB forward to port 8765. You can also use `POST /predict` with a JSON object containing `state` and `questions`, and `GET /health`. This local API has no authentication and is exposed on the board's network interface.

To test in Chrome or another browser, run `python tools/laya_q.py portal` on your computer. Select the USB board and connect in the local web portal. Python handles the existing ADB USB connection; no direct browser WebUSB driver is required.

Model: [convaiinnovations/laya](https://huggingface.co/convaiinnovations/laya). Each new download selects the latest revision once, keeping weights and support files consistent. Verification metadata is obtained or generated during download, rather than fixed in project code. No Hugging Face token is included in the app.

The upstream model is distributed under Apache 2.0. Bundles that include weights also include its license at `model/LICENSE`. Python dependencies retain their own licenses and are installed by App Lab.

The `laya_status` RPC accepts 0 (idle), 1 (receiving), 2 (working), 3 (success), and 4 (error). Edit the sketch's 13-column icon rows to change the visual design.
