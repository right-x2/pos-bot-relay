import unittest
from unittest.mock import patch

import item_search


class FakeFormData:
    latest = None

    def __init__(self, **_kwargs):
        self.fields = {}
        FakeFormData.latest = self

    def add_field(self, name, value, **_kwargs):
        self.fields[name] = value


class FakeResponse:
    status = 200

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_args):
        return False

    async def text(self):
        return '{"ok": true, "items": []}'


class FakeSession:
    def __init__(self, **_kwargs):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_args):
        return False

    def post(self, _url, **_kwargs):
        return FakeResponse()


class ItemSearchRequestTests(unittest.IsolatedAsyncioTestCase):
    async def test_name_search_posts_backend_contract_fields(self):
        with (
            patch.object(item_search.aiohttp, "FormData", FakeFormData),
            patch.object(item_search.aiohttp, "ClientSession", FakeSession),
        ):
            result = await item_search.search_items_by_name(
                target_url="http://example/api/items/search-by-name",
                user_id="kimjungwoo",
                selected_store_code="210",
                item_type="상품",
                keyword="콜라",
            )
        self.assertEqual(result["status"], 200)
        self.assertEqual(
            FakeFormData.latest.fields,
            {
                "userId": "kimjungwoo",
                "selectedStoreCode": "210",
                "상단품구분": "상품",
                "검색어": "콜라",
            },
        )

    async def test_item_detail_posts_op_and_sale_type(self):
        with (
            patch.object(item_search.aiohttp, "FormData", FakeFormData),
            patch.object(item_search.aiohttp, "ClientSession", FakeSession),
        ):
            await item_search.search_items(
                target_url="http://example/api/items/search",
                user_id="kimjungwoo",
                selected_store_code="210",
                item_type="상품",
                code="8801234567890",
                op_code="01",
                sale_type="1",
            )
        self.assertEqual(FakeFormData.latest.fields["코드"], "8801234567890")
        self.assertEqual(FakeFormData.latest.fields["OP_CD"], "01")
        self.assertEqual(FakeFormData.latest.fields["SALE_TP"], "1")


if __name__ == "__main__":
    unittest.main()
