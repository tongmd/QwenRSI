import argparse
import json
import sys
from pathlib import Path


def positive(value):
    n = int(value)
    if n <= 0:
        raise argparse.ArgumentTypeError("Must be a positive integer")
    return n


def main():
    ap = argparse.ArgumentParser(description="QwenRSI: editable, compiled agent controllers")
    ap.add_argument("--version", action="version", version="qwenrsi 0.1.0")
    sub = ap.add_subparsers(dest="command", required=True)
    p = sub.add_parser("build", help="Compile C to native and Qwenputer RV32 firmware")
    p.add_argument("source", type=Path)
    p.add_argument("--out", required=True, type=Path)
    p = sub.add_parser("check", help="Differential native/RV32 conformance")
    p.add_argument("directory", type=Path)
    p = sub.add_parser("eval", help="Evaluate the synthetic protocol simulator")
    p.add_argument("directory", type=Path)
    p.add_argument("--backend", choices=["native", "reference", "cuda"], default="reference")
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
    p.add_argument("--backend", choices=["reference", "cuda"], default="reference")
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
        elif args.command == "eval":
            from qwenrsi.benchmark import evaluate, summary
            from qwenrsi.compiler import NativeController, ReferenceController

            if args.backend == "cuda":
                from qwenrsi.circuit import CircuitController

                controller = CircuitController(args.directory, args.device, args.checkpoint)
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

            if args.backend == "cuda":
                from qwenrsi.circuit import CircuitController

                controller = CircuitController(args.directory, args.device)
            else:
                controller = ReferenceController(args.directory)
            model = LocalQwen(args.model, args.device, 1536)
            result = evaluate_coding(controller, model, json.loads(args.tasks.read_text()), args.out)
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


if __name__ == "__main__":
    main()
