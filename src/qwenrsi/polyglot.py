"""Run the Darwin Gödel Machine paper's initial Polyglot tasks with their Exercism tests."""

import hashlib
import json
import re
import shutil
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

PAPER = "https://arxiv.org/html/2505.22954v3"
DATASET = "https://github.com/Aider-AI/polyglot-benchmark"
DGM_REVISION = "a565fd2d1dca504ef5104a7cc0f3bdc4ab9b4fd2"
INITIAL = (
    "go__dominoes",
    "cpp__all-your-base",
    "python__dominoes",
    "java__sgf-parsing",
    "javascript__robot-name",
    "rust__variable-length-quantity",
    "python__beer-song",
    "go__book-store",
    "javascript__bottle-song",
    "rust__bowling",
)
SOURCE_SUFFIXES = {".py", ".rs", ".go", ".js", ".cpp", ".h", ".java"}


def write_json(path, value):
    Path(path).write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n")


def exercise(dataset, instance):
    lang, name = instance.split("__", 1)
    return Path(dataset) / lang / "exercises" / "practice" / name


def task_sources(config):
    return [name for name in config["solution"] if Path(name).suffix in SOURCE_SUFFIXES]


def parse_edit(response, allowed):
    clean = re.sub(r"<think>.*?</think>", "", response, flags=re.S)
    blocks = re.findall(r"^```([^\n]*)\n(.*?)^```[ \t]*$", clean, flags=re.M | re.S)
    result = {}
    for label, contents in blocks:
        name = label.strip().removeprefix("file ").strip()
        if name not in allowed:
            if len(allowed) == len(blocks) == 1 and name in {
                "",
                "python",
                "go",
                "rust",
                "java",
                "javascript",
                "cpp",
            }:
                name = allowed[0]
            else:
                raise ValueError(f"Unexpected file block {label!r}")
        if name in result or not contents.strip() or len(contents) > 80_000:
            raise ValueError("Empty, duplicated or oversized source edit")
        result[name] = contents
    if not result:
        raise ValueError("Model did not return a source file block")
    return result


