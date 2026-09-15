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
    def test_all_card_builders_use_baseline_submit(self):
        samples = {
            "store_access": {"assignedStoreCode": "210", "accessibleStoreCodes": ["210"]},
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
            "product_search_prepare_image": "handle_product_search_prepare_image",
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
