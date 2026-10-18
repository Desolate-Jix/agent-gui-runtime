"""原生列表的只读三态与竞态契约，不创建实机窗口。"""
from types import SimpleNamespace as NS
import pytest
from app.agent import windows_form_control_reader as shared
from app.agent import windows_row_selection_reader as reader
from pywinauto.uia_defines import NoPatternInterfaceError

TARGET = {'handle': 10, 'process_id': 20}
IDENTITY = {'contract_version': 'windows_native_identity_observation_v1', 'provider': 'windows_native_identity', 'status': 'observed', 'target_window_handle': 10, 'process_id': 20, 'process_create_time': 123.0, 'executable_path': 'C:/fixture.exe'}

def rect(x=100,y=200,w=600,h=500):
    return NS(left=x,top=y,right=x+w,bottom=y+h)

class Node:
    def __init__(self,kind,rid,name='',children=(),selected=None,hwnd=0,cls=''):
        self.element_info=NS(control_type=kind,runtime_id=list(rid),name=name,process_id=20,rectangle=rect(120,230,120,25))
        self.element_info.handle=hwnd or None
        self.element_info.element=self
        self.CurrentProcessId=20;self.CurrentFrameworkId='Win32';self.CurrentNativeWindowHandle=hwnd;self.CurrentClassName=cls;self.CurrentIsPassword=0;self.CurrentHasKeyboardFocus=0
        self.nodes=list(children);self.parent_node=None
        for node in self.nodes:node.parent_node=self
        if kind=='ListItem':self.iface_selection_item=NS(CurrentIsSelected=selected)
    def parent(self):return self.parent_node
    def top_level_parent(self):return NS(element_info=NS(handle=10))
    def is_visible(self):return True
    def is_enabled(self):return True
    def click_input(self,*args,**kwargs):pytest.fail('不得输入')
    def __getattr__(self,name):
        if name=='iface_value':raise NoPatternInterfaceError()
        raise AttributeError(name)

class Value:
    CurrentIsReadOnly=0
    @property
    def CurrentValue(self):pytest.fail('不得读取编辑文字')
    def SetValue(self,*args):pytest.fail('不得输入')

def scene(selected=False,editing=False):
    virtual=Node('Edit',(3,1),'folder')
    virtual.CurrentHasKeyboardFocus=1
    row=Node('ListItem',(3,),'folder',[virtual],selected=selected)
    controls=[row]
    if editing:
        edit=Node('Edit',(4,),hwnd=44,cls='Edit');edit.iface_value=Value();edit.CurrentHasKeyboardFocus=1;controls.insert(0,edit)
    listing=Node('List',(2,),children=controls,hwnd=22,cls='SysListView32')
    return listing,row

@pytest.fixture
def build(monkeypatch):
    def factory(*lists,mutate=None,identities=None,desktop_parent=False):
        from app.agent import windows_text_field_reader as text_reader
        monkeypatch.setattr(text_reader, "_native_root_handle", lambda hwnd: {10:10,22:10,44:10,77:10,88:10,99:10}.get(hwnd))
        root=Node('Window',(1,),children=lists,hwnd=10)
        if desktop_parent:
            class Desktop:
                element_info=NS(runtime_id=[999])
                @property
                def nodes(self):pytest.fail('不得扫描窗口外Desktop')
                @property
                def parent_node(self):pytest.fail('不得访问窗口外Desktop父边')
            root.parent_node=Desktop()
        owner=NS(active=False,calls=0)
        def call(fn):
            owner.calls+=1;owner.active=True
            try:return fn()
            finally:owner.active=False
        owner.call=call
        samples=list(identities or [IDENTITY]*5)
        def identity(_):
            assert owner.active
            return samples.pop(0)
        windows=NS(get_bound_window=lambda:NS(handle=10,process_id=20,rect=rect()))
        co=NS(_owner=owner,_windows=lambda:windows)
        walker=NS(GetParentElement=lambda node:node.parent_node)
        scans=[0]
        def finite(node):
            assert owner.active
            if node is root:
                scans[0]+=1
                if scans[0]==2 and mutate:mutate(root)
            return list(node.nodes)
        monkeypatch.setattr(shared,'_finite_children',finite)
        monkeypatch.setattr(shared,'_same_element',lambda a,b:a is b)
        monkeypatch.setattr(shared,'_native_owned_popups',lambda *_:[])
        monkeypatch.setattr(shared,'_uia_factory',lambda:(NS(window=lambda **kw:NS(wrapper_object=lambda:root)),walker,lambda raw:raw))
        monkeypatch.setattr(reader,'WindowsNativeIdentityReader',lambda **kw:NS(read_identity=identity))
        return co
    return factory

