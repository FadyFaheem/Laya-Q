# UNO Q performance investigation

## Scope

Measurements use the connected 4 GB UNO Q, the installed English Laya checkpoint,
Laya 0.3.20, and initially PyTorch 2.9.1+cpu, followed by 2.14.0+cpu. A synthetic shipping email is classified with
two questions: eight folder choices and three urgency choices. No real email was
read or processed. The user's active descriptions were used privately for the
baseline; they are not included here.

The Outlook batch was stopped by the user before testing. A temporary container
reused the installed environment and checkpoint, with networking disabled. Only
one model process ran at a time. Timings exclude loading, USB transport and Outlook
mailbox operations. Each table entry is the median of two measured predictions.
PyTorch inter-op threads were fixed at one in the benchmark; the original app used
four. Intra-op threads were varied. These are exploratory measurements, not a
mail-classification accuracy evaluation.

## Hardware and original runtime

- Four CPU cores; Linux reports Qualcomm Kryo-V2, ARM64. Arduino identifies the
  QRB2210 CPU as quad Cortex-A53, up to 2 GHz.
- CPU frequency observed at 2.016 GHz, with the `schedutil` governor.
- The live Laya app used approximately 380% CPU during mail processing: all four
  cores were already busy. Its container has no configured CPU or memory cap.
- PyTorch defaults to four intra-op and four inter-op threads. Its libraries
  include OpenBLAS 0.3.30 and Arm Compute Library. OpenBLAS reports a four-thread
  OpenMP build using its generic `armv8` kernel.
- Runtime memory was about 2 GB RSS. There was roughly 1 GB available RAM and
  little swap in use. Sampled CPU thermal-zone readings were approximately
  52–55 degrees C; sampled clock speeds did not show throttling.
- The CPU flags do not advertise native BF16, FP16 arithmetic or integer
  dot-product extensions. Do not assume performance claims for newer Snapdragon
  laptop processors apply to this board.

