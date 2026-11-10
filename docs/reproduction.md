# Reproduction

Use a fresh checkout and retain every output directory. Install the CPU development
dependencies and Zig 0.14.1, then run `pytest -q` and `ruff check src tests`.
`python -m build` builds a wheel containing the pinned Qwenputer package and license.

For the GPU run, record GPU model/driver, Python, torch, transformers, Triton and
Zig versions before running. Pin the language-model revision when downloading:

```python
from huggingface_hub import snapshot_download
snapshot_download("Qwen/Qwen3.5-4B",
    revision="851bf6e806efd8d0a36b00ddf55e13ccb7b8cd0a",
    local_dir="models/Qwen3.5-4B")
```

```bash
qwenrsi evolve examples/baseline.c --model models/Qwen3.5-4B \
  --iterations 3 --out runs/rsi-001
SELECTED=$(cat runs/rsi-001/SELECTED)
qwenrsi audit-circuit "runs/rsi-001/$SELECTED" \
  --samples 32 --out runs/rsi-001/circuit-audit.json
qwenrsi eval "runs/rsi-001/$SELECTED" --backend cuda --count 16 \
  --out runs/rsi-001/circuit-workflows.json
qwenrsi coding-eval "runs/rsi-001/$SELECTED" --model models/Qwen3.5-4B \
  --tasks examples/coding_tasks.json --backend cuda --out runs/coding-001
qwenrsi export "runs/rsi-001/$SELECTED" --out artifacts/QwenRSI-Controller
```

The search uses 64 development cases (seed 1103), 64 validation cases (2207), and
256 final cases (3301). Fixed seeds are for reproducibility, not cryptographic
data isolation. The proposer is greedy with thinking disabled and seed 0. GPU
kernel/library changes may still alter generated language. Each model response
is retained, so the actual accepted program can be replayed independently.

The hand-authored `examples/verified.c` is a required comparison for interpreting
the simulator result. Evaluate it on the same final seed. The simulator is
deliberately small and its initial controller is incomplete. A successful run
demonstrates the integration; it is not a competitive agent benchmark.

Release evidence and environment details will be linked from the release notes.
