import logging
from datetime import datetime, date
from decimal import Decimal

import pyodbc
import pandas as pd
from app.config import settings

TEST_STORE_CD = "210"
logger = logging.getLogger("poschat.db")

def get_conn_str() -> str:
    return (
        f"DRIVER={{{settings.DB_DRIVER}}};"
        f"SERVER={settings.DB_SERVER};"
        f"DATABASE={settings.DB_DATABASE};"
        f"UID={settings.DB_USER};"
        f"PWD={settings.DB_PASSWORD};"
        f"TrustServerCertificate={settings.DB_TRUST_CERT};"
    )


def _serialize_db_value(value):
    if value is None:
        return None
    if isinstance(value, (datetime, date)):
        return value.isoformat(sep=" ")
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, bytes):
        try:
            return value.decode("utf-8")
        except UnicodeDecodeError:
            return value.decode("cp949", errors="replace")
    return value


def _value_length(value) -> int | None:
    if value is None:
        return None
    return len(str(value))


def _value_preview(value, limit: int = 120) -> str | None:
    if value is None:
        return None
    text = str(value)
    if len(text) <= limit:
        return text
    return f"{text[:limit]}...(truncated)"


def _fetch_table_rows(table_name: str, limit: int | None = None) -> list[dict]:
    sql = f"SELECT TOP (?) * FROM {table_name}" if limit else f"SELECT * FROM {table_name}"

    with pyodbc.connect(get_conn_str()) as conn:
        cur = conn.cursor()
        if limit:
            cur.execute(sql, limit)
        else:
            cur.execute(sql)
        rows = cur.fetchall()
        columns = [col[0] for col in cur.description]

    results = []
    for row in rows:
        results.append(
            {columns[idx]: _serialize_db_value(value) for idx, value in enumerate(row)}
        )
    return results


def _fetch_rows(sql: str, params: tuple | list | None = None) -> list[dict]:
    with pyodbc.connect(get_conn_str()) as conn:
        cur = conn.cursor()
        if params is None:
            cur.execute(sql)
        else:
            cur.execute(sql, params)
        rows = cur.fetchall()
        columns = [col[0] for col in cur.description]

    results = []
    for row in rows:
        results.append(
            {columns[idx]: _serialize_db_value(value) for idx, value in enumerate(row)}
        )
    return results


def fetch_pos_pattern_groups(limit: int | None = None) -> list[dict]:
    distinct_top = "DISTINCT TOP (?) " if limit else "DISTINCT "
    if limit:
        sql = """
        SELECT {distinct_top}g.*
        FROM HDMST..POS_MST m
        JOIN HDMST..POS_PTN_GRP_MST g
          ON m.PTN_GRP_CD = g.PTN_GRP_CD
        WHERE m.STORE_CD = ?
        """.format(distinct_top=distinct_top)
        params = (limit, TEST_STORE_CD)
    else:
        sql = """
        SELECT DISTINCT g.*
        FROM HDMST..POS_MST m
        JOIN HDMST..POS_PTN_GRP_MST g
          ON m.PTN_GRP_CD = g.PTN_GRP_CD
        WHERE m.STORE_CD = ?
        """
        params = (TEST_STORE_CD,)

    return _fetch_rows(sql, params)


def fetch_pos_pattern_details(limit: int | None = None) -> list[dict]:
    distinct_top = "DISTINCT TOP (?) " if limit else "DISTINCT "
    if limit:
        sql = """
        SELECT {distinct_top}d.*
        FROM HDMST..POS_MST m
        JOIN HDMST..POS_PTN_DTL d
          ON m.PTN_GRP_CD = d.PTN_GRP_CD
        WHERE m.STORE_CD = ?
        """.format(distinct_top=distinct_top)
        params = (limit, TEST_STORE_CD)
    else:
        sql = """
        SELECT DISTINCT d.*
        FROM HDMST..POS_MST m
        JOIN HDMST..POS_PTN_DTL d
          ON m.PTN_GRP_CD = d.PTN_GRP_CD
        WHERE m.STORE_CD = ?
        """
        params = (TEST_STORE_CD,)

    return _fetch_rows(sql, params)


