import importlib.util
import sys
import types
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch


pyodbc_stub = types.ModuleType("pyodbc")
pyodbc_stub.connect = lambda *_args, **_kwargs: None
sys.modules.setdefault("pyodbc", pyodbc_stub)

pandas_stub = types.ModuleType("pandas")
pandas_stub.DataFrame = object
sys.modules.setdefault("pandas", pandas_stub)

config_stub = types.ModuleType("app.config")
config_stub.settings = SimpleNamespace(
    DB_DRIVER="driver",
    DB_SERVER="server",
    DB_DATABASE="database",
    DB_USER="user",
    DB_PASSWORD="password",
    DB_TRUST_CERT="yes",
)
sys.modules.setdefault("app.config", config_stub)

faq_categories_stub = types.ModuleType("app.faq_categories")
faq_categories_stub.FAQ_CATEGORY_ALIASES = {}
sys.modules.setdefault("app.faq_categories", faq_categories_stub)

db_path = Path(__file__).resolve().parents[1] / "app" / "db.py"
db_spec = importlib.util.spec_from_file_location("item_db_under_test", db_path)
if db_spec is None or db_spec.loader is None:
    raise RuntimeError("failed to load app.db for item contract tests")
db = importlib.util.module_from_spec(db_spec)
db_spec.loader.exec_module(db)


class ItemDbContractTests(unittest.TestCase):
    def test_item_lookup_selects_display_columns(self):
        with patch.object(db, "_fetch_rows", return_value=[]) as fetch:
            db.fetch_item_master_by_code("8801234567890", "210")

        sql, params = fetch.call_args.args
        for column in (
            "EMP_ENURI_RT",
            "GRP_CMP_ENURI_RT",
            "GNRL_MEM_ENURI_RT",
            "JSMN_BLK_ENURI_RT",
            "UCARD_PNT_ACM_RT",
            "OUTLET_PNT_ACM_RT",
            "TCP_PNT_ACM_RT",
            "HCARD_PNT_ACM_RT",
            "USE_START_DT",
            "USE_END_DT",
        ):
            self.assertIn(column, sql)
        self.assertEqual(params, ("210", "8801234567890"))


if __name__ == "__main__":
    unittest.main()