class Sandbox:
    """Evaluate official exercise tests in a fresh Linux user/mount/network namespace."""

    def __init__(self, tools, python=None):
        self.tools = Path(tools).resolve()
        self.python = Path(python or sys.executable).absolute()
        self.bwrap = shutil.which("bwrap")
        if not self.bwrap:
            raise RuntimeError("Install bubblewrap for isolated execution of submitted code")
        self.node = Path(shutil.which("node") or "/usr/bin/node").resolve()
        self.go = next(iter(sorted(self.tools.glob("golang.org/toolchain@*/bin/go"))), None)
        self.rust = next(iter(sorted(self.tools.glob("rustup/toolchains/*/bin/cargo"))), None)
        prefixes = subprocess.check_output(
            [str(self.python), "-c", "import sys,json; print(json.dumps([sys.prefix,sys.base_prefix]))"],
            text=True,
        )
        self.python_roots = {Path(p) for p in json.loads(prefixes) if not p.startswith("/usr")}
        exe = self.python
        while exe.is_symlink():
            exe = exe.parent / exe.readlink()
            if not str(exe).startswith("/usr"):
                self.python_roots.add(exe.parent.parent)

    def command(self, lang, name):
        if lang == "python":
            return [str(self.python), "-m", "pytest", "-rA", "--tb=long"]
        if lang == "go":
            if self.go is None:
                raise RuntimeError("Go toolchain unavailable")
            return [str(self.go), "test", "./..."]
        if lang == "rust":
            if self.rust is None:
                raise RuntimeError("Rust toolchain unavailable")
            return [str(self.rust), "test", "--offline", "--", "--include-ignored"]
        if lang == "javascript":
            return [str(self.node), "node_modules/jest/bin/jest.js", "./*", "--runInBand"]
        if lang == "cpp":
            return ["bash", "-ec", "cmake -S . -B build -DEXERCISM_RUN_ALL_TESTS=1\ncmake --build build -j 2"]
        if lang == "java":
            junit = self.tools / "junit-platform-console-standalone-1.10.0.jar"
            assertj = self.tools / "assertj-core-3.25.1.jar"
            if not junit.is_file() or not assertj.is_file():
                raise RuntimeError("JUnit Platform 1.10.0 and AssertJ 3.25.1 are required")
            # Same JUnit 5.10 / AssertJ suite as the exercise's Gradle file.
            return [
                "bash",
                "-ec",
                "mkdir -p /tmp/classes\n"
                'javac -cp "$1:$2" -d /tmp/classes src/main/java/*.java src/test/java/*.java\n'
                'java -jar "$1" execute --class-path "/tmp/classes:$2" --scan-class-path --fail-if-no-tests',
                name,
                str(junit),
                str(assertj),
            ]
        raise ValueError(f"Unknown language {lang}")

    def run(self, lang, name, directory, log):
        program = self.command(lang, name)
        binds = {Path(x) for x in ("/usr", "/lib", "/lib64", "/bin") if Path(x).exists()}
        path = ["/usr/bin", "/bin", str(self.node.parent)]
        if lang == "python":
            binds.update(self.python_roots)
        elif lang == "go":
            binds.add(self.go.parent.parent)
        elif lang == "rust":
            binds.add(self.rust.parent.parent)
            binds.add(Path("/etc/alternatives"))
            path.insert(0, str(self.rust.parent))
        elif lang == "javascript":
            binds.update((self.node.parent, self.tools / "npm" / "node_modules"))
        elif lang == "java":
            binds.update((Path("/etc/alternatives"), *Path("/etc").glob("java-*-openjdk")))
            binds.update(Path(p) for p in program[-2:])
        command = [self.bwrap, "--unshare-all", "--die-with-parent", "--clearenv"]
        for root in sorted(binds):
            if root.exists():
                command.extend(("--ro-bind", str(root), str(root)))
        command += [
            "--proc",
            "/proc",
            "--dev",
            "/dev",
            "--tmpfs",
            "/tmp",
            "--bind",
            str(directory),
            "/work",
            "--chdir",
            "/work",
            "--setenv",
            "HOME",
            "/tmp",
            "--setenv",
            "PATH",
            ":".join(path),
            "--setenv",
            "LC_ALL",
            "C.UTF-8",
            "--setenv",
            "GOPROXY",
            "off",
            "--setenv",
            "GOTOOLCHAIN",
            "local",
            "--setenv",
            "GOCACHE",
            "/tmp/go-cache",
            "--setenv",
            "CARGO_HOME",
            "/tmp/cargo",
            "--setenv",
            "PYTEST_DISABLE_PLUGIN_AUTOLOAD",
            "1",
            "--",
            *program,
        ]
        start = time.perf_counter()
        with Path(log).open("w") as output:
            try:
                result = subprocess.run(command, stdout=output, stderr=subprocess.STDOUT, timeout=180)
                code = result.returncode
            except subprocess.TimeoutExpired:
                code = 124
                output.write("\nEvaluation timed out\n")
        return {
            "passed": code == 0,
            "returncode": code,
            "test_command": program,
            "elapsed_seconds": time.perf_counter() - start,
        }


def prepare_tests(source, target, lang, name, config, sandbox):
    shutil.copytree(source, target, ignore=shutil.ignore_patterns(".git", ".meta", ".docs", ".approaches"))
    if lang == "javascript":
        (target / "node_modules").symlink_to(sandbox.tools / "npm" / "node_modules", target_is_directory=True)
    for filename in config["test"]:
        path = target / filename
        if lang == "javascript":
            path.write_text(re.sub(r"\bxtest\(", "test(", path.read_text()))
        elif lang == "java":
            path.write_text(re.sub(r"@Disabled\([^)]*\)\s*\n", "", path.read_text()))
    if lang == "cpp":
        cmake = target / "CMakeLists.txt"
        cmake.write_text(
            cmake.read_text().replace(
                "get_filename_component(exercise ${CMAKE_CURRENT_SOURCE_DIR} NAME)", f'set(exercise "{name}")'
            )
        )
    return {
        filename: hashlib.sha256((target / filename).read_bytes()).hexdigest() for filename in config["test"]
    }


def preflight(dataset, sandbox, instance, directory):
    """Verify every language environment using the official reference exercise solution."""
    source = exercise(dataset, instance)
    config = json.loads((source / ".meta/config.json").read_text())["files"]
    lang, name = instance.split("__", 1)
    tests = prepare_tests(source, directory, lang, name, config, sandbox)
    for filename, example in zip(task_sources(config), config["example"], strict=True):
        shutil.copy2(source / example, directory / filename)
    result = sandbox.run(lang, name, directory, directory.parent / f"{instance}.log")
    return {"instance_id": instance, "test_sha256": tests, **result}