def _normalize_lookup_token(value: str | None) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _build_pattern_lookup_filter_clause(
    pattern_code: str | None = None,
    pattern_name: str | None = None,
) -> tuple[str, tuple]:
    code = _normalize_lookup_token(pattern_code)
    name = _normalize_lookup_token(pattern_name)

    if code and name:
        raise ValueError("pattern_code and pattern_name cannot be used together")

    if code:
        return "AND d.PTN_CD = ?", (code,)
    if name:
        return "AND d.PTN_NM LIKE ?", (f"%{name}%",)
    return "", ()


def fetch_pos_pattern_groups_by_pos(
    pos_no: str,
    limit: int | None = None,
    pattern_code: str | None = None,
    pattern_name: str | None = None,
) -> list[dict]:
    filter_sql, filter_params = _build_pattern_lookup_filter_clause(pattern_code, pattern_name)
    has_filter = bool(filter_sql)
    detail_join = """
        JOIN HDMST..POS_PTN_DTL d
          ON g.PTN_GRP_CD = d.PTN_GRP_CD
    """ if has_filter else ""
    distinct_top = "DISTINCT TOP (?) " if limit else "DISTINCT "
    sql = f"""
    SELECT {distinct_top}g.*
    FROM HDMST..POS_MST m
    JOIN HDMST..POS_PTN_GRP_MST g
      ON m.PTN_GRP_CD = g.PTN_GRP_CD
    {detail_join}
    WHERE m.POS_NO = ?
      AND m.STORE_CD = ?
      {filter_sql}
    """
    params = (limit, pos_no, TEST_STORE_CD, *filter_params) if limit else (pos_no, TEST_STORE_CD, *filter_params)
    rows = _fetch_rows(sql, params)
    return rows


def fetch_pos_pattern_details_by_pos(
    pos_no: str,
    limit: int | None = None,
    pattern_code: str | None = None,
    pattern_name: str | None = None,
) -> list[dict]:
    filter_sql, filter_params = _build_pattern_lookup_filter_clause(pattern_code, pattern_name)
    distinct_top = "DISTINCT TOP (?) " if limit else "DISTINCT "
    sql = f"""
    SELECT {distinct_top}d.*
    FROM HDMST..POS_MST m
    JOIN HDMST..POS_PTN_GRP_MST g
      ON m.PTN_GRP_CD = g.PTN_GRP_CD
    JOIN HDMST..POS_PTN_DTL d
      ON g.PTN_GRP_CD = d.PTN_GRP_CD
    WHERE m.POS_NO = ?
      AND m.STORE_CD = ?
      {filter_sql}
    """
    params = (limit, pos_no, TEST_STORE_CD, *filter_params) if limit else (pos_no, TEST_STORE_CD, *filter_params)
    rows = _fetch_rows(sql, params)
    return rows


def fetch_pos_pattern_group_by_pos(pos_no: str) -> dict | None:
    rows = fetch_pos_pattern_groups_by_pos(pos_no, limit=1)
    return rows[0] if rows else None


def _build_pattern_lookup_page_clause(
    search_type: str | None,
    search_value: str | None,
) -> tuple[str, tuple]:
    if search_type is None:
        return "", ()

    search_type_token = str(search_type).strip()
    search_value_token = _normalize_lookup_token(search_value)

    if not search_type_token:
        raise ValueError("search_type is required")
    if search_type_token not in ("0", "1"):
        raise ValueError("search_type must be 0 or 1")

    if search_value_token is None:
        raise ValueError("search_value is required")

    if search_type_token == "0":
        return "AND b.PTN_CD = ?", (search_value_token,)

    return "AND b.PTN_NM LIKE ?", (f"%{search_value_token}%",)


