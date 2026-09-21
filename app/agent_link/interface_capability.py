"""宿主和 MCP 桥共用的独立界面能力声明。"""

INTERFACE_CONTENT_CAPABILITY = {
    "contract_version": "agent_interface_content_v1",
    "operations": ["search_interface_memory", "get_interface_memory", "request_interface_membership"],
}

WORKFLOW_PROJECT_MEMORY_CAPABILITY = {
    "contract_version": "agent_workflow_project_memory_v1",
    "operations": ["search_workflow_projects", "get_workflow_project_memory"],
}

INTERFACE_RELEARNING_CAPABILITY = {
    "contract_version": "agent_interface_relearning_v1",
    "operations": ["list_interface_relearning_feedback", "get_interface_relearning_feedback",
                   "submit_interface_relearning_candidate"],
}
