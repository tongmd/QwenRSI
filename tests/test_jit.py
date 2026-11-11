from pathlib import Path

import numpy as np
import pytest

from qwenrsi.compiler import ReferenceController
from qwenrsi.jit import TraceCompiler, observe, pack_state


@pytest.fixture(scope="module")
def controller():
    root = Path(__file__).resolve().parents[1]
    return ReferenceController(root / "results/tom-20261110-003/evolution/v001")


def compile_path(controller, sample, mode=0):
    trace = controller.machine(sample, mode).run()
    path = observe(controller.machine(sample, mode), trace)
    return TraceCompiler(controller.machine(sample, mode)).compile(path)


def run_circuit(compiled, state, mode=0):
    from chipformer.q35.ir import eval_ffn

    circuit, output = compiled
    packed = pack_state(state, mode)
    values = np.zeros((1, len(circuit.dims)))
    values[0, 0] = 1
    for dim in circuit.token_fns:
        values[0, dim] = circuit.feature_value(dim, packed)
    for node in circuit.nodes:
        eval_ffn(node, values, np.ones(1, dtype=bool), True)
    valid, *action = values[0, output]
    return sum(int(bit) << i for i, bit in enumerate(action)) if valid else None


def test_guard_rejects_other_paths_and_keeps_dynamic_result(controller):
    path = compile_path(controller, [1, 1, 1, 0, 1])
    for attempts in [-(2**31), -1, 0, 4, 5, 8, 2**31 - 1]:
        state = [1, 1, 1, 0, attempts]
        assert run_circuit(path, state) == controller.decide(state)
    assert run_circuit(path, [1, 0, 1, 0, 1]) is None
    assert run_circuit(path, [1, 1, 1, 1, 1]) is None
    assert run_circuit(path, [1, 1, 1, 0, 1], mode=1) is None


def test_selector_signed_comparison(controller):
    path = compile_path(controller, [1, 1, 20, 10], mode=1)
    for state in [[1, 1, 20, 10], [1, 1, -(2**31), 2**31 - 1], [2, -1, 2**31 - 1, -(2**31)]]:
        assert run_circuit(path, state, mode=1) == controller.decide(state, mode=1)
