# Measured release run

The first completed run is [tom-20261110-003](tom-20261110-003/). Earlier launch
attempts were superseded during setup and a Python 3.10 compatibility fix before
any search result was produced. The completed search retained all three proposals,
including two rejected proposals. No candidate was chosen using final-test scores.

| Check | Result | Evidence |
|---|---|---|
| Frozen model | Qwen3.5-4B, revision `851bf6e806efd8d0a36b00ddf55e13ccb7b8cd0a` | [run manifest](tom-20261110-003/evolution/run.json) |
| Search | 3 proposals, 1 accepted; selected v001 | [events](tom-20261110-003/evolution/events.jsonl) |
| Final synthetic protocol, seed | 0/256 | [baseline trajectories](tom-20261110-003/evolution/baseline_test.json) |
| Final synthetic protocol, selected | 216/256 (84.375%) | [selected trajectories](tom-20261110-003/evolution/selected_test.json) |
| Final synthetic protocol, hand-written verified policy | 256/256 | [comparison](tom-20261110-003/human-comparison/results.json) |
| Selected GPU circuit, sampled whole workflows | 14/16 | [GPU workflows](tom-20261110-003/circuit-workflows.json) |
| Free-running circuit conformance | 35 runs, 1,220 tokens, 0 mismatches | [trace audit](tom-20261110-003/circuit-audit.json) |
| Actual model response versus executable source; native versus RV32 scores | Replay passed | [replay evidence](tom-20261110-003/evolution/replay.json) |
| Real Python repair pilot, seed | 4/4 | [baseline pilot](tom-20261110-003/coding-baseline/report.json) |
| Real Python repair pilot, selected on GPU circuit | 4/4 | [selected pilot](tom-20261110-003/coding-selected/report.json) |

The simulator seed deliberately skips verification. The selected policy adds
verification and changes the selector, but its patch-attempt cutoff still causes
failures. The hand-written policy solves every simulator task. Therefore this run
supports a working model-generated controller-edit/validation/execution loop; it
does not establish superior policy discovery, broad coding improvement, or
recursive improvement of the improvement algorithm.

All scores come from executed environments or tests, never model self-grading.
The oracle for the four real Python tasks is not passed to the model. The four
tasks are authored integration cases and not a competitive coding benchmark.
The selected circuit's 14/16 workflow success is consistent with its imperfect
program; zero token mismatches means faithful execution, not a perfect policy.

The original search used native execution for efficient candidate scoring and the
RV32 parent program for nomination. All scores were subsequently recomputed with
RV32, including a second portable replay on macOS. GPU execution was checked
separately, including complete workflows and a real repair pilot. The exported
coefficient file was reloaded and audited before publication.

Run commands and environment are in the source's `scripts/run_tom.sh`,
[environment.json](tom-20261110-003/environment.json) and run manifest. CLI usage:

```bash
qwenrsi replay results/tom-20261110-003/evolution
```

The selected compiled model and its SHA-256 receipt are available at
[Hugging Face](https://huggingface.co/StoneZhang/QwenRSI-Controller-v0.1) and
[publication.json](tom-20261110-003/publication.json). This artifact includes the
CPU circuit and program state; it does not contain newly trained Qwen weights.