def fetch_pos_pattern_lookup_count_by_pos(
    pos_no: str,
    search_type: str | None,
    search_value: str | None,
) -> int:
    filter_sql, filter_params = _build_pattern_lookup_page_clause(search_type, search_value)
    sql = f"""
    WITH base AS (
        SELECT DISTINCT
            a.POS_NO,
            b.PTN_GRP_CD,
            b.PTN_CD,
            b.PTN_NM,
            b.PTN_VAL,
            b.PTN_DTL_BIGO
        FROM HDMST..POS_MST a
        JOIN HDMST..POS_PTN_DTL b
          ON a.STORE_CD = b.STORE_CD
         AND a.PTN_GRP_CD = b.PTN_GRP_CD
        WHERE a.POS_NO = ?
          AND a.STORE_CD = ?
          {filter_sql}
    )
    SELECT COUNT(1) AS TOTAL_COUNT
    FROM base
    """
    rows = _fetch_rows(sql, (pos_no, TEST_STORE_CD, *filter_params))
    if not rows:
        return 0
    return int(rows[0].get("TOTAL_COUNT") or 0)


def fetch_pos_pattern_lookup_page_by_pos(
    pos_no: str,
    search_type: str | None,
    search_value: str | None,
    page: int,
    page_size: int = 10,
) -> list[dict]:
    filter_sql, filter_params = _build_pattern_lookup_page_clause(search_type, search_value)
    page_no = max(int(page or 1), 1)
    page_size = max(int(page_size or 10), 1)
    offset = (page_no - 1) * page_size

    sql = f"""
    WITH base AS (
        SELECT DISTINCT
            a.POS_NO,
            b.PTN_GRP_CD,
            b.PTN_CD,
            b.PTN_NM,
            b.PTN_VAL,
            b.PTN_DTL_BIGO
        FROM HDMST..POS_MST a
        JOIN HDMST..POS_PTN_DTL b
          ON a.STORE_CD = b.STORE_CD
         AND a.PTN_GRP_CD = b.PTN_GRP_CD
        WHERE a.POS_NO = ?
          AND a.STORE_CD = ?
          {filter_sql}
    )
    SELECT
        POS_NO,
        PTN_GRP_CD,
        PTN_CD,
        PTN_NM,
        PTN_VAL,
        PTN_DTL_BIGO
    FROM base
    ORDER BY PTN_CD, PTN_NM
    OFFSET ? ROWS FETCH NEXT ? ROWS ONLY
    """

    rows = _fetch_rows(sql, (pos_no, TEST_STORE_CD, *filter_params, offset, page_size))
    return rows


def fetch_item_master_by_code(item_cd: str, store_cd: str = TEST_STORE_CD) -> dict | None:
    sql = """
    SELECT TOP 1
        STORE_CD,
        ITEM_CD,
        ITEM_NM,
        BILL_ITEM_NM,
        SALE_KND,
        ITEM_GRP,
        VEN_CD,
        PC_CD,
        CONER_CD,
        USE_YN
    FROM HDMST..ITM_ITEM_MST
    WHERE STORE_CD = ?
      AND ITEM_CD = ?
    """

    rows = _fetch_rows(sql, (store_cd, item_cd))
    return rows[0] if rows else None


