"""Versioned self-modification with an independent acceptance gate and final held-out evaluation."""

import datetime
import json
import os
import subprocess
import time
from pathlib import Path

from qwenrsi.benchmark import evaluate, state_samples, summary
from qwenrsi.compiler import NativeController, ReferenceController, build, sha256


def write_json(path, obj):
    Path(path).write_text(json.dumps(obj, ensure_ascii=False, indent=2) + "\n")


def conformance(directory, samples=32):
    native, reference = NativeController(directory), ReferenceController(directory)
    records = []
    for state in state_samples(count=samples):
        a, b = native.decide(state), reference.decide(state)
        if a != b or a not in range(5):
            raise ValueError(f"Invalid or divergent controller: native={a}, rv32={b}")
        records.append({"state": state, "native": a, "rv32": b})
    for state in [[0, 64, 100, 400], [64, 0, 400, 100], [64, 64, 500, 400], [64, 64, 400, 500]]:
        a, b = native.decide(state, 1), reference.decide(state, 1)
        if a != b or a not in (0, 1):
            raise ValueError("Invalid or divergent meta selector")
        records.append({"state": state, "mode": 1, "native": a, "rv32": b})
    return {"checked": len(records), "mismatches": 0, "records": records}


def improves(candidate, parent):
    """Immutable admission rule; separate from the editable nomination procedure."""
    return candidate["solved"] > parent["solved"] or (
        candidate["solved"] == parent["solved"]
        and candidate["solved"] > 0
        and candidate["total_steps"] < parent["total_steps"]
    )


def run(
    *,
    source,
    proposer,
    out,
    iterations=3,
    dev_seed=1103,
    validation_seed=2207,
    test_seed=3301,
    count=64,
    test_count=256,
):
    out = Path(out)
    out.mkdir(parents=True, exist_ok=False)
    start = time.time()
    run_manifest = {
        "schema_version": 1,
        "created_utc": datetime.datetime.now(datetime.UTC).isoformat(),
        "iterations": iterations,
        "dev_seed": dev_seed,
        "validation_seed": validation_seed,
        "test_seed": test_seed,
        "count": count,
        "test_count": test_count,
        "evaluation_type": "simulation_only",
        "model": proposer.identity,
        "upstream": "divagr18/qwenputer@0cab57038a8b218dabe481f994174c3437405e3d",
    }
    try:
        run_manifest["code_revision"] = subprocess.check_output(
            ["git", "rev-parse", "HEAD"], text=True, stderr=subprocess.DEVNULL
        ).strip()
    except subprocess.CalledProcessError:
        run_manifest["code_revision"] = os.environ.get("QWENRSI_CODE_REVISION")
    run_manifest["source_hashes"] = {p.name: sha256(p) for p in sorted(Path(__file__).parent.glob("*.py"))}
    write_json(out / "run.json", run_manifest)
    parent_path = out / "v000"
    build(source, parent_path)
    write_json(parent_path / "conformance.json", conformance(parent_path))
    parent = NativeController(parent_path)
    dev = evaluate(parent, seed=dev_seed, count=count)
    val = evaluate(parent, seed=validation_seed, count=count)
    write_json(parent_path / "development.json", dev)
    write_json(parent_path / "validation.json", val)
    baseline_path = parent_path
    history = []
    for i in range(1, iterations + 1):
        cand_path = out / f"v{i:03d}"
        cand_path.mkdir()
        event = {"iteration": i, "parent": parent_path.name, "candidate": cand_path.name, "accepted": False}
        try:
            proposal = proposer.propose(
                (parent_path / "source.c").read_text(), dev, history, cand_path / "proposal.json"
            )
            (cand_path / "proposed.c").write_text(proposal["source"])
            event["explanation"] = proposal.get("explanation", "")
            build(cand_path / "proposed.c", cand_path)
            write_json(cand_path / "conformance.json", conformance(cand_path))
            candidate = NativeController(cand_path)
            cdev = evaluate(candidate, seed=dev_seed, count=count)
            cval = evaluate(candidate, seed=validation_seed, count=count)
            write_json(cand_path / "development.json", cdev)
            write_json(cand_path / "validation.json", cval)
            state = [dev["solved"], cdev["solved"], dev["total_steps"], cdev["total_steps"]]
            # Selection runs with the current parent's program, never a candidate approving itself.
            nominated = bool(ReferenceController(parent_path).decide(state, mode=1))
            admitted = nominated and improves(cval, val) and cdev["solved"] >= dev["solved"]
            event.update(
                nominated=nominated,
                accepted=admitted,
                development=summary(cdev),
                validation=summary(cval),
                source_sha256=sha256(cand_path / "source.c"),
                meta_changed=meta_source(proposal["source"])
                != meta_source((parent_path / "source.c").read_text()),
            )
            if admitted:
                parent_path, parent, dev, val = cand_path, candidate, cdev, cval
        except Exception as exc:
            event["error"] = f"{type(exc).__name__}: {str(exc)[:1500]}"
        write_json(cand_path / "decision.json", event)
        history.append(event)
        with (out / "events.jsonl").open("a") as f:
            f.write(json.dumps(event, ensure_ascii=False) + "\n")
        print(json.dumps(event, ensure_ascii=False), flush=True)
    # Test set is consulted exactly once, after the final version is fixed.
    base_test = evaluate(NativeController(baseline_path), seed=test_seed, count=test_count)
    final_test = evaluate(parent, seed=test_seed, count=test_count)
    write_json(out / "baseline_test.json", base_test)
    write_json(out / "selected_test.json", final_test)
    report = {
        "evaluation_type": "simulation_only",
        "selected": parent_path.name,
        "accepted": sum(x["accepted"] for x in history),
        "iterations": iterations,
        "baseline": summary(base_test),
        "selected_test": summary(final_test),
        "meta_edits_accepted": sum(x["accepted"] and x.get("meta_changed", False) for x in history),
        "elapsed_seconds": time.time() - start,
        "limitations": [
            "Synthetic repair protocol; not a coding benchmark",
            "No gradient training or base-model weight updates",
            "Compiler, benchmark and model scheduling execute on host",
            "Sampled conformance is testing, not a proof for all int32 inputs",
        ],
    }
    write_json(out / "report.json", report)
    (out / "SELECTED").write_text(parent_path.name + "\n")
    return report


def meta_source(source):
    return source[source.find("int select_candidate") :].strip()
