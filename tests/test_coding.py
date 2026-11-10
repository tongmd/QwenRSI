from pathlib import Path

from qwenrsi.coding import check, evaluate_coding, python_source


def test_independent_oracle_is_not_model_feedback(tmp_path):
    class Controller:
        def decide(self, state):
            if not state[0]:
                return 0
            if not state[1]:
                return 1
            if not state[2]:
                return 2
            return 3

    class Model:
        def generate(self, messages, record_path):
            assert "secret_value" not in str(messages)
            Path(record_path).write_text("fixture")
            return "```python\ndef f(x):\n    return x + 1\n```"

    task = {
        "id": "addition",
        "description": "Add one",
        "initial_source": "def f(x): return 0",
        "visible_tests": "assert f(1)==2",
        "oracle_tests": "secret_value=17\nassert f(secret_value)==18",
    }
    result = evaluate_coding(Controller(), Model(), [task], tmp_path / "coding")
    assert result["solved"] == 1
    assert result["records"][0]["verified_before_finish"]


def test_visible_success_does_not_override_oracle_failure(tmp_path):
    class Controller:
        def decide(self, state):
            return 0 if not state[0] else 1 if not state[1] else 3

    class Model:
        def generate(self, messages, record_path):
            return "def f(x): return 2"

    task = {
        "id": "constant",
        "description": "Add one",
        "initial_source": "def f(x):return 0",
        "visible_tests": "assert f(1)==2",
        "oracle_tests": "assert f(8)==9",
    }
    result = evaluate_coding(Controller(), Model(), [task], tmp_path / "coding")
    assert result["solved"] == 0


def test_python_process_failure_and_code_extraction():
    assert not check("raise RuntimeError('bad')", "")[0]
    assert python_source("```python\nx=1\n```").strip() == "x=1"
