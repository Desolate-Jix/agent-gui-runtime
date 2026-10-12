"""结果认证只重验原始证据，不重复生成上传载荷。"""
from pathlib import Path

import pytest

from app.judgment import evidence
from test_decision_service import arguments, setup_service


def test_binding_only_preserves_binding_without_base64(tmp_path, monkeypatch):
    args = arguments(tmp_path)
    expected, uploaded = evidence.prepare_request(tmp_path, **args)
    assert uploaded[0]["data_url"].startswith("data:image/png;base64,")

    def reject_encoding(*args, **kwargs):
        raise AssertionError("result authentication must not encode upload images")

    monkeypatch.setattr(evidence.base64, "b64encode", reject_encoding)
    actual, omitted = evidence.prepare_request(tmp_path, **args, include_upload=False)
    assert actual == expected
    assert omitted == []


def test_binding_only_still_rejects_changed_image(tmp_path):
    args = arguments(tmp_path)
    path = Path(args["frames"][0]["image_path"])
    path.write_bytes(path.read_bytes() + b"changed")
    with pytest.raises(ValueError, match="decision_evidence_hash_mismatch"):
        evidence.prepare_request(tmp_path, **args, include_upload=False)


def test_saved_result_validation_does_not_encode_or_dispatch(tmp_path, monkeypatch):
    service, calls, client = setup_service(tmp_path, monkeypatch)
    args = arguments(tmp_path)
    try:
        result = service.evaluate(**args)
        assert result["status"] == "completed"
        assert len(calls) == 1

        def reject_encoding(*args, **kwargs):
            raise AssertionError("saved result validation attempted upload encoding")

        monkeypatch.setattr(evidence.base64, "b64encode", reject_encoding)
        assert service.validate_result(result, **args)
        path = Path(args["frames"][0]["image_path"])
        path.write_bytes(path.read_bytes() + b"changed")
        assert not service.validate_result(result, **args)
        assert len(calls) == 1
    finally:
        service.close()
        client.close()
