import sys
import types
import unittest
from types import SimpleNamespace
from unittest.mock import patch


chromadb_stub = types.ModuleType("chromadb")
chromadb_stub.PersistentClient = object
chromadb_config_stub = types.ModuleType("chromadb.config")
chromadb_config_stub.Settings = object
sys.modules.setdefault("chromadb", chromadb_stub)
sys.modules.setdefault("chromadb.config", chromadb_config_stub)

config_stub = types.ModuleType("app.config")
config_stub.settings = SimpleNamespace(
    CHROMA_DIR="./data/chroma",
    CHROMA_COLLECTION="pos_faq",
    CHROMA_TOMBSTONE_DB=None,
    IMAGE_RAG_MAX_DISTANCE=0.65,
    IMAGE_RAG_FALLBACK_MAX_DISTANCE=0.75,
    IMAGE_RAG_MIN_DISTANCE_GAP=0.15,
    IMAGE_RAG_CANDIDATE_COUNT=12,
)
sys.modules.setdefault("app.config", config_stub)

azure_client_stub = types.ModuleType("app.azure_client")
azure_client_stub.embed_text = lambda text: []
azure_client_stub.chat_answer = lambda prompt: ""
sys.modules.setdefault("app.azure_client", azure_client_stub)

db_stub = types.ModuleType("app.db")
db_stub.increment_faq_counts = lambda items: None
sys.modules.setdefault("app.db", db_stub)

from app import rag


VISION_ANALYSIS = (
    "화면: 신용카드 결제\n"
    "오류문구: 카드사 통신장애. 잠시후 거래 재시도\n"
    "오류코드: 3023\n"
    "상태: 신용카드 결제 중 통신 오류"
)