def fetch_plu_master_by_code(code: str, store_cd: str = TEST_STORE_CD) -> dict | None:
    sql = """
    SELECT TOP 1
        STORE_CD,
        PLU_CD,
        SCAN_CD1,
        SCAN_CD2,
        PLU_NM,
        BILL_PLU_NM,
        ITEM_CD,
        ITEM_NM,
        BRAND_CD,
        PC_CD,
        CONER_CD,
        ITEM_GRP,
        BOT_CD,
        BOT_SHOPBAG_TP,
        BOT_PRC,
        DLV_STCK_MNG_YN,
        FNB_OPT_YN,
        EVENT_KND_CD,
        GNRL_PRC,
        OP_CD,
        SALE_TP,
        PRC_EVT_CD,
        PRC_EVT_ST_DT,
        PRC_EVT_ED_DT,
        PRC_EVT_PRC,
        PRC_EVT_OP_CD,
        PRC_EVT_SALE_TP,
        NN_EVT_CD,
        NN_EVT_NM,
        NN_EVT_ST_DT,
        NN_EVT_ED_DT,
        NN_EVT_BASE_QTY,
        NN_EVT_DC_QTY,
        NN_EVT_OP_CD,
        NN_EVT_SALE_TP,
        TRGT_EVT_CD_1,
        TRGT_EVT_NM_1,
        TRGT_EVT_PRC_1,
        TRGT_EVT_ST_DT_1,
        TRGT_EVT_ED_DT_1,
        TRGT_EVT_OP_CD_1,
        TRGT_EVT_SALE_TP_1,
        TRGT_EVT_CD_2,
        TRGT_EVT_NM_2,
        TRGT_EVT_PRC_2,
        TRGT_EVT_ST_DT_2,
        TRGT_EVT_ED_DT_2,
        TRGT_EVT_OP_CD_2,
        TRGT_EVT_SALE_TP_2,
        TRGT_EVT_CD_3,
        TRGT_EVT_NM_3,
        TRGT_EVT_PRC_3,
        TRGT_EVT_ST_DT_3,
        TRGT_EVT_ED_DT_3,
        TRGT_EVT_OP_CD_3,
        TRGT_EVT_SALE_TP_3,
        TRGT_EVT_CD_4,
        TRGT_EVT_NM_4,
        TRGT_EVT_PRC_4,
        TRGT_EVT_ST_DT_4,
        TRGT_EVT_ED_DT_4,
        TRGT_EVT_OP_CD_4,
        TRGT_EVT_SALE_TP_4,
        TRGT_EVT_CD_5,
        TRGT_EVT_NM_5,
        TRGT_EVT_PRC_5,
        TRGT_EVT_ST_DT_5,
        TRGT_EVT_ED_DT_5,
        TRGT_EVT_OP_CD_5,
        TRGT_EVT_SALE_TP_5,
        USE_YN
    FROM HDMST..ITM_PLU_MST
    WHERE STORE_CD = ?
      AND (
            PLU_CD = ?
         OR SCAN_CD1 = ?
         OR SCAN_CD2 = ?
      )
    """

    rows = _fetch_rows(sql, (store_cd, code, code, code))
    return rows[0] if rows else None


def update_pos_pattern_value(
    pos_no: str,
    pattern_type: str,
    pattern_value: str,
    new_value: str,
    store_cd: str,
) -> int:
    if pattern_type == "name":
        condition = "d.PTN_NM = ?"
    else:
        condition = "d.PTN_CD = ?"

    sql = f"""
    UPDATE d
    SET d.PTN_VAL = ?
    FROM HDMST..POS_PTN_DTL d
    JOIN HDMST..POS_MST m
      ON m.STORE_CD = d.STORE_CD
     AND m.PTN_GRP_CD = d.PTN_GRP_CD
    WHERE m.STORE_CD = ?
      AND m.POS_NO = ?
      AND {condition}
    """

    with pyodbc.connect(get_conn_str()) as conn:
        cur = conn.cursor()
        cur.execute(sql, new_value, store_cd, pos_no, pattern_value)
        rows = cur.rowcount
        conn.commit()

    return rows


def update_pos_pattern_value_by_group_code(
    pattern_group_code: str,
    pattern_code: str,
    pattern_value: str,
    store_cd: str,
) -> int:
    sql = """
    UPDATE d
    SET d.PTN_VAL = ?
    FROM HDMST..POS_PTN_DTL d
    WHERE d.STORE_CD = ?
      AND d.PTN_GRP_CD = ?
      AND d.PTN_CD = ?
    """

    with pyodbc.connect(get_conn_str()) as conn:
        cur = conn.cursor()
        cur.execute(sql, pattern_value, store_cd, pattern_group_code, pattern_code)
        rows = cur.rowcount
        conn.commit()

    return rows


