from __future__ import annotations
from pathlib import Path
import pytest
from app.agent_link.service import AgentLinkService
from app.agent_link.store import AgentLinkStore
from app.agent_link.contracts import AgentLinkError
from app.agent_link import mcp_bridge
from types import ModuleType
import sys

REVIEWER='interface-reviewer-token'
class Gateway:
 def __init__(self): self.calls=[]
 def search_interface_memory(self, task, query=''):
  self.calls.append(('search',task,query)); return [{'interface_id':'iface-1','version_id':'version-1','display_name':'Editor'}]
 def get_interface_memory(self, task, interface_id, version_id=None):
  if task != 'task-a': raise AgentLinkError('not_found', 'not found')
  self.calls.append(('get',task,interface_id,version_id)); return {'interface_id':interface_id,'version_id':version_id,'display_name':'Editor'}
 def request_interface_membership(self, task, **kwargs):
  self.calls.append(('membership',task,kwargs)); return {'status':'pending_review','artifact_is_authorization':False,'execute_binding_enabled':False}

def test_interface_capability_is_opt_in_and_task_bound(tmp_path: Path):
 store=AgentLinkStore(tmp_path/'i.json'); service=AgentLinkService(store,REVIEWER)
 conn=service.reviewer_call(REVIEWER,'create_connection',{'task_id':'task-a','agent_name':'agent'})
 try:
  assert 'interface_content' not in service.agent_call(conn['token'],'status',{})
  with pytest.raises(AgentLinkError) as e: service.agent_call(conn['token'],'search_interface_memory',{})
  assert e.value.code=='operation_forbidden'
  gateway=Gateway(); service.bind_interface_content_gateway(REVIEWER,gateway)
  assert service.agent_call(conn['token'],'status',{})['interface_content'] == mcp_bridge._INTERFACE_CONTENT_CAPABILITY
  assert service.agent_call(conn['token'],'search_interface_memory',{'query':'ed'})[0]['interface_id']=='iface-1'
  assert service.agent_call(conn['token'],'get_interface_memory',{'interface_id':'iface-1','version_id':'version-1'})['version_id']=='version-1'
  assert service.agent_call(conn['token'],'get_interface_memory',{'interface_id':'iface-1'})['version_id'] is None
  with pytest.raises(AgentLinkError): service.agent_call(conn['token'],'search_interface_memory',{'task_id':'other'})
  result=service.agent_call(conn['token'],'request_interface_membership',{'workflow_id':'workflow-1','interface_id':'iface-1','version_id':'version-1','expected_revision':1,'expected_sha256':'a'*64,'idempotency_key':'k'})
  assert result['status']=='pending_review'; assert gateway.calls[-1][1]=='task-a'
 finally: store.close()

def test_latest_saved_interface_read_is_optional_and_task_isolated(tmp_path):
 store=AgentLinkStore(tmp_path/'living.json'); service=AgentLinkService(store,REVIEWER)
 gateway=Gateway(); service.bind_interface_content_gateway(REVIEWER,gateway)
 one=service.reviewer_call(REVIEWER,'create_connection',{'task_id':'task-a','agent_name':'a'})
 two=service.reviewer_call(REVIEWER,'create_connection',{'task_id':'task-b','agent_name':'b'})
 try:
  latest=service.agent_call(one['token'],'get_interface_memory',{'interface_id':'iface-1'})
  assert latest['interface_id']=='iface-1'
  explicit=service.agent_call(one['token'],'get_interface_memory',{'interface_id':'iface-1','version_id':'version-1'})
  assert explicit['version_id']=='version-1'
  with pytest.raises(AgentLinkError) as denied:
   service.agent_call(two['token'],'get_interface_memory',{'interface_id':'iface-1'})
  assert denied.value.code == 'not_found'
  service.reviewer_call(REVIEWER,'revoke_connection',{'connection_id':one['connection_id'],'idempotency_key':'revoke-living'})
  with pytest.raises(AgentLinkError) as revoked:
   service.agent_call(one['token'],'get_interface_memory',{'interface_id':'iface-1'})
  assert revoked.value.code=='connection_revoked'
 finally: store.close()

def test_mcp_registers_interface_tools_only_when_advertised(monkeypatch):
 registered={}
 class Server:
  def __init__(self, **_): pass
  def add_tool(self, fn, *, name, description): registered[name]=fn
  def run(self, *, transport): assert transport=='stdio'
 fake=ModuleType('mcp'); server=ModuleType('mcp.server'); server.MCPServer=Server
 monkeypatch.setitem(sys.modules,'mcp',fake); monkeypatch.setitem(sys.modules,'mcp.server',server)
 monkeypatch.setattr(mcp_bridge,'_configuration',lambda:('http://127.0.0.1:1','a'*32))
 monkeypatch.setattr(mcp_bridge,'_call',lambda *_args: {'interface_content':mcp_bridge._INTERFACE_CONTENT_CAPABILITY} if _args[2]=='status' else {})
 mcp_bridge.run_stdio()
 assert {'search_interface_memory','get_interface_memory','request_interface_membership'} <= set(registered)
