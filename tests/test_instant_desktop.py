"""桌面命令无需调用方先选窗口，失败不得沿用旧应用目标。"""
from types import SimpleNamespace
import pytest
from app.instant_mcp import InstantCommand

@pytest.mark.parametrize("kind,payload", [("desktop_capture", None), ("desktop_click", {"goal":"打开计算器", "click_kind":"double"})])
def test_desktop_contract_needs_no_window_identity(kind, payload):
    args={"kind":kind}
    if payload is not None: args["request"]=payload
    assert InstantCommand.model_validate(args).command()==args

@pytest.mark.parametrize("command", [
    {"kind":"desktop_capture","handle":123},
    {"kind":"desktop_click"},
    {"kind":"desktop_click","request":{"goal":"打开计算器","x":4,"y":5}},
    {"kind":"desktop_click","operation":"type_text","request":{"text":"bad"}},
])
def test_desktop_command_rejects_stale_coordinates_or_nonclick_fields(command):
    with pytest.raises(ValueError): InstantCommand.model_validate(command).command()

class Coordinator:
    def __init__(self, windows): self.windows=windows; self.calls=[]
    def discover_applications(self): return {"running_windows":self.windows}
    def preview_selected_window_preparation(self, **kw):
        self.calls.append(("preview",kw)); return {"preparation_id":"fresh"}
    def confirm_window_preparation(self, ident):
        self.calls.append(("confirm",ident)); return {"status":"focused","window":{"handle":11,"process_id":22}}


def test_desktop_resolves_current_shell_not_previous_app():
    from app.desktop_review.desktop_command import prepare_desktop_target
    co=Coordinator([{"handle":99,"process_id":77,"title":"Old App"},
                    {"handle":11,"process_id":22,"window_kind":"desktop"}])
    result=prepare_desktop_target(co)
    assert result["window"]=={"handle":11,"process_id":22}
    assert co.calls==[("preview",{"target_window_handle":11,"target_process_id":22}),("confirm","fresh")]

@pytest.mark.parametrize("windows", [[], [{"handle":10,"process_id":20,"title":"Program Manager"}],
    [{"handle":11,"process_id":22,"window_kind":"desktop"},{"handle":12,"process_id":22,"window_kind":"desktop"}]])
def test_unverified_or_ambiguous_desktop_does_not_prepare(windows):
    from app.desktop_review.desktop_command import prepare_desktop_target
    co=Coordinator(windows)
    with pytest.raises(ValueError,match="desktop_host"): prepare_desktop_target(co)
    assert not co.calls