Hardware reference: [Arduino UNO Q manual](https://docs.arduino.cc/tutorials/uno-q/user-manual/).

## Why criteria affect latency

The installed Laya implementation makes one encoded row per question, containing
the question, its options and the email state. It pads the rows to the longest row
before inference. Increasing descriptions therefore increases transformer work,
and a longer question can add padded work to the other question too.

The checkpoint's default total budget is 512 tokens per row and its question/options
budget is 192 tokens. Laya shortens option descriptions and instructions to fit;
very long descriptions are not necessarily read in full. The returned
`usage.input_tokens` sums the unpadded lengths across questions, not a single
shared context. Tokenization caching alone does not remove the expensive model
computation.

The [upstream documentation](https://github.com/NandhaKishorM/laya#honest-limits)
discusses head budgets, shortlisting and coarse/fine questions for large label sets.
For eight folder labels, concise descriptions are a simpler first experiment than
adding another embedding model or a second routing pass.

## CPU measurements with PyTorch 2.9.1

| Configuration | Criteria | Median seconds | Input tokens |
| --- | --- | ---: | ---: |
| FP32, four intra-op threads | Current descriptions | 40.074 | 391 |
| FP32, four intra-op threads | Compact descriptions, same label set | 18.672 | 193 |
| FP32, two intra-op threads | Current descriptions | 41.803 | 391 |
| FP32, one intra-op thread | Current descriptions | 48.441 | 391 |
| FP32, four threads, later repeat | Current descriptions | 41.039 | 391 |
| FP32, four threads, later repeat | Compact descriptions | 19.726 | 193 |
| FP32, Cortex-A53 OpenBLAS kernel, four threads | Current descriptions | 43.672 | 391 |
| FP32, Cortex-A53 OpenBLAS kernel, four threads | Compact descriptions | 21.095 | 193 |
| INT8 encoder, QNNPACK, four threads | Current descriptions | 17.503 | 391 |
| INT8 encoder, QNNPACK, four threads | Compact descriptions | 7.305 | 193 |

Every result above returned `orders` and `routine`. The shorter descriptions were
about 2.15 times faster for this example. This does not establish accuracy on other
mail. Keep detailed routing policy in the rules where possible, and validate any
rewritten model descriptions against representative labeled examples before
replacing active settings. The active settings were not changed during research.

The INT8 experiment dynamically quantized only the encoder's Linear layers,
retaining the decision head in FP32. Its first prediction with current criteria
took 20.840 s including first-use overhead; the second took 14.167 s. The compact
case took 7.280 and 7.330 s. RSS fell from about 2.0 GiB to 1.4 GiB in this process.
Both variants kept the same choices on this one synthetic email. These results
show that INT8 is viable on this CPU, not that it is accurate enough for every
mailbox. No quantized checkpoint was saved. The production app was left unchanged
during this first experiment; the later requested deployment is described below.

Thread settings are workload dependent, and PyTorch and BLAS parallelism can
interact. Reducing the tested intra-op setting did not improve this workload.
See [OpenBLAS threading guidance](https://www.openmathlib.org/OpenBLAS/docs/faq/).

Forcing `OPENBLAS_CORETYPE=CORTEXA53` did select the dedicated `cortexa53` kernel,
but current-criteria timings were 43.632 and 43.712 s, slower than automatic
selection. Leave the default CPU-kernel detection in place for this installation.

## Other acceleration paths

### ONNX Runtime and INT8

Laya includes an ONNX agent; current upstream also documents export with INT8
quantization. This is a candidate for a subsequent CPU runtime comparison using
the same checkpoint and exact tokenization. ONNX Runtime recommends dynamic
quantization for transformers, but explicitly warns that quantization can affect
accuracy. The board lacks newer Arm dot-product instructions, so speedups measured
on recent CPUs cannot be assumed here.

References: [Laya export script](https://github.com/NandhaKishorM/laya/blob/main/scripts/export_onnx.py),
[ONNX Runtime quantization](https://onnxruntime.ai/docs/performance/model-optimizations/quantization.html).

### Adreno GPU

`vulkaninfo` detects the actual **Turnip Adreno 702**, Mesa 26.1.6, and advertises
FP16 shader and 16-bit storage features. It also lists **llvmpipe**, a software CPU
renderer: selecting that device would not provide GPU acceleration. The Vulkan
loader reports 1.4 while the Adreno physical device reports 1.0.354; compatibility
must be checked against the chosen runtime rather than inferred from the loader.

The current PyTorch CPU package does not run Laya on this GPU. A separate runtime
such as [laya.cpp's Vulkan backend](https://github.com/lkarlslund/laya.cpp/blob/main/docs/vulkan.md)
would require an ARM64 build, model preparation and operator/output validation on
this Adreno. That project's published GPU results concern other hardware. Vulkan
availability is encouraging, but is not a measured Laya GPU speedup on the UNO Q.

CPU/GPU cooperation requires a runtime that assigns supported graph sections to
the GPU and executes the remaining work on the CPU. That does not necessarily
execute both sections simultaneously: dependent layers must wait for their inputs,
and transfers and synchronization can erase the gain on a small GPU. Tokenization
can remain on the CPU while the encoder runs on the GPU in a suitable runtime.

[ExecuTorch's Vulkan backend](https://docs.pytorch.org/executorch/stable/backends/vulkan/vulkan-overview.html)
and its partitioner provide a potential route, but the documented target minimum
is Vulkan 1.1. This board's physical Adreno device currently reports Vulkan 1.0,
so it does not meet that advertised requirement with the installed driver.
The loader's newer version and the software llvmpipe device do not resolve that.
An upgrade of the Python PyTorch wheel alone does not change the GPU driver or
export Laya into an ExecuTorch program. No GPU inference was deployed or timed.

Do not treat Qualcomm QNN as a universal Snapdragon acceleration switch. Its
[execution-provider documentation](https://onnxruntime.ai/docs/execution-providers/QNN-ExecutionProvider.html)
describes specific runtime backends and supported operators. A working QRB2210
backend for this model has not been established here.

### Smaller model or fewer model decisions

The family offers a smaller multilingual checkpoint, but swapping it changes model
behavior and requires a new accuracy comparison. More questions add encoded rows;
avoid requesting questions whose answers cannot affect the configured actions.
Large mail batches do not automatically improve per-message speed on this CPU;
benchmark throughput and memory before adding concurrency.

## PyTorch 2.14 upgrade and INT8 deployment

The official 2.14.0+cpu wheel for CPython 3.13 / manylinux 2.28 ARM64 was downloaded
on the PC, verified against its index digest and transferred over USB. Initial
testing used an isolated import path; full-model testing stopped the production
container and used a temporary container with networking disabled. Import,
matrix multiplication, SDPA attention and full Laya predictions all passed.

| PyTorch 2.14 configuration | Criteria | Two calls (seconds) | Median |
| --- | --- | --- | ---: |
| FP32, four threads | Current | 41.767, 42.620 | 42.194 |
| FP32, four threads | Compact | 21.892, 20.343 | 21.117 |
| INT8 encoder, QNNPACK, four threads | Current | 20.956, 14.618 | 17.787 |
| INT8 encoder, QNNPACK, four threads | Compact | 7.249, 7.240 | 7.245 |

All eight calls returned `orders` / `routine`. The version upgrade alone did not
improve speed. INT8 provides the measured improvement; compact descriptions remain
an additional option, not a change made to the user's Outlook rules. First-use
INT8 packing accounts for some of the first-call cost. A startup warmup now runs
before the app reports ready, though new input shapes can still add overhead.

At the user's request, the active App Lab environment was upgraded to 2.14.0+cpu,
and the shared runtime now defaults to INT8 encoder Linear layers with FP32
decision layers, four intra-op threads and one inter-op thread. The original
safetensors and tokenizer files are unchanged. The verified 2.9.1 wheel is kept
in the board's private performance cache for rollback. The legacy direct-worker
environment was not reinstalled; its next `setup` uses the updated source pins.

To use FP32, set `LAYA_PRECISION=fp32` in the process environment or change
`DEFAULT_PRECISION` in the deployed `python/laya_runtime.py` and restart. The
repository's root helper is the source copied into both App Lab and direct-worker
packages. `/health` reports precision, PyTorch version and thread counts. Failed
conversion or warmup prevents readiness rather than silently changing precision.

The 2.14 legacy `torch.ao` quantization API emits deprecation warnings but worked
in these tests. Recheck it on future upgrades. The original checkpoint also has
its existing calibration warning. Quantization can change probabilities or labels;
the shipping case is not a broad accuracy validation. A dependency check also
found pre-existing base-environment issues (missing pycairo for PyGObject and an
older certifi for requests); these were present before the torch replacement.

References: [PyTorch 2.14 release](https://pytorch.org/blog/pytorch-2-14-release-blog/),
[official CPU wheel index](https://download.pytorch.org/whl/cpu/torch/).

## Further performance work

1. Compare the enabled INT8 mode against FP32 on a representative labeled test
   set. The user requested enabling it after the synthetic benchmarks. ONNX was
   researched but not benchmarked.
2. Offer compact model-facing descriptions while preserving every folder label
   and the user's detailed rules. The combined INT8/compact experiment was about
   5.5 times faster than the current-criteria FP32 baseline on this example.
3. Treat an Adreno/Vulkan port as a separate experiment with device checks and
   output comparisons, not a promised accelerator switch.

After the initial benchmark runs, the original App Lab container was restored and
the synthetic triage request returned `billing` over USB. The later requested
PyTorch/INT8 deployment supersedes that original runtime. Source changes are local;
no commit, push or release was made for this investigation.

Post-deployment verification: `/health` returned `ready=true`, `precision=int8`,
`torch=2.14.0+cpu`, four intra-op threads and one inter-op thread. The exact
synthetic shipping request returned `orders` / `routine` in 15.268 seconds through
USB HTTP. The repository triage example returned `billing`. An earlier host
PowerShell hashtable reordered the state fields and produced `urgent`; preserving
the benchmark's field order restored the matching output. Laya serializes that
state into text, so request formatting matters and the one-case match should not
be generalized. Outlook's request formatting and rules were not changed.

All 23 project tests and source compilation passed on the board, including ZIP
inclusion of the shared helper, health metadata and FP32 fallback behavior.
The live service is running INT8. The temporary test USB forward was removed.
