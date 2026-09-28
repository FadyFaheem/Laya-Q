import importlib.util
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import zipfile


class BundleTests(unittest.TestCase):
    def test_default_bundle_has_code_without_model_parts_or_network_downloads(self):
        spec = importlib.util.spec_from_file_location("bundle", "scripts/build_app_lab.py")
        bundle = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(bundle)
        with tempfile.TemporaryDirectory() as folder:
            output = Path(folder) / "app.zip"
            with patch.object(bundle.sys, "argv", ["build_app_lab.py", str(output)]), \
                 patch.object(bundle, "download_snapshot") as download:
                bundle.main()
                download.assert_not_called()
            with zipfile.ZipFile(output) as archive:
                self.assertIn("python/model_download.py", archive.namelist())
                self.assertIn("tools/model_download.py", archive.namelist())
                self.assertFalse(any(name.startswith("model/") for name in archive.namelist()))
