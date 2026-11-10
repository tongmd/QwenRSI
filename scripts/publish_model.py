"""Publish only a completed, audited controller bundle and its measured evidence."""

import argparse
import json
from pathlib import Path
import shutil


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("run", type=Path)
    ap.add_argument("--repo", required=True)
    args = ap.parse_args()
    root = args.run.resolve()
    if (root / "STATUS").read_text().strip() != "complete":
        raise RuntimeError("Refusing to publish an incomplete run")
    report = json.loads((root / "evolution/report.json").read_text())
    replay = json.loads((root / "evolution/replay.json").read_text())
    audit = json.loads((root / "model/circuit_audit.json").read_text())
    if replay["status"] != "passed" or audit["mismatches"] != 0:
        raise RuntimeError("Replay or exported-circuit audit did not pass")
    if report["accepted"] < 1:
        raise RuntimeError("No model-generated controller improvement was accepted")
    from qwenrsi.compiler import sha256

    config = json.loads((root / "model/qwenrsi_config.json").read_text())
    for name, digest in config["files"].items():
        if sha256(root / "model" / name) != digest:
            raise RuntimeError(f"Artifact hash mismatch: {name}")
    code = json.loads((root / "coding-selected/report.json").read_text())
    baseline_code = json.loads((root / "coding-baseline/report.json").read_text())
    target = root / "model"
    ev = target / "evidence"
    ev.mkdir(exist_ok=True)
    for relative in [
        "environment.json",
        "circuit-audit.json",
        "circuit-workflows.json",
        "evolution/report.json",
        "evolution/run.json",
        "evolution/replay.json",
        "evolution/events.jsonl",
        "coding-selected/report.json",
        "coding-baseline/report.json",
        "human-comparison/results.json",
    ]:
        dest = ev / relative
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(root / relative, dest)
    selected = report["selected"]
    for name in ["proposal.json", "decision.json", "conformance.json"]:
        shutil.copy2(root / "evolution" / selected / name, ev / name)
    license_root = Path(__file__).resolve().parents[1]
    shutil.copy2(license_root / "LICENSE", target / "LICENSE")
    shutil.copy2(license_root / "vendor/qwenputer/LICENSE", target / "QWENPUTER_LICENSE")
    base, final = report["baseline"], report["selected_test"]
    card = f'''---
license: mit
library_name: qwenrsi
base_model: Qwen/Qwen3.5-4B
tags:
- qwenputer
- compiled-circuit
- agent-harness
- self-modification
- experimental
---
# QwenRSI Controller v0.1

An experimental **compiled agent-controller bundle**, produced by a frozen
Qwen3.5-4B model modifying its C harness. This repository contains real sparse
Qwenputer circuit coefficients (`controller.safetensors`), the selected RV32
program (`controller.elf`), source, hashes and measured evidence.

It is **not a trained Qwen language model**, a merged language-model checkpoint,
or a LoRA adapter. Qwen's language-model parameters are unchanged and loaded
separately. The circuit implements the CPU; the evolved program lives in its
initialized ROM/RAM state. Use the QwenRSI loader, not `AutoModel.from_pretrained`.

Code: https://github.com/tongmd/QwenRSI

## Measured run

Run: `{root.name}` on an NVIDIA RTX 4090. Actual model prompts/responses and
selected source provenance are preserved. {report["accepted"]} of
{report["iterations"]} proposed controller versions were admitted.

| Measurement | Result |
|---|---|
| Synthetic repair protocol, seed controller | {base["solved"]}/{base["count"]} |
| Synthetic repair protocol, selected controller | {final["solved"]}/{final["count"]} |
| Real Python repair pilot, seed controller | {baseline_code["solved"]}/{baseline_code["count"]} |
| Real Python repair pilot, selected controller | {code["solved"]}/{code["count"]} |
| Exported tensor reload audit | {audit["free_running_tokens"]} free-running trace tokens, 0 mismatches |

The simulator starts from a deliberately incomplete policy. A hand-written
verified policy is also reported in `evidence/human-comparison/results.json`.
The simulator result is **simulation-only protocol improvement**. The four
Python tasks are an authored integration pilot, not evidence of broad coding
improvement. The final test split was excluded from candidate selection.
Meta-selector edits are tracked but do not prove recursive improvement in the
improvement mechanism. No automatic hotspot JIT is implemented in this release.

## Load

Install the source project with GPU dependencies on Linux, then:

```python
from huggingface_hub import snapshot_download
from qwenrsi.circuit import load_bundle

path = snapshot_download("{args.repo}")
controller = load_bundle(path, device="cuda:0")
print(controller.decide([1, 1, 0, 0, 1, 8, 4]))
```

`load_bundle` verifies SHA-256, loads the sparse coefficient tensors and
initializes the program from the ELF. Circuit decisions are generated freely;
reference outputs are used only for post-run comparisons. The host still
handles compilation, state initialization, evaluation, file I/O and model
scheduling. This is the upstream circuit's Triton execution path, not stock
Transformers `generate()` on one merged model.

## Attribution and license

Qwenputer's compiled RV32 CPU, DeltaNet memory and executor are by Divyansh
Agrawal, MIT, pinned at `0cab57038a8b218dabe481f994174c3437405e3d`.
QwenRSI's controller/evolution/packaging code is by Tong Zhang, MIT.
Qwen/Qwen3.5-4B is a separate upstream model under its own license; its weights
are not included here. See `LICENSE` and `QWENPUTER_LICENSE`.
'''
    (target / "README.md").write_text(card)
    from huggingface_hub import HfApi

    api = HfApi()
    who = api.whoami()["name"]
    if args.repo.split("/")[0] != who:
        raise RuntimeError(f"Publishing account does not match requested namespace: {who}")
    api.create_repo(args.repo, repo_type="model", private=False, exist_ok=True)
    commit = api.upload_folder(
        repo_id=args.repo,
        repo_type="model",
        folder_path=target,
        commit_message="Release audited QwenRSI controller v0.1",
    )
    receipt = {
        "repo_id": args.repo,
        "url": f"https://huggingface.co/{args.repo}",
        "commit": commit.oid,
        "run": root.name,
        "files": config["files"],
    }
    (root / "publication.json").write_text(json.dumps(receipt, indent=2) + "\n")
    print(json.dumps(receipt, indent=2))


if __name__ == "__main__":
    main()
