import asyncio

from mcp import ClientSession
from mcp.client.stdio import stdio_client

from tests.test_formal_learning_observation import _mcp_server, _request, _rig


def test_observed_learning_mcp_schema_exposes_bbox_shape(tmp_path, monkeypatch):
    async def check(host, connection):
        async with stdio_client(_mcp_server(host.status()["base_url"], connection["token"])) as streams:
            async with ClientSession(*streams, read_timeout_seconds=30) as client:
                await client.initialize()
                tool = next(item for item in (await client.list_tools()).tools
                            if item.name == "submit_observed_interface_learning")
                schema = tool.input_schema
                region = schema["$defs"]["ObservedRegionInput"]
                assert region["properties"]["bbox"]["type"] == "array"
                assert region["properties"]["bbox"]["minItems"] == 4
                assert region["properties"]["bbox"]["maxItems"] == 4
                assert region["properties"]["bbox"]["items"] == {"type": "number"}
                assert region["additionalProperties"] is False
                from app.desktop_review.interface_content import _REGION_KINDS
                assert set(region["properties"]["kind"]["enum"]) == _REGION_KINDS

    with _rig(tmp_path, monkeypatch) as (host, connection, segment, _captures):
        host.start()
        asyncio.run(check(host, connection))

