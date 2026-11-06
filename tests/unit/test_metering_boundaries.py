import unittest
from unittest.mock import AsyncMock, Mock

from bintu_api.database import increment_developer_usage as legacy_increment
from bintu_api.database import increment_token_usage
from bintu_api.metering.service import UsageEvent, record_usage_event
from bintu_api.metering.supabase import increment_usage


class MeteringBoundaryTests(unittest.IsolatedAsyncioTestCase):
    async def test_rpc_argument_contracts_remain_unchanged(self):
        supabase = Mock()
        supabase.rpc.return_value.execute = AsyncMock()

        await legacy_increment(supabase, "subscriber-7")
        supabase.rpc.assert_called_once_with(
            "increment_developer_usage",
            {"p_rapidapi_user": "subscriber-7"},
        )

        supabase.rpc.reset_mock()
        await increment_token_usage(supabase, "subscriber-7", tokens=19, mode="chunk")
        supabase.rpc.assert_called_once_with(
            "increment_developer_usage",
            {
                "p_rapidapi_user": "subscriber-7",
                "p_tokens": 19,
                "p_mode": "chunk",
            },
        )

        supabase.rpc.reset_mock()
        await increment_usage(
            supabase,
            identity="local:member",
            gateway="local",
            scrapes=1,
            tokens=23,
            mode="summarize",
        )
        supabase.rpc.assert_called_once_with(
            "increment_developer_usage",
            {
                "p_rapidapi_user": "local:member",
                "p_gateway": "local",
                "p_scrapes": 1,
                "p_tokens": 23,
                "p_mode": "summarize",
            },
        )

    async def test_legacy_route_event_uses_legacy_rpc_shape(self):
        supabase = Mock()
        supabase.rpc.return_value.execute = AsyncMock()

        await record_usage_event(
            supabase,
            UsageEvent(
                identity="subscriber-7",
                legacy_rpc=True,
                source="rest",
            ),
        )

        supabase.rpc.assert_called_once_with(
            "increment_developer_usage",
            {"p_rapidapi_user": "subscriber-7"},
        )
