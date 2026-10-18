from pathlib import Path
import pytest
from app.desktop_review.workflow_membership import WorkflowMembershipService
from app.desktop_review.graph_revision import DesktopReviewError
from test_formal_graph_exact_review import _runtime, TASK, BATCH, TOKEN
def test_create_attach_detach(tmp_path:Path):
 store, service, facade, _, content = _real(tmp_path)
 try:
  graph = facade.create_workflow_graph('Composition', TASK)
  out = facade.request_interface_membership(TASK, graph['logical_workflow_id'], content['interface_id'],
      content['version_id'], graph['revision'], graph['content_sha256'], 'agent-attach')
  assert out['status'] == 'saved' and out['review_required'] is False
  assert out['revision'] == 2
  assert not facade.load_graph_revision(graph['logical_workflow_id'])['graph']['edges']
 finally:
  facade.close(); store.close()

def _real(tmp_path):
 store, service, facade, original = _runtime(tmp_path)
 content = facade.import_interface_content(TASK, BATCH, 'state-a')
 return store, service, facade, original, content

def test_real_create_same_title_and_list(tmp_path):
 store, service, facade, _, _ = _real(tmp_path)
 try:
  first=facade.create_workflow_graph('same', TASK); second=facade.create_workflow_graph('same', TASK)
  assert first['logical_workflow_id'] != second['logical_workflow_id']
  assert len(facade.list_workflow_graphs()) == 2
 finally: facade.close(); store.close()

def test_real_g1_g2_pin_v1_without_edges(tmp_path):
 store, service, facade, _, content = _real(tmp_path)
 try:
  g1=facade.create_workflow_graph('g1', TASK); g2=facade.create_workflow_graph('g2', TASK)
  for g in (g1,g2):
   out=facade.attach_interface_to_workflow(g['logical_workflow_id'],content['interface_id'],content['version_id'],1,g['content_sha256'],'a-'+g['logical_workflow_id'])
   assert out['graph']['edges']==[] and out['source_refs']['interfaces'][0]['version_id']==content['version_id']
 finally: facade.close(); store.close()

def test_real_v2_does_not_rewrite_v1_pins(tmp_path):
 store, service, facade, _, content = _real(tmp_path)
 try:
  g=facade.create_workflow_graph('g', TASK); v1=facade.attach_interface_to_workflow(g['logical_workflow_id'],content['interface_id'],content['version_id'],1,g['content_sha256'],'v1')
  v2=facade.save_interface_content(content['interface_id'],1,content['content_sha256'],{'meaning':'changed'},'save-v2')
  assert v2['version_id'] != content['version_id']
  current=facade.load_graph_revision(g['logical_workflow_id'],2)
  assert current['source_refs']['interfaces'][0]['version_id']==content['version_id']
 finally: facade.close(); store.close()

def test_real_detach_reopen_preserves_other_graph_and_content(tmp_path):
 store, service, facade, _, content = _real(tmp_path)
 g1=facade.create_workflow_graph('g1', TASK); g2=facade.create_workflow_graph('g2', TASK)
 g1=facade.attach_interface_to_workflow(g1['logical_workflow_id'],content['interface_id'],content['version_id'],1,g1['content_sha256'],'d1')
 g2=facade.attach_interface_to_workflow(g2['logical_workflow_id'],content['interface_id'],content['version_id'],1,g2['content_sha256'],'d2')
 g1=facade.detach_interface_from_workflow(g1['logical_workflow_id'],content['interface_id'],content['version_id'],2,g1['content_sha256'],'d3')
 facade.close(); store.close()
 from app.desktop_review.workspace import NativeReviewFacade
 facade=NativeReviewFacade(service,TOKEN,tmp_path/'fresh-artifacts')
 try:
  assert facade.load_graph_revision(g2['logical_workflow_id'],2)['source_refs']['interfaces']
  assert facade.load_interface_content(content['interface_id'],content['version_id'])['version_id']==content['version_id']
 finally: facade.close(); store.close()

def test_real_batch_graph_edges_unchanged(tmp_path):
 store, service, facade, _, content = _real(tmp_path)
 try:
  batch=facade.create_graph_revision(TASK,BATCH,0,{'open-result':['rel-open']}); edges=batch['graph']['edges']
  out=facade.attach_interface_to_workflow(batch['logical_workflow_id'],content['interface_id'],content['version_id'],1,batch['content_sha256'],'batch-attach')
  assert out['graph']['edges']==edges
 finally: facade.close(); store.close()

def test_real_stale_and_idempotency_are_atomic(tmp_path):
 store, service, facade, _, content = _real(tmp_path)
 try:
  g=facade.create_workflow_graph('g',TASK)
  with pytest.raises(DesktopReviewError): facade.attach_interface_to_workflow(g['logical_workflow_id'],content['interface_id'],content['version_id'],2,g['content_sha256'],'k')
  out=facade.attach_interface_to_workflow(g['logical_workflow_id'],content['interface_id'],content['version_id'],1,g['content_sha256'],'k')
  with pytest.raises(DesktopReviewError): facade.attach_interface_to_workflow(g['logical_workflow_id'],'wrong',content['version_id'],1,g['content_sha256'],'k')
  assert facade.load_graph_revision(g['logical_workflow_id'],None)['revision']==2
 finally: facade.close(); store.close()

def test_real_evidence_and_interface_node_edit_rejected(tmp_path):
 store, service, facade, _, content = _real(tmp_path)
 try:
  g=facade.create_workflow_graph('g',TASK); out=facade.attach_interface_to_workflow(g['logical_workflow_id'],content['interface_id'],content['version_id'],1,g['content_sha256'],'ev')
  node=out['graph']['nodes'][0]
  with pytest.raises(DesktopReviewError): facade.apply_graph_edit(out['logical_workflow_id'],2,out['content_sha256'],{'type':'update_node_meaning','node_id':node['node_id'],'meaning':'bad'},'edit')
  batch=facade.create_graph_revision(TASK,BATCH,0,{'open-result':['rel-open']}); original=next(n for n in batch['graph']['nodes'] if n.get('external_interface_id')=='state-a')
  ev=facade.load_graph_node_evidence(batch['logical_workflow_id'],1,batch['content_sha256'],original['node_id'])
  assert ev['screenshot']['sha256']
 finally: facade.close(); store.close()
