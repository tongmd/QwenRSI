"""The DGM paper's first SWE-bench Verified stage with the upstream SWE-bench grader."""

import json
import re
import shutil
import subprocess
import time
from pathlib import Path

from qwenrsi.compiler import sha256
from qwenrsi.polyglot import PAPER, DGM_REVISION, write_json

INITIAL = (
    "django__django-10973",
    "django__django-11066",
    "django__django-12754",
    "django__django-15930",
    "django__django-13279",
    "django__django-16661",
    "django__django-13346",
    "django__django-10880",
    "django__django-10999",
    "django__django-11087",
)
DATASET = "princeton-nlp/SWE-bench_Verified"
REVISION = "c104f840cc67f8b6eec6f759ebc8b2693d585d4a"
DATASET_SHA256 = "a45b1fe4e2f0c8390b2b2938ac83e92ed5979000856808f3679c07812e9e6dcd"
# The official image already contains the environment. Generating its install
# script would fetch dependency manifests that are not used for evaluation.
TEST_SPEC = (
    "import json,sys; from swebench.harness.test_spec import test_spec; "
    "test_spec.make_env_script_list = lambda *args: []; "
    "row = json.load(open(sys.argv[1])); spec = test_spec.make_test_spec(row); "
)


def dataset_rows(python, dataset):
    if sha256(dataset) != DATASET_SHA256:
        raise ValueError("Expected the pinned SWE-bench Verified test parquet documented in docs/reproduction.md")
    script = (
        "import sys,json,pyarrow.parquet as pq; print(json.dumps(pq.read_table(sys.argv[1]).to_pylist()))"
    )
    rows = json.loads(
        subprocess.check_output([str(python), "-c", script, str(dataset)], text=True, timeout=90)
    )
    return {row["instance_id"]: row for row in rows}


def json_response(text):
    decoder = json.JSONDecoder()
    clean = re.sub(r"<think>.*?</think>", "", text, flags=re.S)
    for match in re.finditer(r"\{", clean):
        try:
            value, _ = decoder.raw_decode(clean[match.start() :])
        except ValueError:
            continue
        if isinstance(value, dict) and any(key in value for key in ("search", "read", "edits")):
            return value
    raise ValueError("Expected a JSON search, read, or edits request")


def source_file(repo, filename):
    if not isinstance(filename, str) or not filename.startswith("django/"):
        raise ValueError("Select an existing Django Python source file")
    root = (repo / "django").resolve()
    path = (repo / filename).resolve()
    if not path.is_relative_to(root) or path.suffix != ".py" or not path.is_file():
        raise ValueError(f"Invalid source path: {filename}")
    return path


def search(repo, terms):
    blocks = []
    for term in terms[:5]:
        if not isinstance(term, str) or not 3 <= len(term) <= 160 or "\n" in term:
            continue
        result = subprocess.run(
            ["git", "grep", "-n", "-F", "-e", term, "--", "django"],
            cwd=repo,
            capture_output=True,
            text=True,
            timeout=10,
        )
        hits = [line[:220] for line in result.stdout.splitlines()[:16]]
        blocks.append(term + "\n" + "\n".join(hits))
    return "\n\n".join(blocks)[:12000]


def apply_edits(repo, edits):
    if not isinstance(edits, list) or not 1 <= len(edits) <= 8:
        raise ValueError("Supply one to eight exact source replacements")
    changes = {}
    for edit in edits:
        path = source_file(repo, edit["path"])
        old, new = edit["old"], edit["new"]
        content = changes.get(path, path.read_text())
        if (
            not isinstance(old, str)
            or not isinstance(new, str)
            or not old
            or old == new
            or content.count(old) != 1
        ):
            raise ValueError(f"Old text must match exactly once in {edit['path']}")
        changes[path] = content.replace(old, new, 1)
    for path, content in changes.items():
        compile(content, str(path), "exec")
    for path, content in changes.items():
        path.write_text(content)


