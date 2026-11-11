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

## Paper benchmarks

The task lists are the initial ten instances in each of Appendices E.2 and E.3
of the [Darwin Gödel Machine paper](https://arxiv.org/html/2505.22954v3). Use
Linux x86-64, CUDA, and Bubblewrap with user namespaces enabled. To replay the
released controller, use `results/tom-20261110-003/evolution/v001` as
`controller`. The commands also accept a directory produced by `qwenrsi build`.

```bash
controller=results/tom-20261110-003/evolution/v001
git clone https://github.com/Aider-AI/polyglot-benchmark.git data/polyglot-benchmark
git -C data/polyglot-benchmark checkout 7e0611e77b54e2dea774cdc0aa00cf9f7ed6144f
qwenrsi polyglot "$controller" --model models/Qwen3.5-4B \
  --dataset data/polyglot-benchmark --tools "$PWD/tools" \
  --test-python "$PWD/.venv-tests/bin/python" --out runs/polyglot
mkdir -p runs/profiles
qwenrsi profile-jit "$controller" runs/polyglot/report.json \
  --repeats 7 --out runs/profiles/polyglot.json
```

For Polyglot, install pytest in the test Python environment. Put Go under
`tools/golang.org/toolchain@*/bin/go` and Rust under
`tools/rustup/toolchains/*/bin/cargo`. Put Jest and the exercise's Babel
dependencies under `tools/npm/node_modules` using the JavaScript exercise's
`package.json`. Put `junit-platform-console-standalone-1.10.0.jar` and
`assertj-core-3.25.1.jar` in `tools/`. Provide Node.js, a JDK, CMake, and a
C++ compiler on PATH. The runner checks all reference solutions before scoring.

For SWE-bench, download the pinned
[SWE-bench Verified test parquet](https://huggingface.co/datasets/princeton-nlp/SWE-bench_Verified/resolve/c104f840cc67f8b6eec6f759ebc8b2693d585d4a/data/test-00000-of-00001.parquet)
to `data/swe-verified.parquet`. Install the official grader in a separate Python
environment. Use the [crane](https://github.com/google/go-containerregistry/releases/tag/v0.20.3)
binary to materialize the official Linux x86-64 images.

```bash
python -m venv .venv-swebench
.venv-swebench/bin/python -m pip install 'swebench==3.0.7' pyarrow
python scripts/prepare_swe_images.py --crane "$(command -v crane)" --out data/swe-images
qwenrsi swe-bench "$controller" --model models/Qwen3.5-4B \
  --dataset data/swe-verified.parquet --images data/swe-images \
  --grader-python .venv-swebench/bin/python --out runs/swe-bench
qwenrsi profile-jit "$controller" runs/swe-bench/report.json \
  --repeats 7 --out runs/profiles/swe-bench.json
```

The SWE-bench runner runs the upstream test script and scorer with the official
image filesystem mounted in a Bubblewrap namespace. It checks the dataset
reference patch for each instance before evaluating Qwen's submission. Both
runners keep test outputs out of the model conversation.
