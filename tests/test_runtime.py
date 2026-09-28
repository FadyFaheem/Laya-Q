import os
import unittest
from unittest.mock import MagicMock, patch

from laya_runtime import load_cpu_agent


class RuntimeTests(unittest.TestCase):
    def runtime(self, mode="int8", warmup_error=None):
        torch = MagicMock()
        torch.__version__ = "2.14.0+cpu"
        torch.backends.quantized.supported_engines = ["qnnpack"]
        laya = MagicMock()
        agent = laya.load.return_value
        original_encoder = agent.model.encoder
        original_head = agent.model.head
        agent.predict.side_effect = warmup_error
        with patch.dict("sys.modules", {"torch": torch, "laya": laya}), \
             patch.dict(os.environ, {"LAYA_PRECISION": mode}):
            result = load_cpu_agent("local-model")
            self.assertEqual(os.environ["HF_HUB_OFFLINE"], "1")
            self.assertEqual(os.environ["TRANSFORMERS_OFFLINE"], "1")
        return result, torch, original_encoder, original_head

    def test_int8_preserves_head_and_warms_before_ready(self):
        agent, torch, encoder, head = self.runtime()
        self.assertIs(agent.model.head, head)
        self.assertIsNot(agent.model.encoder, encoder)
        self.assertEqual(agent.laya_q_runtime["precision"], "int8")
        agent.predict.assert_called_once()
        self.assertIn("Parcel delivery", agent.predict.call_args.args)

    def test_fp32_fallback_preserves_encoder(self):
        agent, torch, encoder, head = self.runtime("fp32")
        self.assertIs(agent.model.encoder, encoder)
        self.assertIs(agent.model.head, head)
        torch.ao.quantization.quantize_dynamic.assert_not_called()
        self.assertEqual(agent.laya_q_runtime["precision"], "fp32")

    def test_failed_warmup_does_not_return_ready_agent(self):
        with self.assertRaisesRegex(RuntimeError, "warmup failed"):
            self.runtime(warmup_error=RuntimeError("warmup failed"))

    def test_invalid_mode_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "int8 or fp32"):
            load_cpu_agent("unused", precision="fp16")