def fetch_user_assigned_store_code(user_id: str) -> str | None:
    normalized_user_id = str(user_id or "").strip()
    if not normalized_user_id:
        return None

    sql = """
    SELECT TOP 1
        NULLIF(LTRIM(RTRIM(ASSIGN_STORE_CD)), '') AS ASSIGN_STORE_CD
    FROM HDHBO.dbo.SYS_USER_MST
    WHERE USER_ID = ?
    """

    with pyodbc.connect(get_conn_str()) as conn:
        cur = conn.cursor()
        row = cur.execute(sql, normalized_user_id).fetchone()

    if row is None or row.ASSIGN_STORE_CD is None:
        return None
    return str(row.ASSIGN_STORE_CD).strip() or None


FAQ_CATEGORY_ALIASES = {
    "1": ("1", "POS공통"),
    "2": ("2", "PPOS"),
    "3": ("3", "APOS"),
    "4": ("4", "KIOSK", "키오스크"),
    "5": ("5", "서버", "POS서버"),
}


def fetch_top_faq_questions_by_category(
    category: str,
    limit: int = 5,
) -> list[dict]:
    normalized_category = str(category or "").strip()
    aliases = FAQ_CATEGORY_ALIASES.get(normalized_category)
    if aliases is None:
        raise ValueError("Unsupported FAQ category")

    normalized_limit = max(1, min(int(limit), 5))
    placeholders = ", ".join("?" for _ in aliases)
    sql = f"""
    SELECT TOP (?)
        REG_DT,
        SEQ,
        TITLE AS QUESTION,
        CATEGORY,
        COALESCE(TRY_CONVERT(decimal(18, 4), FILLER1), 0) AS WEIGHT
    FROM HDHBO.dbo.POS_FAQ_MST
    WHERE ISNULL(USE_YN, '1') = '1'
      AND CATEGORY IN ({placeholders})
      AND NULLIF(LTRIM(RTRIM(TITLE)), '') IS NOT NULL
    ORDER BY
        COALESCE(TRY_CONVERT(decimal(18, 4), FILLER1), 0) DESC,
        REG_DT DESC,
        TRY_CONVERT(INT, SEQ) DESC
    """

    return _fetch_rows(sql, (normalized_limit, *aliases))

def load_pos_faq_df() -> pd.DataFrame:
    sql = """
    SELECT
        REG_DT,
        SEQ,
        TITLE,
        ANSWER,
        CATEGORY,
        KEYWORDS
    FROM HDHBO..POS_FAQ_MST
    WHERE ISNULL(USE_YN, '1') = '1'
    ORDER BY SEQ
    """

    with pyodbc.connect(get_conn_str()) as conn:
        df = pd.read_sql(sql, conn)

    return df

def increment_faq_counts(items: list[tuple[str, str, float]]) -> None:
    if not items:
        return

    sql = """
    UPDATE HDHBO..POS_FAQ_MST
    SET FILLER1 = COALESCE(FILLER1, CAST(0 AS decimal(13,2)))
        + CAST(? AS decimal(13,2))
    WHERE REG_DT = ? AND SEQ = ?
    """

    with pyodbc.connect(get_conn_str()) as conn:
        cur = conn.cursor()
        cur.fast_executemany = True
        def _to_seq(v):
            if v is None or v == "":
                return v
            try:
                return int(float(v))
            except (ValueError, TypeError):
                return v

        params = [(weight, reg_dt, _to_seq(seq)) for reg_dt, seq, weight in items]
        cur.executemany(sql, params)
        conn.commit()


def is_user_in_auth_group(user_id: str, auth_grp_cd: str = "8000") -> bool:
    sql = """
    SELECT TOP 1 1
    FROM HDHBO..SYS_AUTH_GRP_USER
    WHERE AUTH_GRP_CD = ?
      AND USER_ID = ?
    """

    user_id_value = (user_id or "").strip()
    if not user_id_value:
        return False

    with pyodbc.connect(get_conn_str()) as conn:
        cur = conn.cursor()
        row = cur.execute(sql, auth_grp_cd, user_id_value).fetchone()

    return row is not None


