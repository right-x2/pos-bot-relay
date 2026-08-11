import unittest
from datetime import date

from app.item_diagnostics import build_item_diagnosis


EVALUATED_DATE = date(2026, 8, 11)


class ItemDiagnosisTests(unittest.TestCase):
    def test_active_plu_and_price_event_are_available(self):
        diagnosis = build_item_diagnosis(
            "PLU",
            {
                "USE_YN": "1",
                "PRC_EVT_CD": "E100",
                "PRC_EVT_ST_DT": "20260801",
                "PRC_EVT_ED_DT": "20260831",
                "PRC_EVT_PRC": 1000,
            },
            evaluated_date=EVALUATED_DATE,
        )

        self.assertEqual(diagnosis["overallStatus"], "AVAILABLE")
        self.assertEqual(diagnosis["events"][0]["periodStatus"], "ACTIVE")
        self.assertEqual(diagnosis["events"][0]["startDate"], "2026-08-01")

    def test_inactive_use_status_overrides_active_event(self):
        diagnosis = build_item_diagnosis(
            "PLU",
            {
                "USE_YN": "0",
                "NN_EVT_CD": "N100",
                "NN_EVT_ST_DT": "2026-08-01",
                "NN_EVT_ED_DT": "2026-08-31",
            },
            evaluated_date=EVALUATED_DATE,
        )

        self.assertEqual(diagnosis["overallStatus"], "UNAVAILABLE")
        self.assertEqual(diagnosis["checks"][0]["status"], "FAIL")

    def test_scheduled_and_expired_events_are_not_current(self):
        diagnosis = build_item_diagnosis(
            "PLU",
            {
                "USE_YN": "Y",
                "TRGT_EVT_CD_1": "FUTURE",
                "TRGT_EVT_ST_DT_1": "20260901",
                "TRGT_EVT_ED_DT_1": "20260930",
                "TRGT_EVT_CD_2": "PAST",
                "TRGT_EVT_ST_DT_2": "20260701",
                "TRGT_EVT_ED_DT_2": "20260731",
            },
            evaluated_date=EVALUATED_DATE,
        )

        statuses = [event["periodStatus"] for event in diagnosis["events"]]
        self.assertEqual(statuses, ["SCHEDULED", "EXPIRED"])
        self.assertEqual(diagnosis["overallLabel"], "사용 가능 · 현재 행사 없음")

    def test_invalid_period_requires_confirmation(self):
        diagnosis = build_item_diagnosis(
            "PLU",
            {
                "USE_YN": "1",
                "PRC_EVT_CD": "BROKEN",
                "PRC_EVT_ST_DT": "20260831",
                "PRC_EVT_ED_DT": "20260801",
            },
            evaluated_date=EVALUATED_DATE,
        )

        self.assertEqual(diagnosis["overallStatus"], "CHECK_REQUIRED")
        self.assertEqual(diagnosis["events"][0]["periodStatus"], "INVALID")

    def test_missing_period_end_requires_confirmation(self):
        diagnosis = build_item_diagnosis(
            "PLU",
            {
                "USE_YN": "1",
                "PRC_EVT_CD": "NO-END",
                "PRC_EVT_ST_DT": "20260801",
            },
            evaluated_date=EVALUATED_DATE,
        )

        self.assertEqual(diagnosis["overallStatus"], "CHECK_REQUIRED")
        self.assertEqual(diagnosis["events"][0]["periodStatus"], "INVALID")

    def test_item_master_requires_plu_for_event_checks(self):
        diagnosis = build_item_diagnosis(
            "ITEM",
            {"USE_YN": "1"},
            evaluated_date=EVALUATED_DATE,
        )

        self.assertEqual(diagnosis["overallStatus"], "AVAILABLE")
        self.assertEqual(diagnosis["checks"][1]["value"], "단품 조회 필요")
        self.assertEqual(diagnosis["checks"][2]["value"], "단품 조회 필요")


if __name__ == "__main__":
    unittest.main()
