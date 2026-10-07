"""原生编辑器的短事务门面；窗口空闲时不占用 Agent 记忆库。"""
from pathlib import Path
from threading import RLock

from .workspace import MemoryWorkspace


class MemoryEditorClient:
    background_interface_loading = True
    pinned_interface_references = True
    _OPERATIONS = frozenset({
        "load_workflow_program", "save_workflow_program", "read_workflow_learning", "start_workflow_trial",
        "read_target_edit_context", "propose_target_edit",
        "read_interface_target_links", "read_learned_target_regions", "propose_target_box_edit",
        "read_workflow_image_options",
        "prepare_workflow_trial", "status_workflow_trial", "cancel_workflow_trial",
        "_artifact_file", "list_interface_contents", "list_interface_contents_for_reference",
        "load_interface_content", "load_interface_content_evidence", "save_interface_content",
        "preview_interface_content_deletion", "delete_interface_contents",
        "load_graph_revision", "create_workflow_graph", "attach_interface_to_workflow",
        "attach_interfaces_to_workflow", "detach_interface_from_workflow",
        "list_workflow_graphs", "list_workflow_projects", "list_workflow_project_summaries",
        "load_workflow_project", "save_workflow_project", "adopt_project_interface",
        "request_interface_relearning", "list_interface_relearning", "read_interface_relearning",
        "compare_interface_relearning", "adopt_interface_relearning",
        "reject_interface_relearning", "withdraw_interface_relearning",
        "save_control_template", "list_control_templates", "load_control_template_evidence",
        "list_source_candidates", "preview_source_candidate", "adopt_source_candidate",
    })

    def __init__(self, artifact_root):
        self._artifact_root = Path(artifact_root).resolve()
        self._guard = RLock()
        self._closed = False

    def __getattr__(self, name):
        if name not in self._OPERATIONS:
            raise AttributeError(name)

        def call(*args, **kwargs):
            # 一次服务调用持有完整事务锁；不在显示/用户编辑期间持有文件锁。
            with self._guard:
                if self._closed:
                    raise RuntimeError("memory editor client is closed")
                with MemoryWorkspace(self._artifact_root) as workspace:
                    return getattr(workspace, name)(*args, **kwargs)
        return call

    def close(self):
        with self._guard:
            self._closed = True

    def __enter__(self):
        return self

    def __exit__(self, *exception):
        self.close()
