# Third-party attribution

`vendor/qwenputer/chipformer` is an unmodified copy of
`experimental/riscv/chipformer` from [Qwenputer](https://github.com/divagr18/qwenputer),
commit `0cab57038a8b218dabe481f994174c3437405e3d`.
Copyright 2026 Divyansh Agrawal; MIT. The original license is preserved in
`vendor/qwenputer/LICENSE` and is included in built wheels.

The RV32 CPU circuit, Gated DeltaNet memory construction, layer compiler and
Triton executor are upstream work. QwenRSI contributes the editable controller
ABI, C compilation, version-selection loop, protocol benchmark, circuit bundle
interface and run/evidence packaging. This project is not an official Qwen or
Qwenputer release.

Qwen language-model weights are separate artifacts under their respective
upstream licenses. They are not included in the MIT-licensed source distribution.

The benchmark task lists follow [Darwin Gödel Machine](https://github.com/jennyzzt/dgm).
[Aider Polyglot](https://github.com/Aider-AI/polyglot-benchmark) curates exercises
from Exercism, which retains copyright in the original exercise and test content.
[SWE-bench](https://github.com/SWE-bench/SWE-bench) supplies the grader and
evaluation images. Benchmark data, images, and dependencies are fetched
separately under their upstream licenses.
