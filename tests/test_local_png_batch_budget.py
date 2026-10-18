"""本地原件的大图预算不扩展外部上传或新增图片预算。"""

import base64
from copy import deepcopy
from hashlib import sha256
from io import BytesIO
import random

import pytest
from PIL import Image

from app.agent_link import contracts
from app.agent_link.review_baseline import validate_review_baseline


@pytest.fixture(scope="module")
def large_png():
    output = BytesIO()
    Image.frombytes("RGB", (1000, 1000), random.Random(17).randbytes(3_000_000)).save(output, format="PNG")
    raw = output.getvalue()
    assert contracts.MAX_PNG_BYTES < len(raw) < contracts.MAX_LOCAL_PNG_BYTES
    return raw


def batch(raw):
    return {
        "contract_version": "agent_link_v1", "idempotency_key": "local-image",
        "batch_id": "local-image", "title": "large local capture", "learning_outcome": "partial",
        "outcome_reason": "Observation only; no action recorded.",
        "screenshots": [{"screenshot_id": "capture", "png_base64": base64.b64encode(raw).decode("ascii")}],
        "interfaces": [{"interface_id": "screen", "screenshot_id": "capture", "meaning": "screen", "regions": []}],
        "relationships": [], "steps": [], "issues": [],
    }


@pytest.mark.parametrize("allowed", [frozenset(), frozenset({"0" * 64})])
def test_external_and_wrong_hash_still_reject_large_png(large_png, allowed):
    with pytest.raises(contracts.AgentLinkError, match="readable PNG") as error:
        contracts.validate_batch(batch(large_png), existing_png_sha256=allowed)
    assert error.value.code == "invalid_png"


def test_exact_local_hash_preserves_original_png_and_dimensions(large_png):
    digest = sha256(large_png).hexdigest()
    result = contracts.validate_batch(batch(large_png), existing_png_sha256=frozenset({digest}))
    image = result["screenshots"][0]
    assert base64.b64decode(image["png_base64"]) == large_png
    assert (image["sha256"], image["width"], image["height"]) == (digest, 1000, 1000)


def test_local_hash_does_not_bypass_local_budget(large_png, monkeypatch):
    monkeypatch.setattr(contracts, "MAX_LOCAL_PNG_BYTES", len(large_png) - 1)
    with pytest.raises(contracts.AgentLinkError, match="readable PNG"):
        contracts.validate_batch(batch(large_png), existing_png_sha256=frozenset({sha256(large_png).hexdigest()}))


def test_local_hash_does_not_allow_corrupt_png():
    raw = b"not a png"
    with pytest.raises(contracts.AgentLinkError, match="readable PNG"):
        contracts.validate_batch(batch(raw), existing_png_sha256=frozenset({sha256(raw).hexdigest()}))


def test_local_hash_does_not_allow_oversized_dimensions():
    output = BytesIO()
    Image.new("RGB", (4097, 1)).save(output, format="PNG")
    raw = output.getvalue()
    with pytest.raises(contracts.AgentLinkError, match="dimensions"):
        contracts.validate_batch(batch(raw), existing_png_sha256=frozenset({sha256(raw).hexdigest()}))


def test_client_cannot_declare_local_budget(large_png):
    value = batch(large_png)
    value["existing_png_sha256"] = [sha256(large_png).hexdigest()]
    with pytest.raises(contracts.AgentLinkError) as error:
        contracts.validate_batch(value)
    assert error.value.code == "invalid_arguments"


def test_review_baseline_reuses_only_original_validated_png(large_png):
    raw = batch(large_png)
    original = contracts.validate_batch(raw, existing_png_sha256=frozenset({sha256(large_png).hexdigest()}))
    baseline = {"contract_version": "desktop_review_baseline_v1", "task_id": "task",
                "workspace_revision": 1, "source_ref": contracts.canonical_hash(original),
                "batch_sha256": contracts.canonical_hash(original), "batch": raw}
    assert validate_review_baseline(baseline, task_id="task", original_batch=original)[1] == original
    replacement = deepcopy(baseline)
    replacement["batch"]["screenshots"].append({
        "screenshot_id": "new", "png_base64": base64.b64encode(large_png + b"new").decode("ascii")})
    with pytest.raises(contracts.AgentLinkError, match="readable PNG"):
        validate_review_baseline(replacement, task_id="task", original_batch=original)


def test_adoption_dialog_preserves_large_original_without_trusting_receipt_hash(large_png):
    from tests.test_desktop_relearn_adoption_window import _compared, _receipt

    application, _facade, dialog = _compared()
    try:
        shot = dialog.workspace["batch"]["screenshots"][0]
        shot.update(png_base64=base64.b64encode(large_png).decode("ascii"),
                    sha256=sha256(large_png).hexdigest(), width=1000, height=1000)
        receipt = _receipt(dialog)
        assert dialog._valid_adoption(receipt, dialog.comparison)
        altered = deepcopy(receipt)
        raw = large_png + b"replacement"
        altered["snapshot"]["batch"]["screenshots"][0].update(
            png_base64=base64.b64encode(raw).decode("ascii"), sha256=sha256(raw).hexdigest())
        assert not dialog._valid_adoption(altered, dialog.comparison)
    finally:
        dialog.close()
        application.processEvents()
