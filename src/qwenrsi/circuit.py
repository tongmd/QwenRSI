"""Free-running Qwenputer circuit execution and portable sparse tensor checkpoints.

The Triton executor evaluates compiled Gated DeltaNet/SwiGLU circuit arithmetic.
No reference-machine answer is used to choose tokens. Reference traces are only an audit.
The sparse checkpoint is not a stock Hugging Face language-model checkpoint.
"""

import json
import time
from pathlib import Path

from qwenrsi.compiler import ReferenceController, sha256


class CircuitController(ReferenceController):
    def __init__(self, directory, device="cuda:0", checkpoint=None):
        super().__init__(directory)
        import torch
        from chipformer.rv import core
        from chipformer.rv.tritonexec import Executor2

        self.torch, self.core, self.device = torch, core, device
        self.c = core.build()
        self.ex = Executor2(self.c, 1, device)
        self.x = torch.zeros((1, self.ex.D), device=device)
        self.graph = None
        self.checkpoint = checkpoint
        if checkpoint:
            self._load(checkpoint)

    def _capture(self):
        torch = self.torch
        # Warm and capture before initializing a program; both mutate recurrent state.
        s = torch.cuda.Stream(device=self.device)
        s.wait_stream(torch.cuda.current_stream(self.device))
        with torch.cuda.stream(s):
            for _ in range(3):
                self.ex.step(self.x)
        torch.cuda.current_stream(self.device).wait_stream(s)
        self.graph = torch.cuda.CUDAGraph()
        with torch.cuda.graph(self.graph):
            self.ex.step(self.x)

    def trace(self, state, mode=0, max_tokens=3000):
        from chipformer.rv import spec as S

        torch = self.torch
        with torch.inference_mode(), torch.cuda.device(self.device):
            if self.graph is None:
                self._capture()
            machine = self.machine(state, mode)
            self.core.snapshot(self.c, machine)
            self.ex.reset()
            self.ex.load_init()
            token, trace = S.tok("GO"), [S.tok("GO")]
            for _ in range(max_tokens):
                self.x.copy_(self.ex.embed([token]))
                self.graph.replay()
                token = self.core.predictions(self.c, self.x.cpu().numpy())[0]
                if token < 0:
                    raise RuntimeError("Invalid circuit output token")
                trace.append(token)
                if token == S.tok("HALT"):
                    return trace
        raise TimeoutError("Circuit exceeded trace-token budget")

    def decide(self, state, mode=0):
        from chipformer.rv import spec as S

        trace = self.trace(state, mode)
        output = [S.family(t)[1] for t in trace if S.family(t)[0] == "BYTE"]
        if len(output) != 1:
            raise RuntimeError("Controller did not emit exactly one action")
        return output[0]

    def _weight_tensors(self):
        torch = self.torch
        result = {}
        for i, st in enumerate(self.ex.steps):
            for key, value in st.items():
                if key in {"S", "hist", "heads"}:
                    continue
                if isinstance(value, torch.Tensor):
                    result[f"step.{i}.{key}"] = value.detach().cpu().contiguous()
                elif isinstance(value, list):
                    for j, tensor in enumerate(value):
                        if isinstance(tensor, torch.Tensor):
                            result[f"step.{i}.{key}.{j}"] = tensor.detach().cpu().contiguous()
        return result

    def _load(self, path):
        from safetensors.torch import load_file

        tensors = load_file(str(path), device=self.device)
        expected = self._weight_tensors()
        if tensors.keys() != expected.keys():
            raise ValueError("Checkpoint tensor keys do not match pinned circuit")
        for key, tensor in tensors.items():
            if tensor.shape != expected[key].shape or tensor.dtype != expected[key].dtype:
                raise ValueError(f"Incompatible checkpoint tensor: {key}")
            parts = key.split(".")
            st, name = self.ex.steps[int(parts[1])], parts[2]
            if len(parts) == 4:
                st[name][int(parts[3])].copy_(tensor)
            else:
                st[name].copy_(tensor)

    def save(self, path):
        from safetensors.torch import save_file

        save_file(
            self._weight_tensors(),
            str(path),
            metadata={
                "format": "qwenrsi-sparse-circuit-v1",
                "machine": "RV32IM+Zba",
                "upstream_commit": "0cab57038a8b218dabe481f994174c3437405e3d",
                "note": "Sparse circuit coefficients; firmware provides program state. Not a language model.",
            },
        )