def insert_post_request(
    source: str,
    teams_user_id: str,
    teams_user_name: str,
    category: str,
    question: str,
    answer: str,
    keywords: str | None,
    request_time: datetime,
    use_yn: str = "0",
) -> dict:
    seq_sql = """
    SELECT COALESCE(MAX(CAST(SEQ AS INT)), 0) + 1 AS NEXT_SEQ
    FROM HDHBO.dbo.POS_FAQ_MST WITH (UPDLOCK, HOLDLOCK)
    """
    insert_sql = """
    INSERT INTO HDHBO.dbo.POS_FAQ_MST (
        REG_DT,
        SEQ,
        TITLE,
        ANSWER,
        CATEGORY,
        KEYWORDS,
        USE_YN,
        FILLER1,
        FILLER2,
        FILLER3,
        REG_USER,
        REG_DTM,
        UPD_USER,
        UPD_DTM
    )
    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """
    reg_dt = request_time.strftime("%Y%m%d")
    reg_dtm = request_time.strftime("%Y-%m-%d %H:%M:%S ")

    with pyodbc.connect(get_conn_str()) as conn:
        cur = conn.cursor()
        next_seq = int(cur.execute(seq_sql).fetchone()[0])
        cur.execute(
            insert_sql,
            reg_dt,
            next_seq,
            question,
            answer,
            category,
            keywords,
            use_yn,
            None,
            source,
            teams_user_id,
            teams_user_name,
            reg_dtm,
            teams_user_name,
            reg_dtm,
        )
        conn.commit()

    return {
        "reg_dt": reg_dt,
        "seq": next_seq,
        "use_yn": use_yn,
    }


def get_post_request_by_key(reg_dt: str, seq: int):
    select_sql = """
    SELECT
        REG_DT,
        SEQ,
        TITLE,
        ANSWER,
        CATEGORY,
        KEYWORDS,
        FILLER2,
        FILLER3,
        REG_USER
    FROM HDHBO.dbo.POS_FAQ_MST
    WHERE REG_DT = ?
      AND SEQ = ?
    """

    with pyodbc.connect(get_conn_str()) as conn:
        cur = conn.cursor()
        row = cur.execute(select_sql, reg_dt, seq).fetchone()

    if not row:
        return None

    return {
        "REG_DT": row.REG_DT,
        "SEQ": int(row.SEQ),
        "TITLE": row.TITLE,
        "ANSWER": row.ANSWER,
        "CATEGORY": row.CATEGORY,
        "KEYWORDS": row.KEYWORDS,
        "FILLER2": row.FILLER2,
        "FILLER3": row.FILLER3,
        "REG_USER": row.REG_USER,
    }


def get_post_request_by_seq(seq: int):
    """Return the latest FAQ row for the legacy requestId(SEQ) API."""
    select_sql = """
    SELECT TOP 1
        REG_DT,
        SEQ,
        TITLE,
        ANSWER,
        CATEGORY,
        KEYWORDS,
        FILLER2,
        FILLER3,
        REG_USER
    FROM HDHBO.dbo.POS_FAQ_MST
    WHERE SEQ = ?
    ORDER BY REG_DT DESC
    """

    with pyodbc.connect(get_conn_str()) as conn:
        cur = conn.cursor()
        row = cur.execute(select_sql, seq).fetchone()

    if not row:
        return None

    return {
        "REG_DT": row.REG_DT,
        "SEQ": int(row.SEQ),
        "TITLE": row.TITLE,
        "ANSWER": row.ANSWER,
        "CATEGORY": row.CATEGORY,
        "KEYWORDS": row.KEYWORDS,
        "FILLER2": row.FILLER2,
        "FILLER3": row.FILLER3,
        "REG_USER": row.REG_USER,
    }


