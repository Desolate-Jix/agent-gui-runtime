from __future__ import annotations

import os
import json
import sys
import time
from pathlib import Path
from uuid import uuid4

import pytest


@pytest.mark.parametrize("fail", [False, True])
def test_managed_acquisition_uses_child_job_and_restores_outer_environment(monkeypatch, tmp_path, fail):
    from app.core import model_server
    from app.learn.hybrid import windows_process_scope as scopes
    from scripts.model_servers import goal_binding_provider_runtimes as runtimes
    created, closed = [], []
    class Scope:
        def __init__(self, name, *, create): created.append(name); self.name = name
        def close(self): closed.append(self.name)
    monkeypatch.setattr(scopes, "WindowsProcessScope", Scope)
    monkeypatch.setenv("AGENT_GUI_HYBRID_PROCESS_SCOPE_NAME", "outer-worker-job")
    monkeypatch.setattr(model_server, "profile_for_stage", lambda *a: {"port": 13240})
    monkeypatch.setattr(runtimes, "_managed_artifact_identity", lambda *a: {})
    def acquire(**kwargs):
        actual = os.environ["AGENT_GUI_HYBRID_PROCESS_SCOPE_NAME"]
        assert actual != "outer-worker-job"
        assert actual == created[0]
        if fail:
            raise RuntimeError("acquisition failed")
        return {"server_process_identity": {"pid": 42, "create_time_ns": 99}}
    monkeypatch.setattr(model_server, "ensure_and_acquire_scoped_qwen_model_lease", acquire)
    if fail:
        with pytest.raises(RuntimeError, match="acquisition failed"):
            runtimes._ManagedIncumbentSession({"timeout_seconds": 5}, tmp_path, tmp_path, "outer-worker-job")
        assert closed == created
    else:
        session = runtimes._ManagedIncumbentSession({"timeout_seconds": 5}, tmp_path, tmp_path, "outer-worker-job")
        monkeypatch.setattr(model_server, "release_scoped_qwen_model_lease", lambda *a: {"status": "released"})
        monkeypatch.setattr(model_server, "_validate_exact_qwen_cleanup_evidence", lambda *a: None)
        assert session.scope_name == created[0]
        assert session.close()["status"] == "released"
        assert closed == created
    assert os.environ["AGENT_GUI_HYBRID_PROCESS_SCOPE_NAME"] == "outer-worker-job"


def test_real_managed_release_keeps_worker_alive_until_stopped_then_outer_reaps_it(tmp_path):
    from app.learn.hybrid import windows_process_scope as scopes
    if not scopes.windows_process_scope_available():
        pytest.skip("real Windows Job primitives unavailable")
    outer_name = scopes.process_scope_name({"run_id": uuid4().hex, "workflow_revision": 1,
        "operation_id": "managed-release-test", "stage": "goal_binding", "stage_execution_id": uuid4().hex}, "qwen")
    root = Path(__file__).resolve().parents[1]
    script = tmp_path / "release_worker.py"
    script.write_text(
        "import json,os,sys,time\nfrom pathlib import Path\n"
        f"sys.path.insert(0,{str(root)!r})\n"
        "from app.core import model_server\n"
        "from app.learn.hybrid import windows_process_scope as scopes\n"
        "from scripts.model_servers import goal_binding_provider_runtimes as runtimes\n"
        "root=Path(sys.argv[1]); outer=sys.argv[2]\n"
        "os.environ['AGENT_GUI_HYBRID_PROCESS_SCOPE_NAME']=outer\n"
        "state={}; saved=[]\n"
        "model_server.profile_for_stage=lambda *a: {'port':1}\n"
        "runtimes._managed_artifact_identity=lambda *a: {}\n"
        "def acquire(**kwargs):\n"
        "    name=os.environ['AGENT_GUI_HYBRID_PROCESS_SCOPE_NAME']\n"
        "    identity=[]\n"
        "    child=scopes.spawn_process_in_scope([sys._base_executable,'-c','import time;time.sleep(60)'],scope_name=name,cwd=root,before_resume=lambda x:identity.append(x))\n"
        "    child.close()\n"
        "    state.update(incarnation={'server_process_identity':identity[0],'server_base_url':'http://127.0.0.1:1','incarnation_id':'fixture'},finalization={'descendant_identities':[]},process_scope_name=name,profile={},leases=[{}],process_scope_acquisition={})\n"
        "    return {'server_process_identity':identity[0]}\n"
        "model_server.ensure_and_acquire_scoped_qwen_model_lease=acquire\n"
        "model_server.model_profile_pid_path=lambda profile:root/'unused.pid'\n"
        "model_server.check_model_server=lambda *a,**kw:{'status':'stopped'}\n"
        "model_server._qwen_public_lease=lambda lease:lease\n"
        "model_server._persist_qwen_termination_proof=lambda state,**kw:saved.append(kw['result'])\n"
        "model_server._finish_qwen_finalization_cleanup=lambda *a,**kw:saved[-1]\n"
        "model_server._validate_exact_qwen_cleanup_evidence=lambda *a:None\n"
        "model_server.release_scoped_qwen_model_lease=lambda *a:model_server._stop_and_finalize_qwen_incarnation(state,token='fixture',revision=1,persist_benchmark_artifacts=False)\n"
        "runtime=runtimes._ManagedIncumbentSession({'timeout_seconds':5},root,root,outer)\n"
        "receipt=runtime.close()\n"
        "scope=scopes.WindowsProcessScope(outer,create=False)\n"
        "payload={'worker_pid':os.getpid(),'server_identity':state['incarnation']['server_process_identity'],'server_scope':state['process_scope_name'],'outer_members_after_release':scope.pids(),'scope_cleanup':receipt['managed_release']['hybrid_process_scope_cleanup']}\n"
        "scope.close()\n"
        "(root/'stopped.json').write_text(json.dumps(payload),encoding='utf-8')\n"
        "time.sleep(60)\n", encoding="utf-8")
    outer = scopes.WindowsProcessScope(outer_name, create=True)
    process = None
    try:
        with (tmp_path / "worker.log").open("wb") as log:
            process = scopes.spawn_process_in_scope([sys.executable, str(script), str(tmp_path), outer_name], scope_name=outer_name, cwd=root, stdout=log, stderr=log)
        deadline = time.monotonic() + 15
        stopped = tmp_path / "stopped.json"
        while not stopped.exists() and process.poll() is None and time.monotonic() < deadline:
            time.sleep(0.02)
        assert stopped.exists(), f"worker exit={process.poll()}; log={(tmp_path / 'worker.log').read_text(encoding='utf-8')}"
        evidence = json.loads(stopped.read_text(encoding="utf-8"))
        assert evidence["server_scope"] != outer_name
        assert evidence["scope_cleanup"]["cleanup_status"] == "verified"
        assert evidence["worker_pid"] in evidence["outer_members_after_release"]
        with pytest.raises(scopes.HybridProcessScopeError, match="absent"):
            scopes._identity_for_pid(evidence["server_identity"]["pid"])
        assert process.poll() is None
        outer.terminate()
        assert process.wait(timeout=5) == 197
    finally:
        outer.terminate()
        if process is not None:
            process.wait(timeout=5)
            process.close()
        outer.close()
