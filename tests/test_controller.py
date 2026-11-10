from pathlib import Path

import pytest

from qwenrsi.benchmark import evaluate
from qwenrsi.compiler import CompileError, NativeController, ReferenceController, build, state_vector
from qwenrsi.evolve import conformance, improves, run
from qwenrsi.model import extract_proposal

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def controllers(tmp_path_factory):
    out = tmp_path_factory.mktemp("controllers")
    for name in ["baseline", "verified"]:
        build(ROOT / "examples" / f"{name}.c", out / name)
    return out


def test_native_rv32_conformance(controllers):
    for name in ["baseline", "verified"]:
        assert conformance(controllers / name, samples=48)["checked"] == 52


def test_reference_and_native_whole_workflows(controllers):
    native = evaluate(NativeController(controllers / "verified"), seed=5921, count=20)
    rv32 = evaluate(ReferenceController(controllers / "verified"), seed=5921, count=20)
    assert native == rv32
    assert native["solved"] == 20


def test_baseline_is_incomplete(controllers):
    assert evaluate(ReferenceController(controllers / "baseline"), seed=17, count=12)["solved"] == 0


def test_source_language_restrictions(tmp_path):
    p = tmp_path / "bad.c"
    p.write_text("#include <stdlib.h>\nint policy(const int*s){return 0;}")
    with pytest.raises(CompileError):
        build(p, tmp_path / "out")


@pytest.mark.parametrize("state", [[2**31], [0] * 16, ["x"], [True]])
def test_abi_rejects_invalid_input(state):
    with pytest.raises(ValueError):
        state_vector(state)


def test_acceptance_is_external():
    assert improves({"solved": 10, "total_steps": 80}, {"solved": 9, "total_steps": 20})
    assert not improves({"solved": 9, "total_steps": 20}, {"solved": 10, "total_steps": 80})
    assert not improves({"solved": 10, "total_steps": 80}, {"solved": 10, "total_steps": 80})


def test_json_extraction():
    assert extract_proposal('<think>ignore</think>```json\n{"source":"abc"}\n```')["source"] == "abc"
    with pytest.raises(ValueError):
        extract_proposal("not a proposal")


def test_full_evolution_accepts_improvement_and_keeps_holdout_private(tmp_path):
    class TestProposer:
        identity = {"kind": "test-fixture-not-a-model"}

        def propose(self, source, development, history, record_path):
            assert development["seed"] == 1103
            assert "selected_test" not in str(history)
            Path(record_path).write_text('{"test_fixture":true}')
            return {"source": (ROOT / "examples" / "verified.c").read_text()}

    report = run(
        source=ROOT / "examples" / "baseline.c",
        proposer=TestProposer(),
        out=tmp_path / "run",
        iterations=2,
        count=8,
        test_count=12,
    )
    assert report["accepted"] == 1
    assert report["meta_edits_accepted"] == 1
    assert report["baseline"]["solved"] == 0
    assert report["selected_test"]["solved"] == 12
    assert (tmp_path / "run" / "v002" / "decision.json").exists()


def test_malformed_proposal_preserves_current_version(tmp_path):
    class BadProposer:
        identity = {"kind": "test-fixture-not-a-model"}

        def propose(self, *args):
            return {"source": "invalid C"}

    report = run(
        source=ROOT / "examples" / "baseline.c",
        proposer=BadProposer(),
        out=tmp_path / "run",
        iterations=1,
        count=4,
        test_count=4,
    )
    assert report["selected"] == "v000"
    assert report["accepted"] == 0
