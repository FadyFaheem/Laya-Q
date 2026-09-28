# Laya Q

Import the release ZIP into Arduino App Lab and run this app on a 4 GB UNO Q. Linux runs Laya; the STM32 drives the built-in 8×13 blue LED matrix. The release includes the English checkpoint and computer-side tools.

- Beating heart: ready
- Moving arrow: receiving a request
- Scanning line: loading or inference
- Check: result sent
- Flashing X: error

The first run installs CPU PyTorch 2.9.1 and Laya 0.3.20, so the board needs internet access. It assembles the bundled 8 MB checkpoint pieces and checks their SHA256. This takes extra time once and uses about 1.6 GB for the checkpoint pieces plus assembled weights; dependencies use additional storage. Subsequent predictions keep the model loaded until you stop the app.

From the computer, use the included host tools (or the repository):

```powershell
python tools/laya_q.py predict tools/examples/triage.json --app-lab
```

The host creates a temporary ADB USB forward to port 8765. You can also use `POST /predict` with a JSON object containing `state` and `questions`, and `GET /health`. This local API has no authentication and is exposed on the board's network interface.

To test in Chrome or another browser, run `python tools/laya_q.py portal` on your computer. Select the USB board and connect in the local web portal. Python handles the existing ADB USB connection; no direct browser WebUSB driver is required.

Model: [convaiinnovations/laya](https://huggingface.co/convaiinnovations/laya), revision `55cf4c4ebb4ebe31b2550e8bdf3bd21b99753851`. No Hugging Face token is included or required to load the bundled checkpoint.

The upstream model is distributed under Apache 2.0. The release includes its license at `model/LICENSE`. Python dependencies retain their own licenses and are installed by App Lab.

The `laya_status` RPC accepts 0 (idle), 1 (receiving), 2 (working), 3 (success), and 4 (error). Edit the sketch's 13-column icon rows to change the visual design.