@pytest.mark.parametrize('selected,editing',[(False,False),(True,False),(True,True)])
def test_three_states_and_owner_no_value_read(build,selected,editing):
    listing,row=scene(selected,editing);co=build(listing)
    result=reader.read_row_selection(co,TARGET,'folder')
    assert result['selected'] is selected and result['editing'] is editing and result['state_available'] is True
    assert result['kind']=='row_selection' and result['control_type']=='ListItem'
    assert result['runtime_id']==[3] and result['bbox']=={'x':20,'y':30,'w':120,'h':25}
    assert result['container_runtime_id']==[2] and result['scan']['graph_scan_complete'] is True
    assert result['window_rect']==[100,200,600,500] and result['source']=='windows_uia'
    assert co._owner.calls==1

@pytest.mark.parametrize('mutation,reason',[
    ('duplicate','row_selection_ambiguous'),('lists','row_selection_list_ambiguous'),
    ('selected','row_selection_state_unavailable'),('editor','row_selection_editor_unavailable'),
    ('provider','row_selection_provider_unsupported'),('runtime','row_selection_identity_changed')])
def test_rejects_ambiguous_unknown_and_identity(build,mutation,reason):
    listing,row=scene(True,mutation=='editor')
    other=[]
    if mutation=='duplicate':
        duplicate=Node('ListItem',(5,),'folder',selected=True);duplicate.parent_node=listing;listing.nodes.append(duplicate)
    if mutation=='lists':other=[Node('List',(9,),hwnd=99,cls='SysListView32')]
    if mutation=='selected':row.iface_selection_item.CurrentIsSelected=None
    if mutation=='editor':listing.nodes[0].CurrentHasKeyboardFocus=None
    if mutation=='provider':listing.CurrentClassName='UnknownList'
    kwargs={'expected_runtime_id':[99]} if mutation=='runtime' else {}
    with pytest.raises(reader.RowSelectionReadError,match=reason):reader.read_row_selection(build(listing,*other),TARGET,'folder',**kwargs)

@pytest.mark.parametrize('change', ['selected','editor','parent','runtime','geometry'])
def test_rejects_mid_read_changes(build,change):
    listing,row=scene(True)
    def mutate(root):
        if change=='selected':row.iface_selection_item.CurrentIsSelected=False
        if change=='editor':
            edit=Node('Edit',(4,),hwnd=44,cls='Edit');edit.iface_value=Value();edit.CurrentHasKeyboardFocus=1;edit.parent_node=listing;listing.nodes.insert(0,edit)
        if change=='parent':row.parent_node=root
        if change=='runtime':row.element_info.runtime_id=[88]
        if change=='geometry':row.element_info.rectangle=rect(121,230,120,25)
    with pytest.raises(reader.RowSelectionReadError):reader.read_row_selection(build(listing,mutate=mutate),TARGET,'folder')

def test_native_identity_changed(build):
    listing,row=scene(True)
    with pytest.raises(reader.RowSelectionReadError,match='window_changed'):
        reader.read_row_selection(build(listing,identities=[IDENTITY,{**IDENTITY,'process_create_time':124.0}]),TARGET,'folder')

def test_finite_scan_limit(build,monkeypatch):
    listing,row=scene(True);co=build(listing)
    monkeypatch.setattr(reader,'MAX_ROW_SCAN_EDGES',1)
    with pytest.raises(reader.RowSelectionReadError,match='scan_limit'):reader.read_row_selection(co,TARGET,'folder')

