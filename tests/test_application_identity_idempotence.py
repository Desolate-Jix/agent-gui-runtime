from __future__ import annotations

import pytest

from app.learn.application_identity import normalize_application_identity


@pytest.mark.parametrize("value", [
    {"kind": "native", "display_name": "Editor view", "executable_identity": "editor.exe", "product_name": "Editor Pro"},
    {"kind": "native", "executable_identity": "editor.exe"},
    {"kind": "native", "display_name": "编辑界面", "executable_identity": "editor.exe", "product_name": "中文产品"},
    {"kind": "web", "display_name": "站点", "canonical_origin": "https://www.example.com"},
])
def test_canonical_application_identity_is_stable_across_saver_and_compiler(value):
    first = normalize_application_identity(value)
    assert normalize_application_identity(first) == first


def test_canonical_native_identity_recomputes_key_instead_of_trusting_it():
    identity = normalize_application_identity({"kind": "native", "display_name": "View", "executable_identity": "editor.exe", "product_name": "Editor Pro"})
    identity["identity_key"] = "native:forged.exe"
    result = normalize_application_identity(identity)
    assert result["identity_key"] == "native:editor.exe:editor-pro"
    assert result["artifact_is_authorization"] is False
