from __future__ import annotations

from scripts.start_test_panel import (
    PortProbe,
    choose_runtime_port,
    is_agent_runtime_health,
)


def test_health_payload_must_identify_agent_gui_runtime() -> None:
    assert is_agent_runtime_health(
        {
            "success": True,
            "data": {"status": "ok", "service": "agent-gui-runtime"},
        }
    )
    assert not is_agent_runtime_health({"success": True, "data": {"service": "other-app"}})
    assert not is_agent_runtime_health({"detail": "Not Found"})


def test_choose_runtime_port_reuses_agent_runtime_after_foreign_service() -> None:
    probes = [
        PortProbe(port=8000, status="foreign_service", detail="HTTP 404"),
        PortProbe(port=8765, status="agent_runtime", detail="healthy"),
    ]

    selection = choose_runtime_port(probes)

    assert selection.port == 8765
    assert selection.should_start is False


def test_choose_runtime_port_skips_foreign_service_and_uses_free_port() -> None:
    probes = [
        PortProbe(port=8000, status="foreign_service", detail="unexpected service"),
        PortProbe(port=8765, status="free", detail="connection refused"),
    ]

    selection = choose_runtime_port(probes)

    assert selection.port == 8765
    assert selection.should_start is True


def test_choose_runtime_port_prefers_existing_runtime_over_earlier_free_port() -> None:
    probes = [
        PortProbe(port=8000, status="free", detail="connection refused"),
        PortProbe(port=8765, status="agent_runtime", detail="healthy"),
    ]

    selection = choose_runtime_port(probes)

    assert selection.port == 8765
    assert selection.should_start is False


def test_choose_runtime_port_rejects_when_all_ports_are_foreign() -> None:
    probes = [
        PortProbe(port=8000, status="foreign_service", detail="unexpected service"),
        PortProbe(port=8765, status="foreign_service", detail="unexpected service"),
    ]

    try:
        choose_runtime_port(probes)
    except RuntimeError as exc:
        assert "No available panel port" in str(exc)
        assert "8000" in str(exc)
        assert "8765" in str(exc)
    else:
        raise AssertionError("choose_runtime_port should reject fully occupied ports")
