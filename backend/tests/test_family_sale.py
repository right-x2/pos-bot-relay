import sys
import types
import unittest
from datetime import datetime
from decimal import Decimal
from types import SimpleNamespace


pyodbc_stub = types.ModuleType("pyodbc")
pyodbc_stub.connect = lambda *_args, **_kwargs: None
sys.modules.setdefault("pyodbc", pyodbc_stub)

config_stub = types.ModuleType("app.config")
config_stub.settings = SimpleNamespace(
    FAMILY_SALE_CURRENT_EVENT_START_DATE="2026-08-13",
    FAMILY_SALE_PREVIOUS_EVENT_START_DATE="2025-08-14",
    FAMILY_SALE_DB_USER="user",
    FAMILY_SALE_DB_PASSWORD="password",
    FAMILY_SALE_DB_DRIVER="ODBC Driver 17 for SQL Server",
    FAMILY_SALE_DB_HOST="10.28.200.5",
    FAMILY_SALE_DB_PORT=1433,
    FAMILY_SALE_DB_DATABASE="HDTRAN",
    FAMILY_SALE_DB_TRUST_CERT="yes",
    FAMILY_SALE_QUERY_TIMEOUT_SEC=30,
    FAMILY_SALE_STORE_CD="480",
    FAMILY_SALE_CURRENT_POS_START="7701",
    FAMILY_SALE_CURRENT_POS_END="7793",
    FAMILY_SALE_PREVIOUS_POS_START="7701",
    FAMILY_SALE_PREVIOUS_POS_END="7783",
)
original_config_module = sys.modules.get("app.config")
sys.modules["app.config"] = config_stub

from app.family_sale import (
    _query_params,
    calculate_change_rate,
    fetch_family_sale_single,
    normalize_family_sale_period,
)

if original_config_module is None:
    sys.modules.pop("app.config", None)
else:
    sys.modules["app.config"] = original_config_module


class FamilySaleTests(unittest.TestCase):
    def test_recent_hour_uses_given_current_time(self):
        period = normalize_family_sale_period(
            "recent_hour",
            now=datetime(2026, 8, 14, 10, 30),
        )
        self.assertEqual(period["current_start"], datetime(2026, 8, 14, 9, 30))
        self.assertEqual(period["display_end"], datetime(2026, 8, 14, 10, 30))
        self.assertEqual(period["previous_start"], datetime(2025, 8, 15, 9, 30))

    def test_event_day_mapping_uses_explicit_first_day_anchors(self):
        period = normalize_family_sale_period(
            "custom",
            "2026-08-13T00:00",
            "2026-08-13T23:59",
        )
        self.assertEqual(period["previous_start"], datetime(2025, 8, 14, 0, 0))
        self.assertEqual(
            period["previous_display_end"],
            datetime(2025, 8, 14, 23, 59),
        )
        self.assertEqual(period["current_event_start_date"], "2026-08-13")
        self.assertEqual(period["previous_event_start_date"], "2025-08-14")

    def test_custom_end_minute_is_included_by_exclusive_boundary(self):
        period = normalize_family_sale_period(
            "custom",
            "2026-08-14T09:00",
            "2026-08-14T10:59",
        )
        self.assertEqual(
            period["current_end_exclusive"],
            datetime(2026, 8, 14, 11, 0),
        )
        params = _query_params(
            period["current_start"],
            period["current_end_exclusive"],
            "7701",
            "7793",
        )
        self.assertEqual(
            params,
            ("480", "7701", "7793", "20260814", "20260814", "090000", "20260814", "20260814", "110000"),
        )

    def test_fixed_period_preserves_exact_recent_hour_boundary_for_paging(self):
        period = normalize_family_sale_period(
            "fixed",
            "2026-08-14T09:30:15",
            "2026-08-14T10:30:15",
            "2026-08-14T10:30:15",
        )
        self.assertEqual(period["current_start"], datetime(2026, 8, 14, 9, 30, 15))
        self.assertEqual(
            period["current_end_exclusive"],
            datetime(2026, 8, 14, 10, 30, 15),
        )

    def test_single_period_paging_preserves_original_end_boundary(self):
        period = normalize_family_sale_period(
            "single",
            "2025-08-14T09:00:00",
            "2025-08-14T11:01:00",
            "2025-08-14T11:00:00",
        )
        self.assertEqual(
            period["current_end_exclusive"],
            datetime(2025, 8, 14, 11, 1),
        )
        self.assertEqual(period["display_end"], datetime(2025, 8, 14, 11, 0))

    def test_single_period_uses_previous_event_pos_range(self):
        from unittest.mock import MagicMock, patch

        period = normalize_family_sale_period(
            "single",
            "2025-08-14T09:00",
            "2025-08-14T11:00",
        )
        connection = MagicMock()
        connection.__enter__.return_value = connection
        cursor = connection.cursor.return_value
        cursor.fetchall.return_value = []
        with patch("app.family_sale.pyodbc.connect", return_value=connection):
            result = fetch_family_sale_single(period)
        self.assertEqual(result["posStart"], "7701")
        self.assertEqual(result["posEnd"], "7783")

    def test_change_rate_and_zero_denominator(self):
        self.assertEqual(calculate_change_rate(Decimal("120"), Decimal("100")), 20.0)
        self.assertEqual(calculate_change_rate(Decimal("0"), Decimal("0")), 0.0)
        self.assertIsNone(calculate_change_rate(Decimal("10"), Decimal("0")))

    def test_rejects_invalid_or_too_long_period(self):
        with self.assertRaises(ValueError):
            normalize_family_sale_period("custom", "2026-08-15T00:00", "2026-08-14T00:00")
        with self.assertRaises(ValueError):
            normalize_family_sale_period("custom", "2026-01-01T00:00", "2026-03-01T00:00")


if __name__ == "__main__":
    unittest.main()
