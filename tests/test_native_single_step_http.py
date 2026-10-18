import asyncio
import hashlib
import json
import sys

import httpx
import pytest

from app.agent_link.http_app import create_agent_link_app
from app.desktop_review.single_step import (
    NativeSingleStepError,
    OwnedSingleStepClient,
    validate_single_step_response,
)
from tests.test_agent_runtime_contracts_v1 import _receipt_payload


TOKEN = "execution-role-secret-for-tests"
CONFIRMATION = "grounded-confirmation." + "a" * 64


class _Service:
    def agent_call(self, *_args):
        raise AssertionError("Agent Link must not handle execution")


class _Execution:
    def __init__(self):
        self.calls = 0

    def execute_server(self, *, confirmation_id):
        if confirmation_id != CONFIRMATION:
            raise NativeSingleStepError(
                "confirmation_not_attached", "confirmation is not attached"
            )
        self.calls += 1
        return {
            "contract_version": "native_single_step_response_v1",
            "confirmation_id": confirmation_id,
            "kind": "decision",
            "payload": {
                "status": "REJECTED",
                "reason_code": "grounded_confirmation_stale",
                "confirmation_id": confirmation_id,
            },
            "artifact_is_authorization": False,
        }


async def _post(app, *, headers, content):
    transport = httpx.ASGITransport(app=app, client=("127.0.0.1", 44000))
    async with httpx.AsyncClient(
        transport=transport, base_url="http://127.0.0.1", trust_env=False
    ) as client:
        return await client.post(
            "/action/execute_recognition_plan", headers=headers, content=content
        )


def _app(execution):
    return create_agent_link_app(
        _Service(),
        reviewer_http=False,
        execution_controller=execution,
        execution_token_digest=hashlib.sha256(TOKEN.encode()).hexdigest(),
    )


def test_canonical_http_accepts_exact_role_and_strict_body_once():
    execution = _Execution()
    response = asyncio.run(_post(
        _app(execution),
        headers={"authorization": f"Bearer {TOKEN}", "content-type": "application/json"},
        content=json.dumps({"confirmation_id": CONFIRMATION}).encode(),
    ))
    assert response.status_code == 200
    assert response.json()["confirmation_id"] == CONFIRMATION
    assert execution.calls == 1


@pytest.mark.parametrize("case", [
    "missing_auth", "wrong_auth", "origin", "content_type", "extra",
    "duplicate_json", "nonfinite", "too_large", "foreign",
])
def test_canonical_http_rejects_before_runtime(case):
    execution = _Execution()
    headers = {
        "authorization": f"Bearer {TOKEN}",
        "content-type": "application/json",
    }
    body = json.dumps({"confirmation_id": CONFIRMATION}).encode()
    if case == "missing_auth":
        headers.pop("authorization")
    elif case == "wrong_auth":
        headers["authorization"] = "Bearer different-role-token"
    elif case == "origin":
        headers["origin"] = ""
    elif case == "content_type":
        headers["content-type"] = "text/plain"
    elif case == "extra":
        body = json.dumps({"confirmation_id": CONFIRMATION, "approved": True}).encode()
    elif case == "duplicate_json":
        body = (
            '{"confirmation_id":"' + CONFIRMATION
            + '","confirmation_id":"' + CONFIRMATION + '"}'
        ).encode()
    elif case == "nonfinite":
        body = b'{"confirmation_id":NaN}'
    elif case == "too_large":
        body = b"{" + b" " * 4097 + b"}"
    elif case == "foreign":
        body = json.dumps({"confirmation_id": "grounded-confirmation." + "b" * 64}).encode()
    response = asyncio.run(_post(_app(execution), headers=headers, content=body))
    assert response.status_code != 200
    assert set(response.json()["error"]) == {"code", "message", "result_unknown"}
    assert response.json()["error"]["result_unknown"] is False
    assert execution.calls == 0


def test_canonical_http_rejects_duplicate_authorization_before_runtime():
    execution = _Execution()
    response = asyncio.run(_post(
        _app(execution),
        headers=[
            ("authorization", f"Bearer {TOKEN}"),
            ("authorization", f"Bearer {TOKEN}"),
            ("content-type", "application/json"),
        ],
        content=json.dumps({"confirmation_id": CONFIRMATION}).encode(),
    ))
    assert response.status_code == 401
    assert response.json()["error"]["result_unknown"] is False
    assert execution.calls == 0


def test_owned_client_rejects_duplicate_response_json_as_unknown(monkeypatch):
    class _Client:
        def __init__(self, **_kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def post(self, *_args, **_kwargs):
            return httpx.Response(
                200,
                content=b'{"contract_version":"native_single_step_response_v1",'
                b'"contract_version":"native_single_step_response_v1",'
                b'"confirmation_id":"' + CONFIRMATION.encode() + b'",'
                b'"kind":"decision","payload":{"status":"REJECTED",'
                b'"reason_code":"grounded_confirmation_stale",'
                b'"confirmation_id":"' + CONFIRMATION.encode() + b'"},'
                b'"artifact_is_authorization":false}',
            )

    monkeypatch.setattr(httpx, "Client", _Client)
    client = OwnedSingleStepClient(
        base_url="http://127.0.0.1:49123",
        token=TOKEN,
        confirmation_id=CONFIRMATION,
    )
    with pytest.raises(NativeSingleStepError) as raised:
        client.execute(confirmation_id=CONFIRMATION)
    assert raised.value.code == "invalid_response"
    assert raised.value.result_unknown is True


def test_canonical_http_rejects_excessively_nested_json_before_runtime():
    execution = _Execution()
    response = asyncio.run(_post(
        _app(execution),
        headers={
            "authorization": f"Bearer {TOKEN}",
            "content-type": "application/json",
        },
        content=b"[" * 2000 + b"]" * 2000,
    ))
    assert response.status_code == 400
    assert response.json() == {
        "error": {
            "code": "invalid_json",
            "message": "request body must be strict JSON",
            "result_unknown": False,
        }
    }
    assert execution.calls == 0


def test_owned_client_wraps_parse_success_receipt_validation_recursion(monkeypatch):
    receipt = json.dumps(_receipt_payload(), separators=(",", ":"))
    nested = "[" * 990 + "0" + "]" * 990
    receipt = receipt[:-1] + ',"x":' + nested + "}"
    content = (
        '{"contract_version":"native_single_step_response_v1",'
        f'"confirmation_id":"{CONFIRMATION}","kind":"receipt",'
        f'"payload":{receipt},"artifact_is_authorization":false}}'
    ).encode("utf-8")
    recursion_limit = sys.getrecursionlimit()
    try:
        sys.setrecursionlimit(5000)
        parsed = json.loads(content)
    finally:
        sys.setrecursionlimit(recursion_limit)
    with pytest.raises(NativeSingleStepError) as direct:
        validate_single_step_response(parsed, confirmation_id=CONFIRMATION)
    assert direct.value.result_unknown is True
    requests = []

    def respond(request):
        requests.append(request)
        return httpx.Response(200, content=content)

    original = httpx.Client
    monkeypatch.setattr(
        httpx,
        "Client",
        lambda **kwargs: original(transport=httpx.MockTransport(respond), **kwargs),
    )
    client = OwnedSingleStepClient(
        base_url="http://127.0.0.1:49123",
        token=TOKEN,
        confirmation_id=CONFIRMATION,
    )
    with pytest.raises(NativeSingleStepError) as raised:
        client.execute(confirmation_id=CONFIRMATION)
    assert raised.value.code == "invalid_response"
    assert raised.value.result_unknown is True
    assert len(requests) == 1
