"""Run with: python -m unittest discover -s tests -v (Bot SDK required)."""
import copy
import inspect
import os
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, patch

from botbuilder.core import TurnContext
from botbuilder.core.adapters import TestAdapter
from botbuilder.core.serializer_helper import serializer_helper
from botbuilder.schema import Activity

with patch.dict(os.environ, {"MicrosoftAppType": "MultiTenant", "MicrosoftAppId": "",
                             "MicrosoftAppPassword": "", "MicrosoftAppTenantId": ""}):
    import app


def walk(value):
    if isinstance(value, dict):
        yield value
        for child in value.values():
            yield from walk(child)
    elif isinstance(value, list):
        for child in value:
            yield from walk(child)


class CardTransportTests(unittest.TestCase):
    def test_hpoint_event_query_parser_and_paging_card(self):
        self.assertEqual(app.parse_hpoint_event_page("현재 진행중인 사은행사"), 1)
        self.assertEqual(app.parse_hpoint_event_page("현재 진행중인 행사 2페이지"), 2)
        self.assertEqual(app.parse_hpoint_event_page("사은행사 3페이지 조회"), 3)
        self.assertIsNone(app.parse_hpoint_event_page("다음 행사 일정 알려줘"))

        card = app.create_hpoint_event_result_card({
            "ok": True,
            "storeCode": "220",
            "page": 1,
            "pageSize": 10,
            "totalCount": 24,
            "totalPages": 3,
            "hasPrevious": False,
            "hasNext": True,
            "events": [
                {"eventName": "H.Point 사은행사"},
                {"eventName": "금액대별 사은 행사"},
            ],
        }).content
        nodes = list(walk(card))
        texts = [node.get("text") for node in nodes if node.get("type") == "TextBlock"]
        self.assertTrue(any("H.Point 사은행사" in str(text) for text in texts))
        next_action = next(
            node for node in nodes
            if node.get("data", {}).get("action") == "hpoint_event_page"
            and node.get("title") == "다음"
        )
        self.assertEqual(next_action["data"]["page"], 2)
        self.assertEqual(next_action["data"]["selected_store_code"], "220")

    def test_product_name_search_input_and_item_candidates(self):
        form = app.create_product_search_input_card(
            app.TOOL_PRODUCT_LOOKUP,
            {"assignedStoreCode": "210", "accessibleStoreCodes": ["210"]},
        ).content
        form_nodes = list(walk(form))
        self.assertTrue(any(node.get("id") == "search_name" for node in form_nodes))
        self.assertTrue(any(node.get("title") == "이름으로 검색" for node in form_nodes))

        candidates = app.create_product_name_results_card(
            tool_name=app.TOOL_PRODUCT_LOOKUP,
            selected_store_code="210",
            keyword="콜라",
            response_json={
                "ok": True,
                "items": [
                    {
                        "itemName": f"콜라 {index}",
                        "itemCode": f"88012345678{index:02d}",
                        "opCode": "01",
                        "saleType": "1",
                    }
                    for index in range(12)
                ],
            },
            page=1,
        ).content
        actions = [node for node in walk(candidates)
                   if node.get("type") == "Action.Submit"]
        selections = [node for node in actions
                      if node.get("data", {}).get("action") == "product_search_name_select"]
        self.assertEqual(len(selections), 10)
        self.assertEqual(selections[0]["data"]["op_code"], "01")
        self.assertEqual(selections[0]["data"]["sale_type"], "1")
        self.assertTrue(any(node.get("title") == "다음" for node in actions))

    def test_plu_name_candidate_preserves_plu_code(self):
        card = app.create_product_name_results_card(
            tool_name=app.TOOL_SINGLE_PRODUCT_LOOKUP,
            selected_store_code="210",
            keyword="콜라",
            response_json={"items": [{"pluName": "콜라 500ml", "pluCode": "880123"}]},
        ).content
        selection = next(
            node for node in walk(card)
            if node.get("data", {}).get("action") == "product_search_name_select"
        )
        self.assertEqual(selection["data"]["search_code"], "880123")
        self.assertEqual(selection["data"]["op_code"], "")

    def test_refund_status_cards_show_each_backend_status(self):
        original = {
            "storeCode": "210", "saleDate": "20260915",
            "posNo": "1111", "dealNo": "000123",
        }
        cases = (
            (
                "IN_PROGRESS", "반품 진행 중", "반품 진행 정보", True,
                {"refundProgress": {
                    "storeCode": "210", "saleDate": "20260915", "posNo": "2222",
                }},
            ),
            (
                "REFUNDED", "반품 완료", "반품 거래 정보", False,
                {"refundReceipt": {
                    "storeCode": "210", "saleDate": "20260915",
                    "posNo": "3333", "dealNo": "000456",
                }},
            ),
            ("NOT_REFUNDED", "미반품 거래", None, False, {}),
        )
        for status, title, detail_title, can_cancel, extra in cases:
            with self.subTest(status=status):
                payload = {
                    "ok": True,
                    "assignedStoreCode": "210",
                    "found": status == "IN_PROGRESS",
                    "status": status,
                    "message": f"{status} 안내",
                    "originalTransaction": {
                        **original,
                        "refundYn": "1" if status == "REFUNDED" else "0",
                    },
                    **extra,
                }
                card = app.create_refund_status_result_card(payload).content
                texts = [node.get("text") for node in walk(card)
                         if node.get("type") == "TextBlock"]
                facts = [fact for node in walk(card) if node.get("type") == "FactSet"
                         for fact in node.get("facts", [])]
                action_titles = [node.get("title") for node in walk(card)
                                 if node.get("type") == "Action.Submit"]
                self.assertIn(title, texts)
                self.assertIn("원거래 정보", texts)
                if detail_title:
                    self.assertIn(detail_title, texts)
                self.assertIn({"title": "거래번호", "value": "000123"}, facts)
                if status == "REFUNDED":
                    self.assertIn({"title": "거래번호", "value": "000456"}, facts)
                self.assertEqual("반품진행 취소" in action_titles, can_cancel)

    def test_tool_menu_keeps_all_buttons_on_one_compact_card(self):
        card = app.create_tool_menu_card()
        self.assertEqual(card.content_type, "application/vnd.microsoft.card.hero")
        self.assertNotIn("text", card.content)
        self.assertEqual(len(card.content["buttons"]), 6)
        self.assertEqual(card.content["buttons"][-1]["title"], "카테고리별 FAQ")

    def test_all_card_builders_use_baseline_submit(self):
        samples = {
            "store_access": {"assignedStoreCode": "210", "accessibleStoreCodes": ["210"]},
            "selected_store_code": "210", "keyword": "콜라", "page": 1,
            "tool_name": app.TOOL_SINGLE_PRODUCT_LOOKUP,
            "response_json": {"found": True, "hasNext": True, "hasPrevious": True,
                              "page": 2, "totalPages": 3, "posNo": "0701",
                              "storeCode": "210", "searchType": "all"},
            "category": "1", "questions": [{"question": "테스트 질문"}],
            "question": "질문", "answer": "답변", "request_id": "test",
            "title": "제목", "message": "내용", "success": True,
            "pattern_group_code": "1001", "pattern_code": "6023",
            "pattern_value": "1", "normalized_pos_no": "0701",
        }
        count = 0
        for name, builder in vars(app).items():
            if not (name.startswith("create_") and name.endswith("_card")):
                continue
            with self.subTest(card=name):
                kwargs = {key: copy.deepcopy(samples[key])
                          for key in inspect.signature(builder).parameters if key in samples}
                card = builder(**kwargs)
                serializer_helper(card)
                for node in walk(card.content):
                    self.assertNotEqual(node.get("type"), "Action.Execute")
                    if node.get("type") == "AdaptiveCard":
                        self.assertEqual(node["version"], "1.2")
                    if node.get("type") == "Action.Submit":
                        self.assertTrue(node["data"].get("action"))
                        self.assertNotIn("msteams", node["data"])
                    if str(node.get("type", "")).startswith("Input."):
                        self.assertNotIn("isRequired", node)
                        self.assertNotIn("label", node)
                count += 1
        self.assertGreaterEqual(count, 20)

    def test_labels_and_values_survive_normalization(self):
        card = app.create_pattern_search_form_card({
            "assignedStoreCode": "210", "accessibleStoreCodes": ["210"]}).content
        nodes = list(walk(card))
        self.assertTrue(any(n.get("text") == "POS 번호 *" for n in nodes))
        self.assertTrue(any(n.get("id") == "selected_store_code" and
                            n.get("value") == "210" for n in nodes))
        original = copy.deepcopy(card)
        app.normalize_adaptive_card_for_teams_mobile(card)
        self.assertEqual(card, original)


