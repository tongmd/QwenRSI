"""Run an editable controller on real Python repair tasks with independent tests.

Task JSON holds description, initial_source, visible_tests and oracle_tests. Only
description, current source and visible-test feedback enter Qwen's context.
The final oracle is used after the controller finishes, never as retry feedback.
Generated Python runs in a time/resource-limited subprocess, NOT a security sandbox.
"""

import json
from pathlib import Path
import re
import subprocess
import sys
import time


def python_source(text):
    text = re.sub(r"<think>.*?</think>", "", text, flags=re.S)
    blocks = re.findall(r"```(?:python)?\s*\n(.*?)```", text, re.S)
    source = blocks[-1] if blocks else text.strip()
    compile(source, "<candidate>", "exec")
    return source


def check(source, tests):
    prefix = "import resource\nresource.setrlimit(resource.RLIMIT_CPU,(2,2))\n"
    prefix += "import sys\nif sys.platform.startswith('linux'):\n"
    prefix += "    resource.setrlimit(resource.RLIMIT_AS,(1073741824,1073741824))\n"
    try:
        p = subprocess.run(
            [sys.executable, "-I", "-c", prefix + source + "\n" + tests],
            capture_output=True,
            text=True,
            timeout=4,
        )
    except subprocess.TimeoutExpired:
        return False, "Test subprocess timed out"
    return p.returncode == 0, p.stderr[-1500:]


def evaluate_coding(controller, model, tasks, out, max_steps=12, max_model_calls=4):
    out = Path(out)
    out.mkdir(parents=True, exist_ok=False)
    records, start = [], time.time()
    for index, task in enumerate(tasks):
        folder = out / f"task-{index:03d}"
        folder.mkdir()
        source = task["initial_source"]
        inspected = patched = verified = False
        attempts, error, feedback, trace = 0, 0, "", []
        ended = False
        for step in range(max_steps):
            state = [int(inspected), int(patched), int(verified), error, attempts, max_steps - step, step]
            action = controller.decide(state)
            trace.append({"state": state, "action": action})
            error = 0
            if action == 0:
                inspected = True
            elif action == 1:
                if not inspected:
                    error = 1
                    continue
                if attempts >= max_model_calls:
                    break
                attempts += 1
                messages = [
                    {
                        "role": "system",
                        "content": "Repair the Python module. Return the complete "
                        "module in one Python code block, no commentary. Preserve the public function API.",
                    },
                    {
                        "role": "user",
                        "content": json.dumps(
                            {
                                "task": task["description"],
                                "source": source,
                                "visible_tests": task["visible_tests"],
                                "feedback": feedback,
                            }
                        ),
                    },
                ]
                text = model.generate(messages, folder / f"attempt-{attempts}.json")
                try:
                    source = python_source(text)
                    (folder / f"attempt-{attempts}.py").write_text(source)
                    patched, verified = True, False
                except (SyntaxError, ValueError) as exc:
                    feedback, error = str(exc), 2
            elif action == 2:
                if not patched:
                    error = 3
                    continue
                verified, feedback = check(source, task["visible_tests"])
                if not verified:
                    patched, error = False, 4
            elif action == 3:
                ended = True
                break
            else:
                break
        passed, oracle_error = check(source, task["oracle_tests"])
        (folder / "final.py").write_text(source)
        records.append(
            {
                "task_id": task["id"],
                "finished": ended,
                "success": ended and passed,
                "oracle_passed": passed,
                "verified_before_finish": verified,
                "model_calls": attempts,
                "steps": len(trace),
                "trace": trace,
                "oracle_error": oracle_error,
            }
        )
    result = {
        "evaluation_type": "real_gt",
        "suite": "python-repair-pilot-v1",
        "scope": "Small authored repair tasks; not SWE-bench or a general coding benchmark",
        "count": len(tasks),
        "solved": sum(r["success"] for r in records),
        "model_calls": sum(r["model_calls"] for r in records),
        "elapsed_seconds": time.time() - start,
        "records": records,
    }
    (out / "report.json").write_text(json.dumps(result, indent=2) + "\n")
    return result
