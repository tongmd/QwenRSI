import json

import pytest

from qwenrsi.circuit import load_bundle


def test_bundle_rejects_corrupted_firmware_before_gpu_load(tmp_path):
    (tmp_path / "controller.elf").write_bytes(b"changed")
    (tmp_path / "qwenrsi_config.json").write_text(
        json.dumps({"format": "qwenrsi-sparse-circuit-v1", "files": {"controller.elf": "0" * 64}})
    )
    with pytest.raises(ValueError, match="integrity"):
        load_bundle(tmp_path)


def test_bundle_rejects_path_traversal(tmp_path):
    (tmp_path / "qwenrsi_config.json").write_text(
        json.dumps({"format": "qwenrsi-sparse-circuit-v1", "files": {"../outside": "0" * 64}})
    )
    with pytest.raises(ValueError, match="integrity"):
        load_bundle(tmp_path)
