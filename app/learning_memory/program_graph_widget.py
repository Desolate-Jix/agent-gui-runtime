"""复用原生图画布的程序步骤只读适配器。"""

from __future__ import annotations
from app.learning_memory.workbench_i18n import ui, tr, bind_text, initialize_i18n, language_manager

from app.desktop_review.graph_view import NativeWorkflowGraphView

from .program_graph import project_program_graph


class ProgramGraphWidget(NativeWorkflowGraphView):
    def set_program_graph(self, definition: dict) -> None:
        self._install_checked(project_program_graph(definition))
        for item in self._node_items.values():
            ui(item._type_text.setText, tr('步骤'))


__all__ = ["ProgramGraphWidget"]
