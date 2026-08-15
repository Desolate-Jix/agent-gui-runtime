from app.core.browser_navigation_guard import verify_navigation_policy
from app.core.browser_navigation_guard import probe_after_settle


def test_required_probe_unavailable_fails_closed():
    result = verify_navigation_policy(
        {"required": True, "expected_origin": "https://nz.seek.com"},
        123,
        probe=lambda hwnd: {"status": "unavailable"},
    )
    assert result["verified"] is False
    assert result["reason"] == "navigation_probe_unavailable"


def test_unexpected_origin_fails():
    result = verify_navigation_policy(
        {"required": True, "expected_origin": "https://nz.seek.com"},
        123,
        before={"status": "ok", "url": "https://nz.seek.com/a", "tab_count": 1, "tab_ids": ["a"]},
        after={"status": "ok", "url": "https://evil.test/x", "tab_count": 1, "tab_ids": ["a"]},
    )
    assert result["verified"] is False
    assert result["reason"] == "unexpected_origin"


def test_same_origin_requirement_rejects_matching_external_destination():
    result = verify_navigation_policy(
        {
            "required": True,
            "expected_origin": "https://evil.test/apply",
            "require_same_origin_as_before": True,
        },
        123,
        before={"status": "ok", "url": "https://nz.seek.com/job/1", "tab_count": 1, "tab_ids": ["a"]},
        after={"status": "ok", "url": "https://evil.test/apply", "tab_count": 1, "tab_ids": ["a"]},
    )
    assert result["verified"] is False
    assert result["reason"] == "unexpected_origin"
    assert result["expected_origin"] == "https://nz.seek.com"
    assert result["actual_origin"] == "https://evil.test"


def test_matching_origin_passes():
    result = verify_navigation_policy(
        {"required": True, "expected_origin": "https://nz.seek.com", "forbid_new_tab": True},
        123,
        before={"status": "ok", "url": "https://nz.seek.com/a", "tab_count": 1, "tab_ids": ["a"]},
        after={"status": "ok", "url": "https://nz.seek.com/b", "tab_count": 1, "tab_ids": ["a"]},
    )
    assert result["verified"] is True


def test_same_tab_navigation_allows_title_identity_to_change():
    result = verify_navigation_policy(
        {"required": True, "expected_origin": "https://nz.seek.com", "forbid_new_tab": True},
        123,
        before={
            "status": "ok",
            "url": "https://nz.seek.com/job/93615952",
            "tab_count": 1,
            "tab_ids": ["Software Engineer | SEEK"],
            "tab_identity_source": "title_fallback",
        },
        after={
            "status": "ok",
            "url": "https://nz.seek.com/job/93615952/apply",
            "tab_count": 1,
            "tab_ids": ["Choose documents | SEEK"],
            "tab_identity_source": "title_fallback",
        },
    )
    assert result["verified"] is True


def test_same_count_changed_runtime_tab_identity_fails_closed():
    result = verify_navigation_policy(
        {"required": True, "expected_origin": "https://nz.seek.com", "forbid_new_tab": True},
        123,
        before={
            "status": "ok",
            "url": "https://nz.seek.com/job/93615952",
            "tab_count": 1,
            "tab_ids": ["runtime:1"],
            "tab_identity_source": "uia_runtime_id",
        },
        after={
            "status": "ok",
            "url": "https://nz.seek.com/job/93615952/apply",
            "tab_count": 1,
            "tab_ids": ["runtime:2"],
            "tab_identity_source": "uia_runtime_id",
        },
    )
    assert result["verified"] is False
    assert result["reason"] == "unexpected_new_tab"


def test_delayed_external_sample_fails_settle():
    samples = iter([
        {"status": "ok", "url": "https://nz.seek.com/a", "tab_count": 1, "tab_ids": ["a"]},
        {"status": "ok", "url": "https://evil.test/x", "tab_count": 2, "tab_ids": ["a", "b"]},
    ])
    result = probe_after_settle({"expected_origin": "https://nz.seek.com", "settle_timeout_ms": 100}, 1, lambda _: next(samples))
    assert result["verified"] is False
    assert result["reason"] == "unexpected_origin"


def test_transient_new_tab_sample_fails_settle_even_if_origin_matches():
    before = {
        "status": "ok",
        "url": "https://nz.seek.com/job/1",
        "tab_count": 1,
        "tab_ids": ["runtime:1"],
        "tab_identity_source": "uia_runtime_id",
    }
    samples = iter(
        [
            {
                "status": "ok",
                "url": "https://nz.seek.com/job/1/apply",
                "tab_count": 2,
                "tab_ids": ["runtime:1", "runtime:2"],
                "tab_identity_source": "uia_runtime_id",
            },
            {
                "status": "ok",
                "url": "https://nz.seek.com/job/1/apply",
                "tab_count": 1,
                "tab_ids": ["runtime:1"],
                "tab_identity_source": "uia_runtime_id",
            },
        ]
    )
    result = probe_after_settle(
        {
            "expected_origin": "https://nz.seek.com",
            "require_same_origin_as_before": True,
            "forbid_new_tab": True,
            "settle_timeout_ms": 100,
        },
        1,
        lambda _: next(samples),
        before=before,
    )
    assert result["verified"] is False
    assert result["reason"] == "unexpected_new_tab"
