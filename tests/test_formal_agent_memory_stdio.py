"""真实 MCP SDK/stdio 到正式 Reader 的隔离集成，不调用模型或外部软件。"""
import asyncio
import json
import os
from pathlib import Path
import sys

import pytest
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from app.agent_link.host import OwnedAgentLinkHttpHost
from test_formal_agent_memory_reuse import _published_pair
from test_formal_graph_exact_review import TOKEN


@pytest.mark.parametrize('granted', [False, True])
def test_real_stdio_negotiates_scoped_memory_and_agent_selects_version(tmp_path, granted):
    inbox, facade, x, _, y, second = _published_pair(tmp_path)
    service = facade._service
    service.bind_workflow_memory_reader(TOKEN, facade)
    connection = service.reviewer_call(TOKEN, 'create_connection', {
        'task_id': 'fresh-stdio-memory-task', 'agent_name': 'fresh-stdio-client',
    })
    allowed = sorted([x['logical_workflow_id'], y['logical_workflow_id']])
    if granted:
        service.reviewer_call(TOKEN, 'set_workflow_memory_scope', {
            'connection_id': connection['connection_id'], 'expected_revision': 0,
            'workflow_ids': allowed, 'idempotency_key': 'fresh-stdio-memory-grant',
        })
    host = OwnedAgentLinkHttpHost(service)
    try:
        url = host.start()
        env = {key: os.environ[key] for key in ('SystemRoot', 'PATH', 'TEMP', 'TMP') if key in os.environ}
        env.update(AGENT_LINK_BASE_URL=url, AGENT_LINK_TOKEN=connection['token'],
                   PYTHONIOENCODING='utf-8', PYTHONDONTWRITEBYTECODE='1',
                   AGENT_GUI_LEARNING_WORKFLOW_STORE_PATH=':memory:')
        server = StdioServerParameters(command=sys.executable,
            args=['-c', 'from app.agent_link.mcp_bridge import run_stdio; run_stdio()'],
            cwd=str(Path(__file__).resolve().parents[1]), env=env)

        async def check():
            with (tmp_path / 'stdio-stderr.log').open('w', encoding='utf-8') as errlog:
                async with stdio_client(server, errlog=errlog) as streams:
                    async with ClientSession(*streams, read_timeout_seconds=20) as client:
                        await client.initialize()
                        names = {item.name for item in (await client.list_tools()).tools}
                        expected = {'agent_link_status', 'submit_learning_batch',
                                    'read_learning_feedback', 'submit_relearning_candidate'}
                        if granted:
                            expected |= {'search_workflow_memory', 'get_workflow_memory'}
                        assert names == expected
                        status = await client.call_tool('agent_link_status', {})
                        assert status.is_error is False
                        if not granted:
                            return
                        search = await client.call_tool('search_workflow_memory', {'application_scope': {}})
                        assert search.is_error is False
                        assert {item['workflow_id'] for item in search.structured_content['items']} == set(allowed)
                        chosen = await client.call_tool('get_workflow_memory', {
                            'workflow_id': y['logical_workflow_id'], 'version': second['version_id'],
                        })
                        assert chosen.is_error is False
                        result = chosen.structured_content
                        assert result['workflow_id'] == y['logical_workflow_id']
                        assert result['version_id'] == second['version_id']
                        assert result['execute_binding_enabled'] is False
                        assert result['artifact_is_authorization'] is False
                        assert result['requires_current_grounding'] is True
                        assert 'source_workflow_path' not in json.dumps(result)
                        source = tmp_path / 'fresh-artifacts' / y['source_refs']['original_batch_path']
                        source.write_bytes(source.read_bytes() + b'changed')
                        damaged = await client.call_tool('get_workflow_memory', {
                            'workflow_id': y['logical_workflow_id'], 'version': second['version_id'],
                        })
                        assert damaged.is_error is True
                        error_text = '\n'.join(item.text for item in damaged.content if item.type == 'text')
                        assert 'memory_source_unavailable' in error_text and str(source) not in error_text
                        service.reviewer_call(TOKEN, 'set_workflow_memory_scope', {
                            'connection_id': connection['connection_id'], 'expected_revision': 1,
                            'workflow_ids': [], 'idempotency_key': 'fresh-stdio-memory-clear',
                        })
                        denied = await client.call_tool('get_workflow_memory', {
                            'workflow_id': y['logical_workflow_id'], 'version': second['version_id'],
                        })
                        assert denied.is_error is True
                        assert str(tmp_path) not in json.dumps(denied.model_dump(mode='json'))

        asyncio.run(asyncio.wait_for(check(), timeout=45))
    finally:
        try:
            host.close()
        finally:
            facade.close(); inbox.close()