class DispatchTests(unittest.IsolatedAsyncioTestCase):
    async def test_name_search_requires_two_characters(self):
        bot = app.RelayBot()
        context = TurnContext(TestAdapter(), Activity(type="message"))
        context.send_activity = AsyncMock()
        with patch.object(app, "search_items_by_name", new=AsyncMock()) as search:
            await bot.handle_product_search_name_submit(
                context,
                {"tool": app.TOOL_PRODUCT_LOOKUP,
                 "selected_store_code": "210", "search_name": "콜"},
            )
        search.assert_not_awaited()
        self.assertIn("최소 2글자", context.send_activity.await_args.args[0])

    async def test_name_search_calls_new_api_and_renders_candidates(self):
        bot = app.RelayBot()
        bot.update_or_send_card = AsyncMock()
        context = TurnContext(TestAdapter(), Activity(type="message"))
        with (
            patch.object(app, "get_teams_account", new=AsyncMock(
                return_value=("kimjungwoo", "사용자"))),
            patch.object(app, "search_items_by_name", new=AsyncMock(
                return_value={
                    "status": 200,
                    "response_text": '{"ok":true}',
                    "response_json": {
                        "ok": True,
                        "items": [{
                            "itemName": "콜라", "itemCode": "8801234567890",
                            "opCode": "01", "saleType": "1",
                        }],
                    },
                })) as search,
        ):
            await bot.handle_product_search_name_submit(
                context,
                {"tool": app.TOOL_PRODUCT_LOOKUP,
                 "selected_store_code": "210", "search_name": "콜라"},
            )
        search.assert_awaited_once_with(
            target_url=app.CONFIG.ITEM_NAME_SEARCH_API_URL,
            user_id="kimjungwoo",
            selected_store_code="210",
            item_type="상품",
            keyword="콜라",
        )
        bot.update_or_send_card.assert_awaited_once()

    async def test_selected_item_calls_detail_with_exact_item_keys(self):
        bot = app.RelayBot()
        bot.execute_product_search = AsyncMock()
        context = TurnContext(TestAdapter(), Activity(type="message"))
        await bot.handle_product_search_name_select(
            context,
            {
                "tool": app.TOOL_PRODUCT_LOOKUP,
                "selected_store_code": "210",
                "search_code": "8801234567890",
                "op_code": "01",
                "sale_type": "1",
            },
        )
        bot.execute_product_search.assert_awaited_once_with(
            context,
            tool_name=app.TOOL_PRODUCT_LOOKUP,
            selected_store_code="210",
            search_code="8801234567890",
            op_code="01",
            sale_type="1",
            update_source=True,
        )

    async def test_native_submit_http_response_is_201(self):
        bot = app.RelayBot()
        bot.handle_pattern_search_submit = AsyncMock()
        payload = {"type": "message", "value": {
            "action": "pattern_search_submit", "pos_no": "0701",
            "selected_store_code": "210", "search_type": "all"}}
        request = SimpleNamespace(method="POST", headers={"Content-Type": "application/json"},
                                  json=AsyncMock(return_value=payload))

        async def dispatch(_auth, activity, callback):
            await callback(TurnContext(TestAdapter(), activity))
            return None

        with patch.object(app.ADAPTER, "process_activity", side_effect=dispatch):
            response = await app.ADAPTER.process(request, bot)
        self.assertEqual(response.status, 201)
        bot.handle_pattern_search_submit.assert_awaited_once()

    async def test_submits_reach_handlers_with_inputs(self):
        routes = {
            "tool_menu": "handle_tool_menu", "tool_select": "handle_tool_select",
            "general_category_select": "handle_general_category_select",
            "general_top_question_select": "handle_general_top_question_select",
            "pos_master_create_submit": "handle_pos_master_create_submit",
            "product_search_code_submit": "handle_product_search_code_submit",
            "product_search_name_submit": "handle_product_search_name_submit",
            "product_search_name_select": "handle_product_search_name_select",
            "product_search_prepare_image": "handle_product_search_prepare_image",
            "hpoint_event_page": "handle_hpoint_event_lookup",
            "pattern_search_submit": "handle_pattern_search_submit",
            "pattern_search_page": "handle_pattern_search_submit",
            "pattern_update_submit": "handle_pattern_update_submit",
            "refund_status_submit": "handle_refund_status_submit",
            "refund_cancel_submit": "handle_refund_status_submit",
            "feedback": "handle_feedback", "faq_register_submit": "handle_register_submit",
            "faq_register_cancel": "handle_register_cancel",
        }
        for action, handler in routes.items():
            with self.subTest(action=action):
                bot = app.RelayBot()
                mock = AsyncMock()
                setattr(bot, handler, mock)
                payload = {"action": action, "selected_store_code": "210",
                           "pos_no": "0701", "deal_no": "0042"}
                activity = Activity(type="message", value=payload)
                context = TurnContext(TestAdapter(), activity)
                await bot.on_turn(context)
                mock.assert_awaited_once()
                if len(mock.call_args.args) > 1:
                    self.assertEqual(mock.call_args.args[1], payload)

    async def test_existing_execute_cards_still_serialize(self):
        bot = app.RelayBot()
        bot.on_message_activity = AsyncMock()
        context = TurnContext(TestAdapter(), Activity(
            type="invoke", name="adaptiveCard/action",
            value={"action": {"type": "Action.Execute", "verb": "tool_menu",
                              "data": {"action": "tool_menu"}}}))
        response = await bot.on_invoke_activity(context)
        wire = serializer_helper(response.body)
        self.assertEqual(wire["statusCode"], 200)
        bot.on_message_activity.assert_awaited_once()


if __name__ == "__main__":
    unittest.main()