def propose_patch(repo, problem, model, folder, max_calls):
    instructions = (
        "Fix the Django issue in the checked-out version. Inspect the implementation and submit a minimal patch. "
        'Respond with one JSON object. Request source with {"search":["exact substring"]} or '
        '{"read":[{"path":"django/file.py","start":1,"end":100}]}. '
        'Submit edits with {"edits":[{"path":"django/file.py","old":"exact original code",'
        '"new":"replacement code"}]}. Preserve indentation. Only existing Django Python source files can be edited.'
    )
    names = list(dict.fromkeys(re.findall(r"`([A-Za-z][\w.]{3,70})`", problem)))[:5]
    hits = search(repo, [name.rsplit(".", 1)[-1] for name in names])
    messages = [
        {"role": "system", "content": instructions},
        {"role": "user", "content": f"Issue:\n{problem}\n\nInitial source search:\n{hits}"},
    ]
    for call in range(max_calls):
        if call == max_calls - 1:
            messages[-1]["content"] += "\nThis is the last call. Submit your edits now."
        response = model.generate(messages, folder / f"model-{call + 1}.json")
        try:
            request = json_response(response)
            if "edits" in request:
                apply_edits(repo, request["edits"])
                patch = subprocess.check_output(
                    ["git", "diff", "--binary", "--", "django"], cwd=repo, text=True
                )
                if patch:
                    return patch, call + 1
                raise ValueError("No source diff")
            if "search" in request:
                result = search(repo, request["search"]) or "No matches"
            else:
                files = []
                for read in request["read"][:3]:
                    file = source_file(repo, read["path"])
                    start = max(1, int(read.get("start", 1)))
                    end = min(start + 199, int(read.get("end", start + 99)))
                    content = file.read_text().splitlines()[start - 1 : end]
                    files.append(f"{read['path']} lines {start}-{end}\n" + "\n".join(content))
                result = "\n\n".join(files)[:24000]
        except (KeyError, TypeError, ValueError, SyntaxError) as exc:
            result = f"Request rejected: {exc}"
        messages.extend([{"role": "assistant", "content": response}, {"role": "user", "content": result}])
    return "", max_calls


class OfficialGrader:
    """Use the upstream eval script and scoring code inside the official image's filesystem."""

    def __init__(self, python, images):
        # Keep the venv's interpreter name so its site-packages remain available.
        self.python = Path(python).absolute()
        self.images = Path(images).resolve()
        self.bwrap = shutil.which("bwrap")
        if not self.bwrap:
            raise RuntimeError("bubblewrap is required")

    def run(self, row, patch, folder):
        instance = row["instance_id"]
        image = self.images / instance
        root = image / "rootfs"
        receipt = json.loads((image / "image.json").read_text())
        folder.mkdir(parents=True, exist_ok=False)
        repo = folder / "repo"
        shutil.copytree(root / "testbed", repo, symlinks=True)
        write_json(folder / "instance.json", row)
        (folder / "submission.patch").write_text(patch)
        script = subprocess.check_output(
            [str(self.python), "-c", TEST_SPEC + "print(spec.eval_script)", str(folder / "instance.json")],
            text=True,
            timeout=90,
        )
        (folder / "eval.sh").write_text(script)
        command = [
            self.bwrap,
            "--unshare-all",
            "--die-with-parent",
            "--clearenv",
            "--uid",
            "0",
            "--gid",
            "0",
            "--ro-bind",
            str(root),
            "/",
            "--proc",
            "/proc",
            "--dev",
            "/dev",
            "--tmpfs",
            "/tmp",
            "--bind",
            str(repo),
            "/testbed",
            "--ro-bind",
            str(folder / "eval.sh"),
            "/tmp/eval.sh",
            "--ro-bind",
            str(folder / "submission.patch"),
            "/tmp/submission.patch",
            "--chdir",
            "/testbed",
            "--setenv",
            "HOME",
            "/tmp",
            "--setenv",
            "PATH",
            "/usr/bin:/bin:/opt/miniconda3/bin",
            "--",
            "/bin/bash",
            "-ec",
            "git config --global --add safe.directory /testbed\n"
            "git apply --verbose /tmp/submission.patch\n/bin/bash /tmp/eval.sh",
        ]
        started = time.perf_counter()
        with (folder / "test_output.txt").open("w") as output:
            try:
                code = subprocess.run(
                    command, stdout=output, stderr=subprocess.STDOUT, timeout=480
                ).returncode
            except subprocess.TimeoutExpired:
                code = 124
                output.write("\nEvaluation timed out\n")
        score_script = TEST_SPEC + (
            "from swebench.harness.grading import get_eval_report; "
            "p={'instance_id':row['instance_id'],'model_patch':open(sys.argv[2]).read(),"
            "'model_name_or_path':'QwenRSI'}; print(json.dumps(get_eval_report(spec,p,sys.argv[3],True)))"
        )
        score = json.loads(
            subprocess.check_output(
                [
                    str(self.python),
                    "-c",
                    score_script,
                    str(folder / "instance.json"),
                    str(folder / "submission.patch"),
                    str(folder / "test_output.txt"),
                ],
                text=True,
                timeout=90,
            )
        )
        result = {
            "instance_id": instance,
            "image": receipt["image"],
            "passed": score[instance]["resolved"],
            "eval_exit_code": code,
            "seconds": time.perf_counter() - started,
            "official_report": score[instance],
        }
        write_json(folder / "grade.json", result)
        return result