@pytest.mark.parametrize('failure',[None,'exception','missing_interface'])
def test_virtual_edit_unknown_value_pattern_is_not_absence(build,failure):
    listing,row=scene(True)
    class UnknownValue:
        @property
        def CurrentIsReadOnly(self):
            if failure=='exception':raise RuntimeError('provider failed')
            if failure=='missing_interface':raise AttributeError('provider failed')
            return None
    row.nodes[0].iface_value=UnknownValue()
    with pytest.raises(reader.RowSelectionReadError,match='editor_pattern_unavailable'):
        reader.read_row_selection(build(listing),TARGET,'folder')

@pytest.mark.parametrize('value',[-1,2,'1',None])
def test_invalid_selection_never_becomes_false(build,value):
    listing,row=scene(value)
    with pytest.raises(reader.RowSelectionReadError,match='state_unavailable'):
        reader.read_row_selection(build(listing),TARGET,'folder')

def test_initial_invalid_native_identity_is_rejected(build):
    listing,row=scene(True)
    with pytest.raises(reader.RowSelectionReadError,match='window_unavailable'):
        reader.read_row_selection(build(listing,identities=[{**IDENTITY,'process_id':21}]),TARGET,'folder')

def test_editor_readonly_is_not_an_active_rename(build):
    listing,row=scene(True,True);listing.nodes[0].iface_value=NS(CurrentIsReadOnly=1)
    with pytest.raises(reader.RowSelectionReadError,match='editor_unavailable'):
        reader.read_row_selection(build(listing),TARGET,'folder')

def test_row_geometry_outside_native_window_rejected(build):
    listing,row=scene(True);row.element_info.rectangle=rect(690,230,120,25)
    with pytest.raises(reader.RowSelectionReadError,match='geometry_unavailable'):
        reader.read_row_selection(build(listing),TARGET,'folder')

def test_exact_row_name_does_not_use_fuzzy_matching(build):
    listing,row=scene(True)
    with pytest.raises(reader.RowSelectionReadError,match='not_found'):
        reader.read_row_selection(build(listing),TARGET,'Folder')

def test_unknown_virtual_edit_provider_is_not_ignored(build):
    listing,row=scene(True);row.nodes[0].CurrentClassName='UnknownEdit'
    with pytest.raises(reader.RowSelectionReadError,match='editor_unavailable'):
        reader.read_row_selection(build(listing),TARGET,'folder')

@pytest.mark.parametrize('parent_kind',['Pane','ListItem'])
def test_real_editor_in_unexpected_list_descendant_is_rejected(build,parent_kind):
    listing,row=scene(True)
    edit=Node('Edit',(7,),hwnd=77,cls='Edit');edit.iface_value=Value();edit.CurrentHasKeyboardFocus=1
    parent=Node(parent_kind,(6,),'other',children=[edit],selected=False)
    parent.parent_node=listing;listing.nodes.append(parent)
    with pytest.raises(reader.RowSelectionReadError,match='editor_unavailable'):
        reader.read_row_selection(build(listing),TARGET,'folder')

def test_other_row_virtual_name_does_not_indicate_editing(build):
    listing,row=scene(True)
    virtual=Node('Edit',(6,1),'other');virtual.CurrentHasKeyboardFocus=1
    other=Node('ListItem',(6,),'other',children=[virtual],selected=False)
    other.parent_node=listing;listing.nodes.append(other)
    result=reader.read_row_selection(build(listing),TARGET,'folder')
    assert result['selected'] is True and result['editing'] is False

def test_root_desktop_parent_does_not_make_address_edit_part_of_list(build):
    listing,row=scene(True)
    address=Node('Edit',(8,),name='address',hwnd=88,cls='Edit')
    class ForbiddenValue:
        @property
        def CurrentIsReadOnly(self):pytest.fail('列表外地址栏不得读取Value模式')
    address.iface_value=ForbiddenValue()
    result=reader.read_row_selection(build(listing,address,desktop_parent=True),TARGET,'folder')
    assert result['selected'] is True and result['editing'] is False
    assert result['scan']['graph_scan_complete'] is True