def insert_teams_faq_approval_notifications(
    faq_title: str,
    registrant_name: str,
) -> int:
    """Queue an FAQ approval notification for every auth group 8001 user."""
    title = str(faq_title or "").strip() or "제목 없음"
    registrant = str(registrant_name or "").strip() or "알 수 없음"
    message = f"FAQ가 등록됐습니다. FAQ 제목 : {title} / 등록자 : {registrant}"
    message = message[:2000]

    insert_sql = """
    SET NOCOUNT ON;

    INSERT INTO HDMST.dbo.TEAMS_NOTF_SEND_DTL (
        USER_ID,
        MESSAGE,
        SUCC_YN,
        TRY_CNT,
        RGST_ID,
        RGST_IP,
        REG_DTM,
        CHGP_ID,
        CHGP_IP,
        CHG_DTM,
        TASK_GBCD
    )
    SELECT DISTINCT
        LTRIM(RTRIM(USER_ID)),
        ?,
        'N',
        0,
        'POS_FAQ_API',
        NULL,
        GETDATE(),
        NULL,
        NULL,
        NULL,
        '02'
    FROM HDHBO.dbo.SYS_AUTH_GRP_USER
    WHERE AUTH_GRP_CD = '8001'
      AND NULLIF(LTRIM(RTRIM(USER_ID)), '') IS NOT NULL;

    SELECT @@ROWCOUNT AS INSERTED_COUNT;
    """

    with pyodbc.connect(get_conn_str()) as conn:
        cur = conn.cursor()
        row = cur.execute(insert_sql, message).fetchone()
        inserted_count = int(row[0]) if row else 0
        conn.commit()

    return inserted_count


def insert_pos_faq_log(
    user_id: str,
    qry: str | None,
    answer: str | None,
    category: str | None,
    help_yn: str | None = None,
    filler1: str | None = None,
    filler2: str | None = None,
    filler3: str | None = None,
    reg_user: str | None = None,
) -> tuple[str, int]:
    seq_sql = """
    SELECT COALESCE(MAX(CAST(SEQ AS INT)), 0) + 1 AS NEXT_SEQ
    FROM HDHBO.dbo.POS_FAQ_LOG WITH (UPDLOCK, HOLDLOCK)
    WHERE REG_DT = ?
    """
    insert_sql = """
    INSERT INTO HDHBO.dbo.POS_FAQ_LOG (
        REG_DT,
        SEQ,
        USER_ID,
        QRY,
        ANSWER,
        CATEGORY,
        HELP_YN,
        FILLER1,
        FILLER2,
        FILLER3,
        REG_USER,
        REG_DTM,
        UPD_USER,
        UPD_DTM
    )
    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """

    now = datetime.now()
    reg_dt = now.strftime("%Y%m%d")
    reg_dtm = now.strftime("%Y-%m-%d %H:%M:%S")
    user_id_value = (user_id or "").strip() or "anonymous"
    actor = (reg_user or user_id_value).strip() or "system"

    with pyodbc.connect(get_conn_str()) as conn:
        cur = conn.cursor()
        next_seq = int(cur.execute(seq_sql, reg_dt).fetchone()[0])
        params = (
            reg_dt,
            next_seq,
            user_id_value,
            qry,
            answer,
            category,
            help_yn,
            filler1,
            filler2,
            filler3,
            actor,
            reg_dtm,
            actor,
            reg_dtm,
        )
        try:
            cur.execute(insert_sql, params)
        except Exception:
            logger.exception(
                "POS_FAQ_LOG insert failed sql=%s params=%s",
                " ".join(line.strip() for line in insert_sql.splitlines() if line.strip()),
                {
                    "REG_DT": {"length": _value_length(reg_dt), "preview": _value_preview(reg_dt)},
                    "SEQ": {"length": _value_length(next_seq), "preview": _value_preview(next_seq)},
                    "USER_ID": {"length": _value_length(user_id_value), "preview": _value_preview(user_id_value)},
                    "QRY": {"length": _value_length(qry), "preview": _value_preview(qry)},
                    "ANSWER": {"length": _value_length(answer), "preview": _value_preview(answer)},
                    "CATEGORY": {"length": _value_length(category), "preview": _value_preview(category)},
                    "HELP_YN": {"length": _value_length(help_yn), "preview": _value_preview(help_yn)},
                    "FILLER1": {"length": _value_length(filler1), "preview": _value_preview(filler1)},
                    "FILLER2": {"length": _value_length(filler2), "preview": _value_preview(filler2)},
                    "FILLER3": {"length": _value_length(filler3), "preview": _value_preview(filler3)},
                    "REG_USER": {"length": _value_length(actor), "preview": _value_preview(actor)},
                    "REG_DTM": {"length": _value_length(reg_dtm), "preview": _value_preview(reg_dtm)},
                    "UPD_USER": {"length": _value_length(actor), "preview": _value_preview(actor)},
                    "UPD_DTM": {"length": _value_length(reg_dtm), "preview": _value_preview(reg_dtm)},
                },
            )
            raise
        conn.commit()

    return reg_dt, next_seq


