"""Supabase mock helpers for metering and cache tests."""


class FakeSupabaseClient:
    def __init__(self):
        self.calls = []

    async def rpc(self, *args, **kwargs):
        self.calls.append((args, kwargs))
        return {"success": True}


