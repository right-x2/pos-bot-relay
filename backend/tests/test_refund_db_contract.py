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
db_spec = importlib.util.spec_from_file_location("refund_db_under_test", db_path)
if db_spec is None or db_spec.loader is None:
    raise RuntimeError("failed to load app.db for refund contract tests")
db = importlib.util.module_from_spec(db_spec)
db_spec.loader.exec_module(db)


class _FakeCursor:
    def __init__(self, deleted=1):
        self.deleted = deleted
        self.sql = ""
        self.params = ()

    def execute(self, sql, *params):
        self.sql = sql
        self.params = params
        return self

    def fetchone(self):
        return (self.deleted,)


class _FakeConnection:
    def __init__(self, cursor):
        self._cursor = cursor
        self.committed = False

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def cursor(self):
        return self._cursor

    def commit(self):
        self.committed = True


class RefundDbContractTests(unittest.TestCase):
    def test_lookup_passes_all_four_original_transaction_keys(self):
        with patch.object(db, "_fetch_rows", return_value=[]) as fetch:
            db.fetch_refund_progress("210", "20260812", "0011", "000123")

        sql, params = fetch.call_args.args
        self.assertIn("FROM HDTRAN..TR_POS_TRANCALL_RFND", sql)
        for column in ("STORE_CD = ?", "SALE_DT = ?", "POS_NO = ?", "DEAL_NO = ?"):
            self.assertIn(column, sql)
        self.assertEqual(params, ("210", "20260812", "0011", "000123"))

    def test_delete_uses_all_four_keys_and_commits(self):
        cursor = _FakeCursor(deleted=1)
        connection = _FakeConnection(cursor)
        with (
            patch.object(db, "get_conn_str", return_value="connection-string"),
            patch.object(db.pyodbc, "connect", return_value=connection),
        ):
            deleted = db.delete_refund_progress("210", "20260812", "0011", "000123")

        self.assertEqual(deleted, 1)
        self.assertTrue(connection.committed)
        for column in ("STORE_CD = ?", "SALE_DT = ?", "POS_NO = ?", "DEAL_NO = ?"):
            self.assertIn(column, cursor.sql)
        self.assertEqual(cursor.params, ("210", "20260812", "0011", "000123"))


if __name__ == "__main__":
    unittest.main()
