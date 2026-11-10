# Architecture and execution contract

## Controller ABI v1

```c
int policy(const int *state);
int select_candidate(const int *state);
```

Inputs are sixteen signed 32-bit words, stored at byte address `0x100` in
Qwenputer RAM. The last word is mode: 0 for task policy, 1 for version selector.
The first fifteen words contain application state. The program emits exactly one
byte through ecall 1 and exits through ecall 93. No syscall has host side effects
in this reference/circuit implementation.

Task state: inspected, patched, verified, last error, patch attempts, remaining
steps, used steps. Actions: inspect=0, patch=1, test=2, finish=3, abort=4.
Selector state: parent solved, candidate solved, parent steps, candidate steps.
Selection returns 0 or 1. The parent selector nominates the child; the child never
approves itself. The external gate requires strictly better validation performance
under the documented solved-count/step-count ordering and no development solved
count regression. Identical candidates are not admitted.

Arithmetic must avoid C undefined behavior. This first ABI exposes bounded integer
states, no host APIs, recursion or dynamic memory. Compilation rejects preprocessor
directives and inline assembly. Native subprocesses have a deadline; reference and
circuit executions have instruction/token budgets. These are failure bounds, not
a proof of arbitrary C safety. Conformance covers sampled inputs only.

## Circuit execution

The pinned upstream core has 11 layers and implements RV32IM+Zba. Program code,
read-only data, registers and writable RAM enter its Gated DeltaNet head states.
For each state, QwenRSI constructs a fresh machine snapshot. It then feeds GO and
repeatedly feeds each circuit-predicted next trace token back into the circuit,
until HALT. An externally held reference trace is compared only after decoding.

This is execution of compiled circuit arithmetic by the upstream Triton executor,
not a merged Qwen checkpoint evaluated through stock `model.generate()`. Frozen
Qwen and the circuit are separate modules on the same GPU. Host code handles
state transfer and version switching at decision boundaries. No mid-instruction
state migration is claimed.

## Export format

`controller.safetensors` stores per-sublayer sparse row pointers, indices,
coefficients, output maps and head metadata tensors used by the executor. State
buffers and CUDA graphs are recreated. `controller.elf` supplies the selected
program and initial memory, while `source.c` enables inspection and recompilation.
`qwenrsi_config.json` pins the circuit source revision and SHA-256 of the tensor,
ELF and source files. `load_bundle` verifies hashes before loading tensor values.
The loader requires the pinned circuit layout. It validates keys, shapes and
dtypes and copies the checkpoint values into the executor.

The circuit compiler and executor are upstream Qwenputer work. Tensor serialization,
loader validation, C ABI and self-modification/evaluation orchestration are QwenRSI
work. The frozen language model is separately licensed and is not redistributed
inside this controller bundle.

## Improvement claims

Three different measurements must remain distinct:

1. Simulator success: protocol compliance under independently defined transitions.
2. Python pilot correctness: final artifacts passing independent executable tests.
3. Circuit conformance: equality to the reference program on sampled inputs/traces.

None by itself proves the others. Base-model parameters are frozen. A higher
simulator score is an improvement in the controller on that simulator, not evidence
of general intelligence gains. Changes to `select_candidate` are tracked but do
not establish recursive improvement without an additional meta-level comparison.
