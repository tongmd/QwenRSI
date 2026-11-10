"""Recompute a completed experiment with RV32 and verify proposal provenance."""

import json
from pathlib import Path

from qwenrsi.benchmark import evaluate, summary
from qwenrsi.compiler import ReferenceController, sha256
from qwenrsi.model import extract_proposal


def replay(directory):
    root = Path(directory)
    config = json.loads((root / "run.json").read_text())
    selected = (root / "SELECTED").read_text().strip()
    if Path(selected).name != selected:
        raise ValueError("Invalid selected-version path")
    checks = []
    for folder in sorted(root.glob("v[0-9][0-9][0-9]")):
        if not (folder / "manifest.json").exists():
            continue
        manifest = json.loads((folder / "manifest.json").read_text())
        if sha256(folder / "source.c") != manifest["source_sha256"]:
            raise ValueError(f"Source hash mismatch in {folder.name}")
        if sha256(folder / "controller.elf") != manifest["elf_sha256"]:
            raise ValueError(f"Firmware hash mismatch in {folder.name}")
        if folder.name != "v000":
            proposal = json.loads((folder / "proposal.json").read_text())
            actual = extract_proposal(proposal["response"])["source"]
            if actual != (folder / "source.c").read_text():
                raise ValueError(f"Executable source differs from model response in {folder.name}")
        for name, seed in [("development", config["dev_seed"]), ("validation", config["validation_seed"])]:
            path = folder / f"{name}.json"
            if path.exists():
                expected = json.loads(path.read_text())
                actual = evaluate(ReferenceController(folder), seed=seed, count=config["count"])
                if actual != expected:
                    raise ValueError(f"RV32 replay mismatch: {folder.name}/{name}")
                checks.append({"version": folder.name, "split": name, **summary(actual)})
    for name, version in [("baseline", "v000"), ("selected", selected)]:
        expected = json.loads((root / f"{name}_test.json").read_text())
        actual = evaluate(
            ReferenceController(root / version), seed=config["test_seed"], count=config["test_count"]
        )
        if expected != actual:
            raise ValueError(f"Final test replay mismatch: {name}")
        checks.append({"version": version, "split": f"{name}_test", **summary(actual)})
    result = {
        "status": "passed",
        "backend": "rv32-reference",
        "checks": checks,
        "model_proposals_match_executable_source": True,
        "scope": "Direct deterministic replay; not an independent external review",
    }
    (root / "replay.json").write_text(json.dumps(result, indent=2) + "\n")
    return result