def load_bundle(directory, device="cuda:0"):
    directory = Path(directory)
    config = json.loads((directory / "qwenrsi_config.json").read_text())
    if config.get("format") != "qwenrsi-sparse-circuit-v1":
        raise ValueError("Unsupported model bundle format")
    for name, digest in config["files"].items():
        if Path(name).name != name or sha256(directory / name) != digest:
            raise ValueError(f"Bundle integrity check failed: {name}")
    return CircuitController(directory, device, directory / config["controller_weights"])


def audit(directory, *, out, device="cuda:0", samples=8, checkpoint=None):
    from qwenrsi import enable_chipformer
    from qwenrsi.benchmark import state_samples

    enable_chipformer()
    from chipformer.rv import spec as S

    runner = CircuitController(directory, device, checkpoint)
    records, total, start = [], 0, time.time()
    states = [(s, 0) for s in state_samples(count=samples)]
    states += [(s, 1) for s in [[0, 64, 100, 300], [64, 0, 300, 100], [64, 64, 400, 300]]]
    for state, mode in states:
        reference = runner.machine(state, mode)
        expected = reference.run(10000)
        generated = runner.trace(state, mode)
        if generated != expected:
            first = next(
                (i for i, (a, b) in enumerate(zip(generated, expected)) if a != b),
                min(len(generated), len(expected)),
            )
            raise AssertionError(f"Circuit/reference divergence at position {first}")
        total += len(generated)
        records.append(
            {
                "state": state,
                "mode": mode,
                "tokens": len(generated),
                "action": [S.family(t)[1] for t in generated if S.family(t)[0] == "BYTE"][0],
                "mismatches": 0,
            }
        )
    result = {
        "backend": "qwenputer-triton-executor-v2",
        "device": device,
        "gpu": runner.torch.cuda.get_device_name(device),
        "sampled_runs": len(records),
        "free_running_tokens": total,
        "mismatches": 0,
        "elapsed_seconds": time.time() - start,
        "records": records,
        "elf_sha256": sha256(Path(directory) / "controller.elf"),
        "circuit": runner.c.stats(),
        "checkpoint": str(checkpoint) if checkpoint else None,
    }
    Path(out).write_text(json.dumps(result, indent=2) + "\n")
    return result, runner


def export(directory, out, device="cuda:0", base_model="Qwen/Qwen3.5-4B"):
    import shutil

    out = Path(out)
    out.mkdir(parents=True, exist_ok=False)
    runner = CircuitController(directory, device)
    runner.save(out / "controller.safetensors")
    for name in ["source.c", "controller.elf", "manifest.json"]:
        shutil.copy2(Path(directory) / name, out / name)
    config = {
        "format": "qwenrsi-sparse-circuit-v1",
        "qwenrsi_version": "0.1.0",
        "base_model": base_model,
        "base_weights_modified": False,
        "controller_weights": "controller.safetensors",
        "program_state": "controller.elf",
        "circuit": runner.c.stats(),
        "abi": "qwenrsi-controller-v1",
        "upstream_commit": "0cab57038a8b218dabe481f994174c3437405e3d",
        "files": {n: sha256(out / n) for n in ["controller.safetensors", "controller.elf", "source.c"]},
    }
    (out / "qwenrsi_config.json").write_text(json.dumps(config, indent=2) + "\n")
    # Crucially test the file read back from disk, not only the in-memory pre-export circuit.
    result, _ = audit(
        out, out=out / "circuit_audit.json", device=device, checkpoint=out / "controller.safetensors"
    )
    return config, result