def update_pos_faq_log_help_yn(
    reg_dt: str,
    seq: int,
    help_yn: str,
    feedback_text: str | None = None,
) -> int:
    sql = """
    UPDATE HDHBO.dbo.POS_FAQ_LOG
    SET HELP_YN = ?,
        FILLER1 = ?,
        UPD_USER = ?,
        UPD_DTM = ?
    WHERE REG_DT = ?
      AND SEQ = ?
    """

    upd_dtm = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    upd_user = "system"

    with pyodbc.connect(get_conn_str()) as conn:
        cur = conn.cursor()
        cur.execute(sql, help_yn, feedback_text, upd_user, upd_dtm, reg_dt, seq)
        rows = cur.rowcount
        conn.commit()

    return rows


def update_pos_master(store_cd: str, pos_no: str) -> int:
    sql = """
    UPDATE HDTRAN..TR_POS_DOWN
    SET MST_STAT1 = '0',
        MST_STAT2 = '0'
    WHERE STORE_CD = ?
      AND POS_NO = ?
    """

    with pyodbc.connect(get_conn_str()) as conn:
        cur = conn.cursor()
        cur.execute(sql, store_cd, pos_no)
        rows = cur.rowcount
        conn.commit()

    return rows


def update_pos_master_targets(
    store_cd: str,
    pos_numbers: list[str] | None = None,
    pos_range: tuple[str, str] | None = None,
    pos_knd: str | None = None,
) -> int:
    base_sql = """
    UPDATE d
    SET d.MST_STAT1 = '0',
        d.MST_STAT2 = '0'
    FROM HDTRAN..TR_POS_DOWN d
    """
    params: list = []
    where_lines = ["d.STORE_CD = ?"]
    params.append(store_cd)

    if pos_knd:
        base_sql += """
        JOIN HDMST..POS_MST m
          ON m.STORE_CD = d.STORE_CD
         AND m.POS_NO = d.POS_NO
        """
        where_lines.append("m.POS_KND = ?")
        params.append(pos_knd)
    elif pos_range:
        where_lines.append("d.POS_NO BETWEEN ? AND ?")
        params.extend([pos_range[0], pos_range[1]])
    elif pos_numbers:
        placeholders = ", ".join("?" for _ in pos_numbers)
        where_lines.append(f"d.POS_NO IN ({placeholders})")
        params.extend(pos_numbers)
    else:
        raise ValueError("No POS target provided")

    sql = base_sql + "\nWHERE " + "\n  AND ".join(where_lines)

    with pyodbc.connect(get_conn_str()) as conn:
        cur = conn.cursor()
        cur.execute(sql, params)
        rows = cur.rowcount
        conn.commit()

    return rows
