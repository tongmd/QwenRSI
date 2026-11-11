"""Paired timing on controller states observed in a real benchmark run."""

import json
import statistics
import time
from pathlib import Path

from qwenrsi.circuit import CircuitController, trace_action
from qwenrsi.jit import JITController


def profile(directory, benchmark, out, device="cuda:0", repeats=5):
    report = json.loads(Path(benchmark).read_text())
    inputs = [
        (case["instance_id"], row["state"], row["action"])
        for case in report["records"]
        for row in case["controller_trace"]
    ]
    if not inputs or repeats < 1:
        raise ValueError("A completed benchmark trace and positive repetition count are required")
    baseline = CircuitController(directory, device)
    jit = JITController(directory, device)
    torch = baseline.torch

    def timed(runner, raw=False):
        torch.cuda.synchronize(device)
        started = time.perf_counter()
        tokens = 0
        for instance, state, expected in inputs:
            if raw:
                trace = runner.trace(state)
                actual = trace_action(trace)
                tokens += len(trace)
            else:
                actual = runner.decide(state)
            if actual != expected:
                raise RuntimeError(f"Controller decision mismatch on {instance}: {state}")
        torch.cuda.synchronize(device)
        return time.perf_counter() - started, tokens

    # Warm shared Triton kernels separately. Measure the JIT cache population on the real workload.
    baseline.decide(inputs[0][1])
    jit.trace(inputs[0][1])
    cold_seconds, _ = timed(jit)
    cold = jit.statistics()
    cold["compilations"] = list(cold["compilations"])
    baseline_times, jit_times = [], []
    for repetition in range(repeats):
        # Alternate order to reduce drift bias.
        if repetition % 2 == 0:
            base_seconds, tokens = timed(baseline, raw=True)
            jit_seconds, _ = timed(jit)
        else:
            jit_seconds, _ = timed(jit)
            base_seconds, tokens = timed(baseline, raw=True)
        baseline_times.append(base_seconds)
        jit_times.append(jit_seconds)
    after = jit.statistics()
    result = {
        "benchmark_report": str(benchmark),
        "dataset_revision": report["dataset_revision"],
        "gpu": torch.cuda.get_device_name(device),
        "decisions_per_replay": len(inputs),
        "repetitions": repeats,
        "matched_decisions": len(inputs) * (2 * repeats + 1),
        "baseline_seconds": baseline_times,
        "jit_seconds": jit_times,
        "median_speedup": statistics.median(baseline_times) / statistics.median(jit_times),
        "generic_tokens_per_baseline_replay": tokens,
        "generic_tokens_across_jit_replays": after.get("generic_tokens", 0) - cold.get("generic_tokens", 0),
        "cold_seconds": cold_seconds,
        "cold_jit": cold,
        "final_jit": after,
    }
    Path(out).write_text(json.dumps(result, indent=2) + "\n")
    return result
