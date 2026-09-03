from pathlib import Path


def test_model_test_root_is_exact_utf8_literal_across_production_paths() -> None:
    import app.learn.hybrid.goal_binding_model_callers as callers
    import app.learn.hybrid.model_test_storage as storage
    import scripts.fetch_goal_binding_model as fetch

    expected = r"E:\模型测试"
    assert str(storage.MODEL_TEST_ROOT) == expected
    assert str(callers._MODEL_TEST_ROOT) == expected
    assert callers._MODEL_TEST_ROOT is storage.MODEL_TEST_ROOT
    assert str(fetch.MODEL_TEST_ROOT) == expected
    for value in (storage.MODEL_TEST_ROOT, callers._MODEL_TEST_ROOT, fetch.MODEL_TEST_ROOT):
        assert "�" not in str(value)
        assert "ï¿½" not in str(value)


def test_model_test_root_error_contract_preserves_exact_utf8_text() -> None:
    import app.learn.hybrid.model_test_storage as storage

    wrong_root = Path(r"E:\not-model-tests")
    try:
        storage._require_model_test_root(wrong_root)
    except ValueError as exc:
        message = str(exc)
    else:
        raise AssertionError("expected pinned-root validation to reject an unapproved root")
    assert message == "model-test write operations are pinned to E:\\模型测试"
    assert "�" not in message
    assert "ï¿½" not in message
