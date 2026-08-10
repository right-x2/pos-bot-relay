import json
import urllib.error
import urllib.request

from app.config import settings


def _get_base_url() -> str:
    base_url = (settings.MCP_BASE_URL or "").strip()
    if not base_url:
        raise RuntimeError("MCP_BASE_URL is not set")
    return base_url.rstrip("/")


def _build_headers() -> dict:
    headers = {"Content-Type": "application/json"}
    api_key = (settings.MCP_API_KEY or "").strip()
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    return headers


def create_pos_master(pos_no: str, requested_by: str | None):
    payload = {"posNo": pos_no, "requestedBy": requested_by}
    data = json.dumps(payload).encode("utf-8")

    req = urllib.request.Request(
        url=f"{_get_base_url()}/tools/create_pos_master",
        data=data,
        headers=_build_headers(),
        method="POST",
    )

    try:
        with urllib.request.urlopen(req, timeout=settings.MCP_TIMEOUT_SEC) as resp:
            body = resp.read().decode("utf-8", errors="replace").strip()
            return json.loads(body) if body else {"ok": True}
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace").strip()
        raise RuntimeError(f"MCP HTTP {exc.code}: {body}") from exc


def fetch_pos_patterns(
    pos_no: str,
    group_limit: int | None = None,
    detail_limit: int | None = None,
):
    if not pos_no or not pos_no.strip():
        raise ValueError("pos_no is empty")

    payload = {"posNo": pos_no, "groupLimit": group_limit, "detailLimit": detail_limit}
    data = json.dumps(payload).encode("utf-8")

    req = urllib.request.Request(
        url=f"{_get_base_url()}/tools/pattern_lookup",
        data=data,
        headers=_build_headers(),
        method="POST",
    )

    try:
        with urllib.request.urlopen(req, timeout=settings.MCP_TIMEOUT_SEC) as resp:
            body = resp.read().decode("utf-8", errors="replace").strip()
            return json.loads(body) if body else {"ok": True}
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace").strip()
        raise RuntimeError(f"MCP HTTP {exc.code}: {body}") from exc
