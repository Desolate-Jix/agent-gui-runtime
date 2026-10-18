from pathlib import Path
import pytest
from fastapi.testclient import TestClient
from app.agent_link.http_app import create_agent_link_app
from app.agent_link.contracts import AgentLinkError
from app.agent_link.service import AgentLinkService
from test_formal_graph_exact_review import _runtime, TASK, BATCH, TOKEN
from app.agent_link import mcp_bridge
from types import ModuleType
import sys

def test_real_living_interface_latest_explicit_and_asgi(tmp_path: Path):
 store, service, facade, _ = _runtime(tmp_path)
 try:
  first = facade.import_interface_content(TASK, BATCH, 'state-a')
  second = facade.save_interface_content(first['interface_id'], 1, first['content_sha256'], {'meaning':'updated'}, 'living-v2')
  service.bind_interface_content_gateway(TOKEN, facade)
  conn = service.reviewer_call(TOKEN, 'create_connection', {'task_id':TASK, 'agent_name':'living'})
  client = TestClient(create_agent_link_app(service), client=('127.0.0.1', 50271))
  latest = client.post('/agent/get_interface_memory', headers={'Authorization':'Bearer '+conn['token']}, json={'interface_id':first['interface_id']})
  assert latest.status_code == 200 and latest.json()['version_id'] == second['version_id']
  old = client.post('/agent/get_interface_memory', headers={'Authorization':'Bearer '+conn['token']}, json={'interface_id':first['interface_id'], 'version_id':first['version_id']})
  assert old.status_code == 200 and old.json()['version_id'] == first['version_id']
  assert first['review_status'] != 'reviewed'
  bad = client.post('/agent/get_interface_memory', headers={'Authorization':'Bearer '+conn['token']}, json={'interface_id':first['interface_id'], 'version_id':3})
  assert bad.status_code == 400
  unknown = client.post('/agent/get_interface_memory', headers={'Authorization':'Bearer '+conn['token']}, json={'interface_id':first['interface_id'], 'extra':'x'})
  assert unknown.status_code == 400
  other = service.reviewer_call(TOKEN, 'create_connection', {'task_id':'other-task', 'agent_name':'other'})
  denied = client.post('/agent/get_interface_memory', headers={'Authorization':'Bearer '+other['token']}, json={'interface_id':first['interface_id']})
  assert denied.status_code in (400,409)
  service.reviewer_call(TOKEN, 'revoke_connection', {'connection_id':conn['connection_id'], 'idempotency_key':'living-revoke'})
  revoked = client.post('/agent/get_interface_memory', headers={'Authorization':'Bearer '+conn['token']}, json={'interface_id':first['interface_id']})
  assert revoked.status_code == 400
 finally:
  facade.close(); store.close()

def test_mcp_interface_tool_forwards_optional_and_explicit_version(monkeypatch):
 registered = {}; calls = []
 class Server:
  def __init__(self, **_): pass
  def add_tool(self, fn, *, name, description): registered[name] = fn
  def run(self, *, transport): assert transport == 'stdio'
 fake=ModuleType('mcp'); server=ModuleType('mcp.server'); server.MCPServer=Server
 monkeypatch.setitem(sys.modules,'mcp',fake); monkeypatch.setitem(sys.modules,'mcp.server',server)
 monkeypatch.setattr(mcp_bridge,'_configuration',lambda:('http://127.0.0.1:1','a'*32))
 def call(*args):
  calls.append((args[2], args[3])); return {'interface_content':mcp_bridge._INTERFACE_CONTENT_CAPABILITY} if args[2]=='status' else {'version_id': args[3].get('version_id')}
 monkeypatch.setattr(mcp_bridge,'_call',call)
 mcp_bridge.run_stdio()
 registered['get_interface_memory']('iface-1')
 registered['get_interface_memory']('iface-1','version-1')
 assert calls[-2:] == [('get_interface_memory', {'interface_id':'iface-1','version_id':None}), ('get_interface_memory', {'interface_id':'iface-1','version_id':'version-1'})]
