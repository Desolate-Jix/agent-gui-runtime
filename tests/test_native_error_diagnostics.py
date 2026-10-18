"""错误必须保留定位信息，但不得把填写内容写进诊断。"""
import logging
from app.core.failure_diagnostics import log_failure_structure
from app.desktop_review.single_step_coordinator import NativeSingleStepCoordinator


def test_mapping_keeps_safe_stack_without_error_text_or_locals(caplog):
    private_value = 'PRIVATE_TEST_FIELD_MUST_NOT_BE_LOGGED'
    try:
        try:
            raise ValueError(private_value)
        except ValueError as source:
            raise RuntimeError(private_value) from source
    except RuntimeError as error:
        with caplog.at_level(logging.WARNING):
            mapped = NativeSingleStepCoordinator._mapped(error, 'runtime_prepare_failed', 'Preparation failed')
    assert mapped.code == 'runtime_prepare_failed'
    assert 'test_mapping_keeps_safe_stack' in caplog.text
    assert 'ValueError' in caplog.text and 'RuntimeError' in caplog.text
    assert private_value not in caplog.text


def test_cyclic_exception_chain_is_bounded(caplog):
    error = ValueError('PRIVATE_CHAIN')
    error.__cause__ = error
    with caplog.at_level(logging.WARNING):
        log_failure_structure(error, 'synthetic')
    assert caplog.text.count('ValueError') == 1
    assert 'PRIVATE_CHAIN' not in caplog.text
def test_suppressed_context_keeps_locations_without_provider_values(caplog):
    import logging
    from app.core.failure_diagnostics import log_failure_structure

    with caplog.at_level(logging.WARNING):
        try:
            try:
                raise RuntimeError("provider-private-sentinel")
            except RuntimeError:
                raise ValueError("public-private-sentinel") from None
        except ValueError as error:
            log_failure_structure(error, "suppressed_provider")
    assert "RuntimeError" in caplog.text
    assert "test_suppressed_context_keeps_locations_without_provider_values" in caplog.text
    assert "provider-private-sentinel" not in caplog.text
    assert "public-private-sentinel" not in caplog.text
