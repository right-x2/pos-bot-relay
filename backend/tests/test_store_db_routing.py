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
config_stub.settings = SimpleNamespace()
sys.modules.setdefault("app.config", config_stub)

faq_categories_stub = types.ModuleType("app.faq_categories")
faq_categories_stub.FAQ_CATEGORY_ALIASES = {}
sys.modules.setdefault("app.faq_categories", faq_categories_stub)

db_path = Path(__file__).resolve().parents[1] / "app" / "db.py"
db_spec = importlib.util.spec_from_file_location("store_db_under_test", db_path)
if db_spec is None or db_spec.loader is None:
    raise RuntimeError("failed to load app.db for store routing tests")
db = importlib.util.module_from_spec(db_spec)
db_spec.loader.exec_module(db)


class _AssignedStoreCursor:
    def __init__(self, assigned_store_cd="220"):
        self.assigned_store_cd = assigned_store_cd
        self.sql = ""
        self.params = ()

    def execute(self, sql, *params):
        self.sql = sql
        self.params = params
        return self

    def fetchone(self):
        if self.assigned_store_cd is None:
            return None
        return SimpleNamespace(ASSIGN_STORE_CD=self.assigned_store_cd)


class _AuthorizedStoreCursor:
    def __init__(self, store_codes):
        self.store_codes = store_codes
        self.sql = ""
        self.params = ()

    def execute(self, sql, *params):
        self.sql = sql
        self.params = params
        return self

    def fetchall(self):
        return [SimpleNamespace(STORE_CD=value) for value in self.store_codes]


class _Connection:
    def __init__(self, cursor):
        self._cursor = cursor

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def cursor(self):
        return self._cursor


class StoreDbRoutingTests(unittest.TestCase):
    def setUp(self):
        db.settings = SimpleNamespace(
            STORE_DB_DRIVER="ODBC Driver 17 for SQL Server",
            STORE_DB_DATABASE="HDHBO",
            STORE_DB_USER="store-user",
            STORE_DB_PASSWORD="store-password",
            STORE_DB_TRUST_CERT="yes",
            STORE_DB_SERVERS={
                "220": "10.30.200.4",
                "260": "10.18.200.4",
                "420": "10.46.200.4",
                "720": "10.153.200.4",
                "750": "10.192.200.4",
            },
        )

    def test_normalizes_email_local_part(self):
        self.assertEqual(
            db.normalize_user_account_id(" rightx2@hyundaifuturenet.co.kr "),
            "rightx2",
        )

    def test_selects_server_by_assigned_store(self):
        expected = {
            "220": "10.30.200.4",
            "260": "10.18.200.4",
            "420": "10.46.200.4",
            "720": "10.153.200.4",
            "750": "10.192.200.4",
        }
        for store_cd, server in expected.items():
            self.assertEqual(db.get_store_db_server(store_cd), server)
            self.assertIn(f"SERVER={server};", db.get_store_conn_str(store_cd))

    def test_rejects_unsupported_store_instead_of_falling_back(self):
        with self.assertRaises(ValueError):
            db.get_store_conn_str("210")

    def test_account_lookup_uses_central_connection_and_local_part(self):
        cursor = _AssignedStoreCursor("220")
        connection = _Connection(cursor)
        with (
            patch.object(db, "get_conn_str", return_value="central-connection") as central,
            patch.object(db.pyodbc, "connect", return_value=connection) as connect,
        ):
            store_cd = db.fetch_user_assigned_store_code(
                "rightx2@hyundaifuturenet.co.kr"
            )

        self.assertEqual(store_cd, "220")
        self.assertIn("HDHBO.dbo.SYS_USER_MST", cursor.sql)
        self.assertIn("ASSIGN_STORE_CD", cursor.sql)
        self.assertEqual(cursor.params, ("rightx2",))
        central.assert_called_once_with()
        connect.assert_called_once_with("central-connection")

    def test_authorized_store_lookup_uses_auth_table_and_deduplicates(self):
        cursor = _AuthorizedStoreCursor(["220", "750", "750"])
        connection = _Connection(cursor)
        with (
            patch.object(db, "get_conn_str", return_value="central-connection"),
            patch.object(db.pyodbc, "connect", return_value=connection),
        ):
            store_codes = db.fetch_user_authorized_store_codes(
                "rightx2@hyundaifuturenet.co.kr"
            )

        self.assertEqual(store_codes, ["220", "750"])
        self.assertIn("HBHBO.dbo.SYS_USER_STR_AUTH", cursor.sql)
        self.assertIn("STORE_CD", cursor.sql)
        self.assertEqual(cursor.params, ("rightx2",))


if __name__ == "__main__":
    unittest.main()
