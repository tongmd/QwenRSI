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
