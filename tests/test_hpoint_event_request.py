import unittest
from unittest.mock import patch

import hpoint_event


class FakeResponse:
    status = 200

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_args):
        return False

    async def text(self):
        return '{"ok": true, "events": []}'


class FakeSession:
    latest_json = None
    latest_url = None

    def __init__(self, **_kwargs):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_args):
        return False

    def post(self, url, **kwargs):
        FakeSession.latest_url = url
        FakeSession.latest_json = kwargs.get("json")
        return FakeResponse()


class HpointEventRequestTests(unittest.IsolatedAsyncioTestCase):
    async def test_lookup_posts_backend_contract_fields(self):
        with patch.object(hpoint_event.aiohttp, "ClientSession", FakeSession):
            result = await hpoint_event.fetch_hpoint_events(
                target_url="http://example/tools/hpoint_event_lookup",
                user_id=" kimjungwoo ",
                selected_store_code=" 220 ",
                page=2,
            )

        self.assertEqual(result["status"], 200)
        self.assertEqual(
            FakeSession.latest_json,
            {
                "userId": "kimjungwoo",
                "selectedStoreCode": "220",
                "page": 2,
            },
        )

    async def test_lookup_rejects_invalid_page_before_request(self):
        with self.assertRaisesRegex(ValueError, "page는 1 이상"):
            await hpoint_event.fetch_hpoint_events(
                target_url="http://example/tools/hpoint_event_lookup",
                user_id="kimjungwoo",
                selected_store_code="220",
                page=0,
            )


if __name__ == "__main__":
    unittest.main()
