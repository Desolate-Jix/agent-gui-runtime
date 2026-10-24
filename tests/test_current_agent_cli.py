"""Current-Agent product entry must not infer capability or start another route."""
import io
import json
import pytest

from scripts import execution_client
from tests.test_learning_benchmark_client import FakeSDK


def start_cli(tmp_path, extra):
    sdk, options, output = FakeSDK(), {}, io.StringIO()

    def current_factory(**kwargs):
        options.update(kwargs)
        name = kwargs.pop("client_name")
        capabilities = kwargs.pop("client_vision_capabilities")
        opened = execution_client.ExecutionClient(**kwargs, transport_factory=sdk.transport,
            client_factory=sdk.client, params_factory=lambda **value: value,
            ready_timeout=1, cleanup_timeout=1, poll_interval=.001)
        opened.current_agent_state = {"client_name": name, "capabilities": capabilities,
            "phase": "ready", "input_authorized": opened.allow_actions}
        return opened

    result = execution_client.main(["--data-dir", str(tmp_path), "--current-agent", *extra],
        input_stream=io.StringIO('{"action":"finish"}\n'), output_stream=output,
        client_factory=lambda **kwargs: pytest.fail("legacy or API client selected"),
        current_agent_factory=current_factory)
    return result, options, sdk, [json.loads(line) for line in output.getvalue().splitlines()]


def test_current_agent_cli_defaults_unknown_and_read_only_on_one_connection(tmp_path):
    result, options, sdk, rows = start_cli(tmp_path, [])
    assert result == 0
    assert options["recognition_source"] == "agent_current"
    assert options["allow_actions"] is False and options["prepare_models"] is False
    assert options["api_profile"] is options["decision_profile"] is options["model_directory"] is None
    assert sdk.session_enters == sdk.session_exits == 1
    assert rows[0]["execution_mode"] == "current_agent"
    assert rows[0]["current_agent"]["capabilities"] == {
        "image_transport": "unknown", "current_vision": "unknown"}
    assert rows[0]["actions_enabled"] is False
    assert rows[-1]["cleanup_verified"] is True
    assert rows[-1]["current_agent"]["input_authorized"] is False
    assert not any(args.get("command", {}).get("kind") == "prepare_models" for _, args in sdk.calls)


def test_explicit_client_declarations_and_authorization_are_independent(tmp_path):
    result, options, sdk, rows = start_cli(tmp_path, ["--client-name", "Example Client",
        "--client-image-transport", "supported", "--client-current-vision", "supported"])
    assert result == 0
    assert options["client_name"] == "Example Client"
    assert options["client_vision_capabilities"] == {
        "image_transport": "supported", "current_vision": "supported"}
    assert rows[0]["actions_enabled"] is False
    assert not any(name == "instant_run" for name, _ in sdk.calls)


def test_real_current_agent_adapter_through_jsonl_cli(tmp_path, monkeypatch):
    from scripts.current_agent_client import CurrentAgentClient
    from tests.test_current_agent_client import CurrentSDK

    monkeypatch.setenv("AGENT_GUI_DECISION_PROFILE", str(tmp_path / "ambient-profile.json"))
    sdk, output = CurrentSDK(tmp_path / "runtime"), io.StringIO()

    def current_factory(**kwargs):
        return CurrentAgentClient(**kwargs, transport_factory=sdk.transport,
            client_factory=sdk.client, params_factory=lambda **value: value,
            ready_timeout=1, cleanup_timeout=1, poll_interval=.001)

    result = execution_client.main(["--data-dir", str(tmp_path / "data"), "--current-agent",
        "--client-name", "Example Client", "--client-image-transport", "supported",
        "--client-current-vision", "supported"],
        input_stream=io.StringIO('\n'.join(json.dumps(row) for row in (
            {"action": "agent_status"}, {"action": "agent_complete"}, {"action": "finish"})) + '\n'),
        output_stream=output, current_agent_factory=current_factory)
    rows = [json.loads(line) for line in output.getvalue().splitlines()]
    assert result == 0
    assert [row["event"] for row in rows] == ["ready", "result", "result", "finished"]
    assert rows[0]["current_agent"]["capability_status"] == "eligible"
    assert rows[0]["current_agent"]["actions_enabled"] is False
    assert rows[1]["response"]["current_agent"]["phase"] == "idle"
    assert rows[2]["response"]["current_agent"]["completed"] is True
    assert rows[-1]["current_agent"]["connection_active"] is False
    assert rows[-1]["cleanup_verified"] is True
    assert sdk.session_enters == sdk.session_exits == 1
    assert not sdk.inputs


def test_current_agent_administrator_rejected_before_connection(tmp_path):
    output = io.StringIO()
    result = execution_client.main(["--data-dir", str(tmp_path), "--current-agent", "--administrator"],
        output_stream=output, current_agent_factory=lambda **kw: pytest.fail("transport opened"))
    assert result == 1
    assert json.loads(output.getvalue())["error"]["code"] == "current_agent_administrator_unsupported"


@pytest.mark.parametrize("extra", [
    ["--luna-api"], ["--recognition-source", "local"],
    ["--recognition-source", "external_api"], ["--recognition-source", "agent_delegate"],
    ["--api-profile", "not-read.json"], ["--decision-profile", "not-read.json"],
    ["--delegate-profile", "not-used"], ["--model-directory", "not-used"], ["--prepare-models"],
])
def test_conflicting_route_rejected_before_any_connection(tmp_path, extra):
    output = io.StringIO()
    result = execution_client.main(["--data-dir", str(tmp_path), "--current-agent", *extra],
        output_stream=output, client_factory=lambda **kw: pytest.fail("legacy transport opened"),
        current_agent_factory=lambda **kw: pytest.fail("current transport opened"))
    assert result == 1
    assert json.loads(output.getvalue())["error"]["code"] == "execution_client_current_agent_conflict"


@pytest.mark.parametrize("extra", [
    ["--client-name", "Not a mode selection"],
    ["--client-image-transport", "supported"], ["--client-current-vision", "supported"],
])
def test_capability_flags_cannot_be_silently_ignored_by_legacy_mode(tmp_path, extra):
    output = io.StringIO()
    result = execution_client.main(["--data-dir", str(tmp_path), *extra], output_stream=output,
        client_factory=lambda **kw: pytest.fail("transport opened"))
    assert result == 1
    assert json.loads(output.getvalue())["error"]["code"] == "execution_client_current_agent_option_conflict"


@pytest.mark.parametrize("name", ["", " leading", "trailing ", "line\nbreak", "x" * 129])
def test_client_name_cannot_be_empty_control_text_or_model_capability_guess(tmp_path, name):
    output = io.StringIO()
    result = execution_client.main(["--data-dir", str(tmp_path), "--current-agent", "--client-name", name],
        output_stream=output, current_agent_factory=lambda **kw: pytest.fail("transport opened"))
    assert result == 1
    assert json.loads(output.getvalue())["error"]["code"] == "execution_client_client_name_invalid"
