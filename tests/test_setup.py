import hashlib
import io
from pathlib import Path
import subprocess
import unittest
from unittest.mock import patch
from urllib.error import HTTPError

import laya_q


class SetupTests(unittest.TestCase):
    def test_downloads_on_host_and_checks_board_before_publish(self):
        weights = b"test checkpoint"
        digest = hashlib.sha256(weights).hexdigest()
        transfers = []

        def adb(serial, *args):
            if args[0] == "push":
                self.assertEqual(Path(args[1]).read_bytes(), weights)
                transfers.append(args[2])

        with patch.object(laya_q, "MODEL_FILES", ("model.safetensors",)), \
             patch.object(laya_q, "MODEL_SHA256", digest), \
             patch.object(laya_q, "urlopen", return_value=io.BytesIO(weights)) as download, \
             patch.object(laya_q, "adb_run", side_effect=adb) as adb_call, \
             patch.object(laya_q, "adb_base", return_value=["adb", "-s", "test-board"]), \
             patch.object(laya_q.subprocess, "run", return_value=subprocess.CompletedProcess([], 0, digest + "  weights\n")) as verify:
            laya_q.download_model_on_host("test-board", None)
        self.assertIn(laya_q.MODEL_REVISION, download.call_args.args[0].full_url)
        self.assertEqual(transfers, [laya_q.BOARD_MODEL + "/model.safetensors.partial"])
        self.assertIn("sha256sum", verify.call_args.args[0][-1])
        self.assertTrue(adb_call.call_args.args[-1].startswith("mv "))

    def test_corrupt_host_download_is_not_transferred(self):
        with patch.object(laya_q, "MODEL_FILES", ("model.safetensors",)), \
             patch.object(laya_q, "urlopen", return_value=io.BytesIO(b"corrupt")), \
             patch.object(laya_q, "adb_run") as adb:
            with self.assertRaisesRegex(laya_q.ToolError, "checksum"):
                laya_q.download_model_on_host("test-board", None)
            adb.assert_not_called()

    def test_corrupt_board_copy_is_not_published(self):
        weights = b"test checkpoint"
        with patch.object(laya_q, "MODEL_FILES", ("model.safetensors",)), \
             patch.object(laya_q, "MODEL_SHA256", hashlib.sha256(weights).hexdigest()), \
             patch.object(laya_q, "urlopen", return_value=io.BytesIO(weights)), \
             patch.object(laya_q, "adb_run") as adb, \
             patch.object(laya_q, "adb_base", return_value=["adb"]), \
             patch.object(laya_q.subprocess, "run", return_value=subprocess.CompletedProcess([], 0, "wrong  weights\n")):
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
        weights = b"checkpoint"
        digest = hashlib.sha256(weights).hexdigest()
        failure = HTTPError("https://huggingface.co/test", 401, "Unauthorized", {}, None)
        with patch.object(laya_q, "MODEL_FILES", ("model.safetensors",)), \
             patch.object(laya_q, "MODEL_SHA256", digest), \
             patch.object(laya_q, "urlopen", side_effect=[failure, io.BytesIO(weights)]) as download, \
             patch.object(laya_q.sys.stdin, "isatty", return_value=True), \
             patch.object(laya_q, "read_hf_token", return_value="hf_example") as prompt, \
             patch.object(laya_q, "adb_run"), \
             patch.object(laya_q, "adb_base", return_value=["adb"]), \
             patch.object(laya_q.subprocess, "run", return_value=subprocess.CompletedProcess([], 0, digest + "  weights\n")):
            laya_q.download_model_on_host("test-board", None)
            prompt.assert_called_once()
            self.assertEqual(download.call_args.args[0].get_header("Authorization"), "Bearer hf_example")