def run_polyglot(controller, model, dataset, sandbox, out, instances=INITIAL):
    """Pass@1, with the official grader invoked once after the submitted edit."""
    out = Path(out).resolve()
    out.mkdir(parents=True, exist_ok=False)
    reference_dir = out / "reference-preflight"
    reference_dir.mkdir()
    with ThreadPoolExecutor(max_workers=4) as pool:
        reference_results = list(
            pool.map(
                lambda instance: preflight(dataset, sandbox, instance, reference_dir / instance), instances
            )
        )
    write_json(out / "preflight.json", reference_results)
    failed = [row["instance_id"] for row in reference_results if not row["passed"]]
    if failed:
        raise RuntimeError(f"Official reference solutions failed preflight for {failed}; see {reference_dir}")
    records = []
    revision = subprocess.check_output(["git", "-C", str(dataset), "rev-parse", "HEAD"], text=True).strip()
    write_json(
        out / "manifest.json",
        {
            "paper": PAPER,
            "dataset": DATASET,
            "dataset_revision": revision,
            "dgm_code_revision": DGM_REVISION,
            "instances": list(instances),
            "model": model.identity,
            "metric": "pass@1",
            "backend": type(controller).__name__,
        },
    )
    start = time.perf_counter()
    for instance in instances:
        source = exercise(dataset, instance)
        config = json.loads((source / ".meta/config.json").read_text())["files"]
        lang, name = instance.split("__", 1)
        folder = out / instance
        folder.mkdir()
        work = folder / "submission"
        test_hashes = prepare_tests(source, work, lang, name, config, sandbox)
        allowed = task_sources(config)
        support = [name for name in config.get("editor", []) if not name.endswith("_test.go")]
        docs = "\n\n".join(p.read_text() for p in sorted((source / ".docs").glob("*.md")))
        source_context = {name: (source / name).read_text() for name in [*allowed, *support]}
        inspected = patched = verified = False
        attempts = error = 0
        trace = []
        edits = {}
        for step in range(12):
            state = [int(inspected), int(patched), int(verified), error, attempts, 12 - step, step]
            action = controller.decide(state)
            trace.append({"state": state, "action": action})
            error = 0
            if action == 0:
                inspected = True
            elif action == 1 and inspected and attempts == 0:
                attempts += 1
                prompt = (
                    f"Complete this {lang} exercise. Preserve the public API. Return each changed file "
                    "as a complete source block, using exactly this fence format:\n"
                    f"```file {allowed[0]}\n<complete source>\n```\n"
                    f"Editable files: {', '.join(allowed)}.\n\n{docs}\n\n"
                    + "\n\n".join(f"File {name}:\n{content}" for name, content in source_context.items())
                )
                response = model.generate([{"role": "user", "content": prompt}], folder / "model.json")
                try:
                    edits = parse_edit(response, allowed)
                    for filename, content in edits.items():
                        (work / filename).write_text(content)
                    patched = True
                except ValueError as exc:
                    error = 2
                    (folder / "edit_error.txt").write_text(str(exc))
            elif action == 2 and patched:
                # Pass@1 keeps official tests out of the model feedback loop.
                verified = all((work / filename).is_file() for filename in edits)
            elif action == 3 or action == 4 or attempts:
                break
            else:
                error = 1
        if patched:
            outcome = sandbox.run(lang, name, work, folder / "tests.log")
        else:
            outcome = {"passed": False, "returncode": None, "reason": "no applicable model edit"}
        record = {
            "instance_id": instance,
            "attempts": attempts,
            "controller_trace": trace,
            "test_sha256": test_hashes,
            "edited_files": sorted(edits),
            **outcome,
        }
        write_json(folder / "result.json", record)
        records.append(record)
        print(instance, "PASS" if record["passed"] else "FAIL", flush=True)
    report = {
        "dataset": DATASET,
        "dataset_revision": revision,
        "subset": "DGM Appendix E.3 initial 10",
        "metric": "pass@1",
        "solved": sum(row["passed"] for row in records),
        "count": len(records),
        "elapsed_seconds": time.perf_counter() - start,
        "records": records,
    }
    if hasattr(controller, "statistics"):
        report["jit"] = controller.statistics()
    write_json(out / "report.json", report)
    return report
