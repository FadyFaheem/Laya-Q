import hashlib
import io
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch
from urllib.error import HTTPError

import laya_q
import model_download


class HubFixture:
    def __init__(self, revision="a" * 40, weights=b"test checkpoint"):
        self.revision = revision
        self.files = {"rl_agent_config.json": b"{}", "model.safetensors": weights,
                      "tokenizer/additional.json": b"{}"}
        self.info = {"sha": revision, "siblings": [
            {"rfilename": name, "size": len(data), "lfs": {"sha256": hashlib.sha256(data).hexdigest()}}
            for name, data in self.files.items()]}
        self.urls = []

    def open(self, request, **kwargs):
        url = request if isinstance(request, str) else request.full_url
        self.urls.append(url)
        if "/api/models/" in url:
            return io.BytesIO(json.dumps(self.info).encode())
        name = url.split(f"/resolve/{self.revision}/")[1]
        return io.BytesIO(self.files[name])

    def verify_board(self, command, **kwargs):
        remote = command[-1].split("sha256sum ", 1)[1].removesuffix(".partial")
        name = next(name for name in self.files if remote.endswith("/" + name))
        return subprocess.CompletedProcess(command, 0, hashlib.sha256(self.files[name]).hexdigest() + "  file\n")


class SetupTests(unittest.TestCase):
    def test_downloads_current_snapshot_and_checks_board_before_publish(self):
        hub = HubFixture()
        transfers = []

        def adb(serial, *args):
            if args[0] == "push":
                if not args[2].endswith(model_download.MANIFEST + ".partial"):
                    name = next(name for name in hub.files if args[2].endswith("/" + name + ".partial"))
                    self.assertEqual(Path(args[1]).read_bytes(), hub.files[name])
                transfers.append(args[2])

        with patch.object(laya_q, "urlopen", side_effect=hub.open), \
             patch.object(laya_q, "adb_run", side_effect=adb) as adb_call, \
             patch.object(laya_q, "adb_base", return_value=["adb"]), \
             patch.object(laya_q.subprocess, "run", side_effect=hub.verify_board) as verify:
            laya_q.download_model_on_host("test-board", None)
        self.assertEqual(verify.call_count, len(hub.files))
        self.assertIn(laya_q.BOARD_MODEL + "/model.safetensors.partial", transfers)
        self.assertIn(model_download.MANIFEST, adb_call.call_args.args[-1])
        self.assertTrue(all(f"/resolve/{hub.revision}/" in url for url in hub.urls[1:]))

    def test_new_upstream_weights_need_no_source_hash_change(self):
        with tempfile.TemporaryDirectory() as folder:
            for revision, weights in (("a" * 40, b"version1"), ("b" * 40, b"version2")):
                hub = HubFixture(revision, weights)
                manifest = model_download.download_snapshot(folder, open_remote=hub.open)
                self.assertEqual(manifest["revision"], revision)
                self.assertEqual((Path(folder) / "model.safetensors").read_bytes(), weights)
                self.assertTrue(model_download.cache_complete(folder))

    def test_corrupt_download_is_not_transferred(self):
        hub = HubFixture()
        hub.info["siblings"][1]["lfs"]["sha256"] = "0" * 64
        with patch.object(laya_q, "urlopen", side_effect=hub.open), patch.object(laya_q, "adb_run") as adb:
            with self.assertRaisesRegex(laya_q.ToolError, "checksum"):
                laya_q.download_model_on_host("test-board", None)
            adb.assert_not_called()

    def test_corrupt_board_copy_is_not_published(self):
        hub = HubFixture()
        with patch.object(laya_q, "urlopen", side_effect=hub.open), \
             patch.object(laya_q, "adb_run") as adb, \
             patch.object(laya_q, "adb_base", return_value=["adb"]), \
             patch.object(laya_q.subprocess, "run", return_value=subprocess.CompletedProcess([], 0, "wrong  file\n")):
            with self.assertRaisesRegex(laya_q.ToolError, "checksum"):
                laya_q.download_model_on_host("test-board", None)
            self.assertFalse(any(call.args[-1].startswith("mv ") for call in adb.call_args_list))

    def test_private_prompt_and_host_download_are_cli_options(self):
        with patch.object(laya_q.sys, "argv", ["laya_q.py", "setup", "--hf-token", "--skip-warmup"]), \
             patch.object(laya_q, "setup") as setup:
            self.assertEqual(laya_q.main(), 0)
            self.assertEqual(setup.call_args.args[1:], (True, False, True, True))
        with patch.object(laya_q.getpass, "getpass", return_value="hf_example") as prompt:
            self.assertEqual(laya_q.read_hf_token(), "hf_example")
            prompt.assert_called_once()

    def test_host_token_is_not_passed_to_board_commands(self):
        with patch.object(laya_q, "read_hf_token", return_value="hf_example"), \
             patch.object(laya_q, "check_device", return_value="test-board"), \
             patch.object(laya_q, "adb_run") as adb, \
             patch.object(laya_q, "download_model_on_host") as download:
            laya_q.setup("test-board", False, token_prompt=True)
            download.assert_called_once_with("test-board", "hf_example")
            self.assertNotIn("hf_example", str(adb.call_args_list))

    def test_authentication_error_prompts_and_retries_privately(self):
        hub = HubFixture()
        failure = HTTPError("https://huggingface.co/test", 401, "Unauthorized", {}, None)
        calls = []

        def request(req, **kwargs):
            calls.append(req)
            if len(calls) == 1:
                raise failure
            return hub.open(req)

        with patch.object(laya_q, "urlopen", side_effect=request), \
             patch.object(laya_q.sys.stdin, "isatty", return_value=True), \
             patch.object(laya_q, "read_hf_token", return_value="hf_example") as prompt, \
             patch.object(laya_q, "adb_run"), \
             patch.object(laya_q, "adb_base", return_value=["adb"]), \
             patch.object(laya_q.subprocess, "run", side_effect=hub.verify_board):
            laya_q.download_model_on_host("test-board", None)
            prompt.assert_called_once()
            self.assertEqual(calls[-1].get_header("Authorization"), "Bearer hf_example")

    def test_app_model_uses_hidden_cache_without_installing_second_runtime(self):
        with patch.object(laya_q, "check_device", return_value="test-board"), \
             patch.object(laya_q, "adb_run"), patch.object(laya_q, "download_model_on_host") as download:
            laya_q.setup_app_model(None, "user:laya-q-app-lab")
            download.assert_called_once_with("test-board", None, "/home/arduino/ArduinoApps/laya-q-app-lab/.cache/model")
