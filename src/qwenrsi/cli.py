import argparse
import json
import sys
from pathlib import Path

from qwenrsi import __version__


def positive(value):
    n = int(value)
    if n <= 0:
        raise argparse.ArgumentTypeError("Must be a positive integer")
    return n


def main():
    from qwenrsi.swebench import INITIAL as SWE_INITIAL

    ap = argparse.ArgumentParser(description="QwenRSI: editable, compiled agent controllers")
    ap.add_argument("--version", action="version", version=f"qwenrsi {__version__}")
    sub = ap.add_subparsers(dest="command", required=True)
    p = sub.add_parser("build", help="Compile C to native and Qwenputer RV32 firmware")
    p.add_argument("source", type=Path)
    p.add_argument("--out", required=True, type=Path)
    p = sub.add_parser("check", help="Differential native/RV32 conformance")
    p.add_argument("directory", type=Path)
    p = sub.add_parser("replay", help="Recompute a finished search and verify proposal provenance")
    p.add_argument("directory", type=Path)
    p = sub.add_parser("eval", help="Evaluate the synthetic protocol simulator")
    p.add_argument("directory", type=Path)
    p.add_argument("--backend", choices=["native", "reference", "cuda", "cuda-jit"], default="reference")
    p.add_argument("--checkpoint", type=Path)
    p.add_argument("--seed", type=int, default=4409)
    p.add_argument("--count", type=positive, default=64)
    p.add_argument("--out", required=True, type=Path)
    p.add_argument("--device", default="cuda:0")
    p = sub.add_parser("evolve", help="Run frozen Qwen proposals, validation and final test")
    p.add_argument("source", type=Path)
    p.add_argument("--model", required=True)
    p.add_argument("--device", default="cuda:0")
    p.add_argument("--out", required=True, type=Path)
    p.add_argument("--iterations", type=positive, default=3)
    p.add_argument("--count", type=positive, default=64)
    p.add_argument("--test-count", type=positive, default=256)
    p.add_argument("--max-new-tokens", type=positive, default=1536)
    p = sub.add_parser(
        "coding-eval", help="Run real Python repair tasks; test in resource-limited subprocesses"
    )
    p.add_argument("directory", type=Path)
    p.add_argument("--model", required=True)
    p.add_argument("--tasks", required=True, type=Path)
    p.add_argument("--out", required=True, type=Path)
    p.add_argument("--device", default="cuda:0")
    p.add_argument("--backend", choices=["reference", "cuda", "cuda-jit"], default="reference")
    p = sub.add_parser("polyglot", help="Evaluate the DGM paper's initial Aider Polyglot subset")
    p.add_argument("directory", type=Path)
    p.add_argument("--dataset", type=Path, required=True)
    p.add_argument("--tools", type=Path, required=True)
    p.add_argument("--test-python", type=Path)
    p.add_argument("--model", required=True)
    p.add_argument("--device", default="cuda:0")
    p.add_argument("--backend", choices=["cuda", "cuda-jit"], default="cuda-jit")
    p.add_argument("--max-new-tokens", type=positive, default=3072)
    p.add_argument("--out", type=Path, required=True)
    p = sub.add_parser("swe-bench", help="Evaluate the DGM paper's initial SWE-bench Verified subset")
    p.add_argument("directory", type=Path)
    p.add_argument("--dataset", required=True, type=Path)
    p.add_argument("--images", required=True, type=Path)
    p.add_argument("--grader-python", required=True, type=Path)
    p.add_argument("--model", required=True)
    p.add_argument("--device", default="cuda:0")
    p.add_argument("--backend", choices=["cuda", "cuda-jit"], default="cuda-jit")
    p.add_argument("--max-calls", type=positive, default=6)
    p.add_argument("--instances", nargs="+", choices=SWE_INITIAL, default=SWE_INITIAL)
    p.add_argument("--out", required=True, type=Path)
    p = sub.add_parser("profile-jit", help="Profile JIT on recorded paper benchmark controller decisions")
    p.add_argument("directory", type=Path)
    p.add_argument("benchmark_report", type=Path)
    p.add_argument("--out", required=True, type=Path)
    p.add_argument("--device", default="cuda:0")
    p.add_argument("--repeats", type=positive, default=5)
    p = sub.add_parser("audit-circuit", help="Free-running GPU circuit versus reference trace")
    p.add_argument("directory", type=Path)
    p.add_argument("--out", required=True, type=Path)
    p.add_argument("--device", default="cuda:0")
    p.add_argument("--checkpoint", type=Path)
    p.add_argument("--samples", type=positive, default=8)
    p = sub.add_parser("export", help="Export and reload-test a sparse circuit model bundle")
    p.add_argument("directory", type=Path)
    p.add_argument("--out", required=True, type=Path)
    p.add_argument("--device", default="cuda:0")
    p.add_argument("--base-model", default="Qwen/Qwen3.5-4B")
    args = ap.parse_args()
    try:
        if args.command == "build":
            from qwenrsi.compiler import build

            result = build(args.source, args.out)
        elif args.command == "check":
            from qwenrsi.evolve import conformance

            result = conformance(args.directory)
        elif args.command == "replay":
            from qwenrsi.replay import replay

            result = replay(args.directory)
        elif args.command == "eval":
            from qwenrsi.benchmark import evaluate, summary
            from qwenrsi.compiler import NativeController, ReferenceController

            if args.backend in {"cuda", "cuda-jit"}:
                controller = gpu_controller(args, args.checkpoint)
            else:
                controller = {"native": NativeController, "reference": ReferenceController}[args.backend](
                    args.directory
                )
            full = evaluate(controller, seed=args.seed, count=args.count)
            full["backend"] = args.backend
            args.out.write_text(json.dumps(full, indent=2) + "\n")
            result = summary(full)
        elif args.command == "evolve":
            from qwenrsi.evolve import run
            from qwenrsi.model import LocalQwen

            proposer = LocalQwen(args.model, args.device, args.max_new_tokens)
            result = run(
                source=args.source,
                proposer=proposer,
                out=args.out,
                iterations=args.iterations,
                count=args.count,
                test_count=args.test_count,
            )
        elif args.command == "coding-eval":
            from qwenrsi.coding import evaluate_coding
            from qwenrsi.compiler import ReferenceController
            from qwenrsi.model import LocalQwen

            if args.backend in {"cuda", "cuda-jit"}:
                controller = gpu_controller(args)
            else:
                controller = ReferenceController(args.directory)
            model = LocalQwen(args.model, args.device, 1536)
            result = evaluate_coding(controller, model, json.loads(args.tasks.read_text()), args.out)
        elif args.command == "polyglot":
            from qwenrsi.model import LocalQwen
            from qwenrsi.polyglot import Sandbox, run_polyglot

            controller = gpu_controller(args)
            sandbox = Sandbox(args.tools, args.test_python)
            model = LocalQwen(args.model, args.device, args.max_new_tokens)
            report = run_polyglot(controller, model, args.dataset, sandbox, args.out)
            result = {k: v for k, v in report.items() if k != "records"}
        elif args.command == "swe-bench":
            from qwenrsi.model import LocalQwen
            from qwenrsi.swebench import OfficialGrader, run_swebench

            controller = gpu_controller(args)
            grader = OfficialGrader(args.grader_python, args.images)
            model = LocalQwen(args.model, args.device, 2048)
            report = run_swebench(
                controller, model, args.dataset, grader, args.out, args.max_calls, args.instances
            )
            result = {k: v for k, v in report.items() if k != "records"}
        elif args.command == "profile-jit":
            from qwenrsi.jit_profile import profile

            result = profile(args.directory, args.benchmark_report, args.out, args.device, args.repeats)
        elif args.command == "audit-circuit":
            from qwenrsi.circuit import audit

            result, _ = audit(
                args.directory,
                out=args.out,
                device=args.device,
                samples=args.samples,
                checkpoint=args.checkpoint,
            )
        else:
            from qwenrsi.circuit import export

            config, audit_result = export(args.directory, args.out, args.device, args.base_model)
            result = {"config": config, "audit": audit_result}
        print(json.dumps(result, ensure_ascii=False, indent=2))
    except Exception as exc:
        print(f"qwenrsi: {type(exc).__name__}: {exc}", file=sys.stderr)
        sys.exit(1)


def gpu_controller(args, checkpoint=None):
    if args.backend == "cuda-jit":
        from qwenrsi.jit import JITController

        return JITController(args.directory, args.device, checkpoint)
    from qwenrsi.circuit import CircuitController

    return CircuitController(args.directory, args.device, checkpoint)


if __name__ == "__main__":
    main()
