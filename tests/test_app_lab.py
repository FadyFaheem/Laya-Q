import hashlib
import importlib.util
import json
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import MagicMock, patch
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from model_download import MANIFEST


def load_app():
    spec = importlib.util.spec_from_file_location("laya_app", "app_lab/laya_status/python/main.py")
    module = importlib.util.module_from_spec(spec)
    with patch.dict("sys.modules", {"arduino": MagicMock(), "arduino.app_utils": MagicMock()}):
        spec.loader.exec_module(module)
    return module


class AppLabTests(unittest.TestCase):
    def test_split_checkpoint_assembly_and_checksum(self):
        app = load_app()
        with tempfile.TemporaryDirectory(dir=".") as folder:
            root = Path(folder)
            app.SOURCE_MODEL = root / "source"
            app.MODEL = root / "assembled"
            parts = app.SOURCE_MODEL / "parts"
            parts.mkdir(parents=True)
            (parts / "0000.bin").write_bytes(b"first")
            (parts / "0001.bin").write_bytes(b"second")
            for filename in ("rl_agent_config.json", "encoder/config.json",
                             "tokenizer/tokenizer_config.json", "tokenizer/tokenizer.json"):
                path = app.SOURCE_MODEL / filename
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text("{}")
            manifest = {"revision": "test", "files": [
                {"path": "model.safetensors", "size": 11, "sha256": hashlib.sha256(b"firstsecond").hexdigest()}]}
            for path in app.SOURCE_MODEL.rglob("*.json"):
                manifest["files"].append({"path": path.relative_to(app.SOURCE_MODEL).as_posix(),
                                          "size": path.stat().st_size, "sha256": hashlib.sha256(path.read_bytes()).hexdigest()})
            (app.SOURCE_MODEL / MANIFEST).write_text(json.dumps(manifest))
            app.prepare_model()
            self.assertEqual((app.MODEL / "model.safetensors").read_bytes(), b"firstsecond")
            (app.MODEL / "model.safetensors").unlink()
            (parts / "0001.bin").write_bytes(b"corrupted")
            with self.assertRaisesRegex(ValueError, "checksum"):
                app.prepare_model()
            self.assertFalse((app.MODEL / "model.safetensors").exists())

    def test_missing_cache_requires_host_installation_without_network(self):
        app = load_app()
        with tempfile.TemporaryDirectory() as folder:
            app.SOURCE_MODEL = Path(folder) / "no-bundled-model"
            app.MODEL = Path(folder) / "cache"
            with patch("model_download.urlopen") as network:
                with self.assertRaisesRegex(FileNotFoundError, "On your computer"):
                    app.prepare_model()
                network.assert_not_called()
            with patch.object(app, "cache_complete", return_value=True), patch("model_download.urlopen") as network:
                app.prepare_model()
                network.assert_not_called()

    def test_http_prediction_and_bad_request(self):
        app = load_app()
        app.AGENT = MagicMock()
        app.AGENT.laya_q_runtime = {"precision": "int8", "torch": "2.14.0+cpu"}
        app.AGENT.predict.return_value = {"answers": {"department": "billing"}}
        app.status = MagicMock()
        server = app.ThreadingHTTPServer(("127.0.0.1", 0), app.Handler)
        thread = threading.Thread(target=server.serve_forever)
        thread.start()
        try:
            endpoint = f"http://127.0.0.1:{server.server_port}/predict"
            with urlopen(f"http://127.0.0.1:{server.server_port}/health") as response:
                health = json.load(response)
                self.assertTrue(health["ready"])
                self.assertEqual(health["runtime"]["precision"], "int8")
            request = Request(endpoint, data=json.dumps({"state": "refund", "questions": {"q": {}}}).encode())
            with urlopen(request) as response:
                self.assertEqual(json.load(response)["answers"]["department"], "billing")
            with self.assertRaises(HTTPError) as failure:
                urlopen(Request(endpoint, data=b"{}"))
            self.assertEqual(failure.exception.code, 400)
            failure.exception.close()
            app.AGENT.predict.assert_called_once_with("refund", {"q": {}})
        finally:
            server.shutdown()
            thread.join()
            server.server_close()
