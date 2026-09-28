"""Shared CPU runtime for the UNO Q; checkpoint files stay in their original form."""

import gc
import os
import sys

DEFAULT_PRECISION = "int8"  # Change to "fp32" to disable encoder quantization.


def load_cpu_agent(model_path, precision=None):
    precision = (precision or os.environ.get("LAYA_PRECISION", DEFAULT_PRECISION)).lower()
    if precision not in ("int8", "fp32"):
        raise ValueError("LAYA_PRECISION must be int8 or fp32")
    os.environ.setdefault("USE_TF", "0")
    os.environ["HF_HUB_OFFLINE"] = "1"
    os.environ["TRANSFORMERS_OFFLINE"] = "1"
    import torch
    import laya

    torch.set_num_threads(4)
    # Called once, before model loading or inference in each worker process.
    torch.set_num_interop_threads(1)
    if precision == "int8" and "qnnpack" not in torch.backends.quantized.supported_engines:
        raise RuntimeError("This PyTorch build lacks QNNPACK; install the pinned CPU build or select fp32")
    agent = laya.load(str(model_path), device="cpu")
    if precision == "int8":
        torch.backends.quantized.engine = "qnnpack"
        agent.model.encoder = torch.ao.quantization.quantize_dynamic(
            agent.model.encoder, {torch.nn.Linear}, dtype=torch.qint8, inplace=True
        )
        gc.collect()
        # Pack weights before accepting the first real email. No user data is used.
        agent.predict("Parcel delivery", {
            "warmup": {"type": "choice", "instructions": "Topic",
                       "criteria": {"orders": "delivery", "other": "other"}}
        })
    agent.laya_q_runtime = {"precision": precision, "torch": torch.__version__,
                            "threads": 4, "interop_threads": 1}
    print(f"Laya CPU ready: {agent.laya_q_runtime}", file=sys.stderr, flush=True)
    return agent