def run_swebench(controller, model, dataset, grader, out, max_calls=6, instances=INITIAL):
    out = Path(out).resolve()
    out.mkdir(parents=True, exist_ok=False)
    rows = dataset_rows(grader.python, dataset)
    write_json(
        out / "manifest.json",
        {
            "paper": PAPER,
            "dgm_code_revision": DGM_REVISION,
            "dataset": DATASET,
            "dataset_revision": REVISION,
            "dataset_sha256": DATASET_SHA256,
            "instances": list(instances),
            "model": model.identity,
            "max_agent_calls": max_calls,
            "scorer": "swebench.harness.grading.get_eval_report",
        },
    )
    records = []
    for instance in instances:
        row = rows[instance]
        folder = out / instance
        folder.mkdir()
        root = grader.images / instance / "rootfs"
        preflight = grader.run(row, row["patch"], folder / "reference-preflight")
        if not preflight["passed"]:
            raise RuntimeError(
                f"Official reference patch failed for {instance}. See its reference-preflight log."
            )
        repo = folder / "source"
        shutil.copytree(root / "testbed", repo, symlinks=True)
        patch, calls, trace = "", 0, []
        inspected = verified = False
        for step in range(12):
            state = [int(inspected), int(bool(patch)), int(verified), 0, int(calls > 0), 12 - step, step]
            action = controller.decide(state)
            trace.append({"state": state, "action": action})
            if action == 0:
                inspected = True
            elif action == 1 and inspected and calls == 0:
                patch, calls = propose_patch(repo, row["problem_statement"], model, folder, max_calls)
            elif action == 2 and patch:
                verified = (
                    subprocess.run(["git", "diff", "--check"], cwd=repo, capture_output=True).returncode == 0
                )
                if not verified:
                    break
            else:
                break
        if patch:
            outcome = grader.run(row, patch, folder / "evaluation")
        else:
            outcome = {"instance_id": instance, "passed": False, "reason": "no applicable model patch"}
        record = {**outcome, "model_calls": calls, "controller_trace": trace}
        write_json(folder / "result.json", record)
        records.append(record)
        print(instance, "RESOLVED" if record["passed"] else "UNRESOLVED", flush=True)
    report = {
        "dataset": DATASET,
        "dataset_revision": REVISION,
        "subset": "DGM Appendix E.2 initial 10",
        "metric": "resolved",
        "solved": sum(r["passed"] for r in records),
        "count": len(records),
        "records": records,
    }
    if hasattr(controller, "statistics"):
        report["jit"] = controller.statistics()
    write_json(out / "report.json", report)
    return report