class ImageRagTests(unittest.TestCase):
    def test_image_context_without_faq_returns_not_found(self):
        with patch.object(rag, "search_faq", return_value=[]):
            result = rag.ask_rag(
                "결제가 왜 안 돼?",
                retrieval_question=(
                    "결제가 왜 안 돼?\n\n"
                    f"{VISION_ANALYSIS}"
                ),
                image_context=VISION_ANALYSIS,
            )

        self.assertEqual(result["references"], [])
        self.assertEqual(result["answer"], "관련 FAQ를 찾지 못했습니다.")

    def test_retrieval_text_combines_user_text_and_full_vision_analysis(self):
        result = rag.build_image_retrieval_text(
            question="이 오류 어떻게 처리해?",
            vision_analysis=VISION_ANALYSIS,
        )

        self.assertEqual(
            result,
            (
                "이 오류 어떻게 처리해?\n\n"
                f"{VISION_ANALYSIS}"
            ),
        )

    def test_retrieval_text_uses_only_vision_for_image_only_message(self):
        for question in ("", "첨부된 POS 화면을 분석해주세요.", "첨부 이미지 분석"):
            with self.subTest(question=question):
                self.assertEqual(
                    rag.build_image_retrieval_text(question, VISION_ANALYSIS),
                    VISION_ANALYSIS,
                )

    def test_retrieval_text_removes_vision_boilerplate_and_markdown(self):
        noisy_analysis = (
            "[이미지 분석 결과] 다음과 같이 화면 정보를 추출할 수 있습니다.\n\n"
            "- **화면:** 현대백화점 POS 승인 화면\n"
            "- **오류문구:** 서버 연결에 실패했습니다.\n"
            "- **오류코드:** Timeout"
        )

        result = rag.build_image_retrieval_text("", noisy_analysis)

        self.assertEqual(
            result,
            (
                "화면: 현대백화점 POS 승인 화면\n"
                "오류문구: 서버 연결에 실패했습니다.\n"
                "오류코드: Timeout"
            ),
        )
        self.assertNotIn("이미지 분석 결과", result)
        self.assertNotIn("다음과 같이", result)
        self.assertNotIn("**", result)

    def test_ask_rag_embeds_combined_retrieval_text(self):
        retrieval_text = rag.build_image_retrieval_text(
            "결제가 왜 안 돼?",
            VISION_ANALYSIS,
        )
        with patch.object(rag, "search_faq", return_value=[]) as search:
            rag.ask_rag(
                "결제가 왜 안 돼?",
                retrieval_question=retrieval_text,
                image_context=VISION_ANALYSIS,
            )

        search.assert_called_once_with(retrieval_text, top_k=12)

    def test_search_faq_passes_input_unchanged_to_embedding(self):
        retrieval_text = rag.build_image_retrieval_text(
            "결제가 왜 안 돼?",
            VISION_ANALYSIS,
        )
        collection = SimpleNamespace(
            count=lambda: 1,
            query=lambda **kwargs: {
                "ids": [[]],
                "documents": [[]],
                "metadatas": [[]],
                "distances": [[]],
            },
        )
        with (
            patch.object(rag, "get_collection", return_value=collection),
            patch.object(rag, "_get_deleted_doc_ids", return_value=set()),
            patch.object(rag, "embed_text", return_value=[0.1]) as embed,
        ):
            rag.search_faq(retrieval_text)

        embed.assert_called_once_with(retrieval_text)

    def test_image_context_excludes_unrelated_faq(self):
        refs = [
            {"title": "관련 FAQ", "distance": 0.5446},
            {"title": "무관한 FAQ", "distance": 1.0},
        ]
        with (
            patch.object(rag, "search_faq", return_value=refs),
            patch.object(rag, "increment_faq_counts"),
            patch.object(rag, "chat_answer", return_value="이미지 분석 답변") as chat,
        ):
            result = rag.ask_rag("화면 분석", image_context=VISION_ANALYSIS)

        self.assertEqual([ref["title"] for ref in result["references"]], ["관련 FAQ"])
        prompt = chat.call_args.args[0]
        self.assertIn("관련 FAQ", prompt)
        self.assertNotIn("무관한 FAQ", prompt)

    def test_image_context_accepts_clear_leader_above_normal_threshold(self):
        refs = [
            {"title": "가장 가까운 FAQ", "distance": 0.7},
            {"title": "무관한 FAQ", "distance": 0.95},
        ]
        with (
            patch.object(rag, "search_faq", return_value=refs),
            patch.object(rag, "increment_faq_counts"),
            patch.object(rag, "chat_answer", return_value="FAQ 기반 답변"),
        ):
            result = rag.ask_rag("화면 분석", image_context=VISION_ANALYSIS)

        self.assertEqual(
            [ref["title"] for ref in result["references"]],
            ["가장 가까운 FAQ"],
        )

    def test_error_code_match_wins_over_vector_distance(self):
        refs = [
            {
                "title": "가까운 다른 FAQ",
                "content": "로그인 처리 오류",
                "distance": 0.4,
            },
            {
                "title": "서버 연결 실패",
                "content": "오류코드 Timeout 발생 시 서버 통신 상태를 확인한다.",
                "distance": 0.82,
            },
        ]
        retrieval_text = (
            "화면: 승인 화면\n"
            "오류문구: 서버 연결에 실패하였습니다\n"
            "오류코드: TimeOut\n"
            "상태: 승인 처리 실패"
        )
        with (
            patch.object(rag, "search_faq", return_value=refs),
            patch.object(rag, "increment_faq_counts"),
            patch.object(rag, "chat_answer", return_value="FAQ 기반 답변"),
        ):
            result = rag.ask_rag(
                "",
                retrieval_question=retrieval_text,
                image_context=retrieval_text,
            )

        self.assertEqual(
            [ref["title"] for ref in result["references"]],
            ["서버 연결 실패"],
        )

    def test_error_code_match_accepts_spaced_field_label(self):
        ref = {
            "title": "카드사 통신장애",
            "content": "오류코드 3023 조치 방법",
            "distance": 0.9,
        }
        retrieval_text = "오류 문구: 카드사 통신장애\n오류 코드: 3023"

        strength, match_type = rag._image_reference_match(ref, retrieval_text)

        self.assertEqual(strength, 2)
        self.assertEqual(match_type, "error_code")

    def test_image_context_rejects_ambiguous_weak_matches(self):
        refs = [
            {"title": "약한 후보 1", "distance": 0.7},
            {"title": "약한 후보 2", "distance": 0.76},
        ]
        with patch.object(rag, "search_faq", return_value=refs):
            result = rag.ask_rag("화면 분석", image_context=VISION_ANALYSIS)

        self.assertEqual(result["references"], [])
        self.assertEqual(result["answer"], "관련 FAQ를 찾지 못했습니다.")

    def test_unavailable_image_claim_is_replaced_with_vision_analysis(self):
        refs = [
            {
                "title": "카드사 통신장애 조치",
                "content": "잠시 후 거래를 재시도한다.",
                "distance": 0.3,
            }
        ]
        with (
            patch.object(rag, "search_faq", return_value=refs),
            patch.object(rag, "increment_faq_counts"),
            patch.object(
                rag,
                "chat_answer",
                return_value="실제 이미지가 포함되어 있지 않아 분석할 수 없습니다.",
            ),
        ):
            result = rag.ask_rag("화면 분석", image_context=VISION_ANALYSIS)

        self.assertIn(VISION_ANALYSIS, result["answer"])
        self.assertIn("카드사 통신장애 조치", result["answer"])
        self.assertNotIn("이미지가 포함되어 있지", result["answer"])

    def test_text_chat_without_faq_keeps_existing_response(self):
        with patch.object(rag, "search_faq", return_value=[]):
            result = rag.ask_rag("일반 질문")

        self.assertEqual(result["answer"], "관련 FAQ를 찾지 못했습니다.")
        self.assertEqual(result["references"], [])


if __name__ == "__main__":
    unittest.main()