def test_selected_change_has_bounded_failure_evidence(build):
    import json
    listing,row=scene(False)
    row.element_info.name='\u4e2d\u6587'
    def mutate(root):row.iface_selection_item.CurrentIsSelected=True
    with pytest.raises(reader.RowSelectionReadError) as caught:
        reader.read_row_selection(build(listing,mutate=mutate),TARGET,'\u4e2d\u6587')
    error=caught.value
    assert str(error)==error.reason_code=='row_selection_state_changed'
    evidence=error.failure_evidence
    assert evidence['contract_version']=='row_selection_scan_difference_v1'
    assert evidence['changed_fields']==['selected']
    assert evidence['before']['selected'] is False and evidence['after']['selected'] is True
    assert evidence['before']['row']['label']=='\u4e2d\u6587'
    assert evidence['window_binding']['identity']=={**IDENTITY, 'executable_path': r'c:\fixture.exe'}
    assert len(json.dumps(evidence,ensure_ascii=False).encode('utf-8'))<=16384


def test_topology_change_has_hash_count_without_tree(build):
    listing,row=scene(False)
    def mutate(root):
        child=Node('Button',(90,),name='extra');child.parent_node=root;root.nodes.append(child)
    with pytest.raises(reader.RowSelectionReadError) as caught:
        reader.read_row_selection(build(listing,mutate=mutate),TARGET,'folder')
    evidence=caught.value.failure_evidence
    assert 'topology' in evidence['changed_fields']
    before,after=evidence['before']['topology'],evidence['after']['topology']
    assert after['count']==before['count']+1
    assert before['sha256']!=after['sha256']
    assert set(before)=={'count','sha256'}


def test_old_reader_error_has_no_fabricated_failure_evidence(build):
    listing,row=scene(None)
    with pytest.raises(reader.RowSelectionReadError) as caught:
        reader.read_row_selection(build(listing),TARGET,'folder')
    assert getattr(caught.value,'failure_evidence',None) is None


def test_evidence_projection_bounds_large_unicode_and_excludes_objects():
    import json
    from copy import deepcopy
    scan={'description': {'runtime_id': [3], 'bbox': {'x': 1, 'y': 2, 'w': 3, 'h': 4},
            'label': '\u4e2d'*10000, 'control_type': 'ListItem'},
          'list': {'runtime_id': [2], 'bbox': {'x': 0, 'y': 0, 'w': 100, 'h': 100},
            'label': '', 'control_type': 'List'},
          'selected': False, 'editing': False, 'editors': [],
          'topology': [(([n],20,'ListItem','Win32',0,10),[2]) for n in range(1000)],
          'scan': {'graph_scan_complete': True, 'provider_tree_valid': True, 'edge_count': 1000, 'alias_count': 0}}
    after=deepcopy(scan);after['selected']=True
    evidence=reader._scan_difference(scan,after,{**IDENTITY,'untrusted_object':object()},[100,200,600,500])
    encoded=json.dumps(evidence,ensure_ascii=False).encode('utf-8')
    assert len(encoded)<=reader.MAX_FAILURE_EVIDENCE_BYTES
    assert len(evidence['before']['row']['label'])==256
    assert evidence['before']['topology']['count']==1000
    assert evidence['window_binding']['identity']['untrusted_object'] is None
    assert '\u4e2d' in encoded.decode('utf-8')
    error=reader.RowSelectionReadError('row_selection_state_changed',failure_evidence=evidence)
    saved=reader.row_selection_failure_evidence(error)
    assert saved==json.loads(encoded)
    saved['before']['selected']=True
    assert error.failure_evidence['before']['selected'] is False


def test_arbitrary_and_oversized_failure_payloads_are_not_forwarded():
    from types import SimpleNamespace
    payload={'contract_version':reader.SCAN_DIFFERENCE_VERSION,'changed_fields':['selected'],
             'window_binding':{},'before':{},'after':{}}
    assert reader.row_selection_failure_evidence(SimpleNamespace(reason_code='row_selection_state_changed',failure_evidence=payload)) is None
    error=reader.RowSelectionReadError('row_selection_state_changed',failure_evidence=payload)
    error.failure_evidence['before']['large']='\u4e2d'*reader.MAX_FAILURE_EVIDENCE_BYTES
    assert reader.row_selection_failure_evidence(error) is None
    assert reader.row_selection_failure_evidence(reader.RowSelectionReadError('row_selection_state_changed')) is None
