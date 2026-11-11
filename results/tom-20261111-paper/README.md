# Qwenputer JIT on the DGM initial benchmarks

This run uses the first ten SWE-bench Verified instances and the first ten
Aider Polyglot exercises listed in Appendices E.2 and E.3. DGM uses these
stages to verify basic code editing before expanded evaluation. See the
[paper](https://arxiv.org/html/2505.22954v3#S4.SS2) and the original
[SWE-bench](https://github.com/jennyzzt/dgm/blob/a565fd2d1dca504ef5104a7cc0f3bdc4ab9b4fd2/swe_bench/subsets/small.json)
and [Polyglot](https://github.com/jennyzzt/dgm/blob/a565fd2d1dca504ef5104a7cc0f3bdc4ab9b4fd2/polyglot/subsets/small.json)
task lists.

## Protocol

Both tasks use the [released RV32 controller](../tom-20261110-003/evolution/v001/)
and frozen Qwen3.5-4B at revision `851bf6e806efd8d0a36b00ddf55e13ccb7b8cd0a`.
Polyglot permits one submission per exercise with a 3,072-token generation
budget. SWE-bench permits six model calls with up to 2,048 tokens each to
search, read, and edit existing Django source. Both score the final submission
using executable tests. No test result or reference solution enters the model
conversation.

The Polyglot checkout is pinned to
`7e0611e77b54e2dea774cdc0aa00cf9f7ed6144f`. It uses the original Exercism test
files, enabling tests as in the DGM runner. Java uses JUnit Platform Console
with the exercise's JUnit and AssertJ versions. Each language toolchain was
checked with the dataset's reference solution. The
[preflight report](polyglot/preflight.json) records test hashes and exit codes.

The SWE-bench Verified dataset is pinned to
`c104f840cc67f8b6eec6f759ebc8b2693d585d4a`. On tom, the runner mounts the official
images with Bubblewrap and uses `swebench==3.0.7` for both the evaluation script
and grading. It first checks each image and grader with the dataset's reference
patch, then scores the submitted diff in a fresh testbed. It skips generating
the unused environment installation script, since each image already contains
its dependencies.

## Benchmark scores

| First-stage tasks | Qwen3.5-4B | Reference solutions |
|---|---:|---:|
| [Aider Polyglot](polyglot/report.json) | 0/10 | 10/10 |
| [SWE-bench Verified](swe-bench/report.json) | 0/10 | 10/10 |

Nine Polyglot submissions ran the exercise tests. The remaining response
could not be parsed into a source edit. SWE-bench graded two submitted diffs
and recorded eight cases with no applicable diff.

## Controller timing

Both GPU backends replay the same recorded inputs and check each action against
the benchmark run. The timing alternates backend order and synchronizes CUDA.
It includes Python dispatch and CPU/GPU transfers during controller execution.
The cold run starts with an empty path cache after shared Triton warm-up.
Steady-state numbers are medians of seven replays. Timing covers controller
execution only.

| Task traces | Decisions per replay | Generic CUDA | Warm JIT | Speedup | Cold JIT |
|---|---:|---:|---:|---:|---:|
| [Polyglot](polyglot/profile_output/jit.json) | 39 | 3.284 s | 30.96 ms | 106.1× | 1.105 s |
| [SWE-bench](swe-bench/jit.json) | 32 | 2.767 s | 16.65 ms | 166.2× | 1.173 s |

Each cold run compiled four paths, spending 0.373 seconds for Polyglot and
0.450 seconds for SWE-bench in compilation. All 1,065 action checks agreed.
All warm replays hit compiled paths. The released wheel loaded the published
Hugging Face bundle and matched the RV32 reference on all 71 recorded decisions.

[Bundle verification](bundle-replay.json) ·
[Environment](environment.json) ·
[Reproduction](../../docs/reproduction.md#paper-benchmarks)
