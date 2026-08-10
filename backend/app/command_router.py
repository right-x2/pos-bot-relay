import re

_MASTER = r"\uB9C8\uC2A4\uD130"
_CREATE = r"(?:\uC0DD\uC131|\uB4F1\uB85D|\uB9CC\uB4E4\uC5B4)"
_TAIL = r"(?:\s*(?:\uD574\s*\uC918|\uD574\s*\uC8FC\uC138\uC694|\uC918|\uC8FC\uC138\uC694))?"
_POS = r"(?:pos\s*)?"
_PATTERN = r"(?:\uD328\uD134|pattern|ptn)"
_UPDATE_VERB = r"(?:\uC218\uC815|\uBCC0\uACBD|\uC5C5\uB370\uC774\uD2B8|\uAC31\uC2E0|\uBC14\uAFB8|\uBC14\uAFB8\uC5B4|\uBC14\uAFB8\uC5B4\uC918|\uBC14\uAFD4|\uBC14\uAFD4\uC918|\uC124\uC815|\uC138\uD305|\uC14B\uD305|\uC801\uC6A9)"
_POS_TARGET = r"(?:\d{3,6}(?:\s*(?:,\s*\d{3,6})+|\s*[~-]\s*\d{3,6})?)"

_PATTERNS = [
    re.compile(
        rf"(?P<pos>{_POS_TARGET})\s*{_POS}{_MASTER}\s*{_CREATE}{_TAIL}",
        re.IGNORECASE,
    ),
    re.compile(
        rf"{_POS}{_MASTER}\s*{_CREATE}{_TAIL}.*?(?P<pos>{_POS_TARGET})",
        re.IGNORECASE,
    ),
]

_POS_PATTERNS = [
    re.compile(r"(?:pos\s*\uBC88\uD638|pos\uBC88\uD638|pos)\s*(?P<pos>\d{3,6})", re.IGNORECASE),
    re.compile(r"(?P<pos>\d{3,6})\s*pos", re.IGNORECASE),
]

_PATTERN_CODE_PATTERNS = [
    re.compile(r"(?:\uD328\uD134\s*\uCF54\uB4DC|pattern\s*code|ptn\s*code)\s*[:=]?\s*(?P<value>[A-Za-z0-9_-]{2,})", re.IGNORECASE),
    re.compile(r"(?:\uD328\uD134|pattern|ptn)\s*[:=]?\s*(?P<value>\d{2,})", re.IGNORECASE),
    re.compile(r"(?P<value>\d{2,})\s*(?:\uBC88\s*)?(?:\uD328\uD134|pattern|ptn)", re.IGNORECASE),
]

_PATTERN_NAME_PATTERNS = [
    re.compile(r"(?:\uD328\uD134\s*\uBA85|pattern\s*name)\s*[:=]?\s*(?P<value>\"[^\"]+\"|'[^']+'|[^\s]+)", re.IGNORECASE),
    re.compile(r"(?P<value>[A-Za-z0-9_-]*[A-Za-z][A-Za-z0-9_-]*)\s*(?:related\s*)?\uD328\uD134", re.IGNORECASE),
    re.compile(r"(?P<value>[\uAC00-\uD7A3A-Za-z0-9_-]{2,})\s*(?:\uAD00\uB828\s*)?\uD328\uD134"),
]

_PATTERN_NAME_IGNORE = {
    "pos",
    "pos\uBC88\uD638",
    "posno",
    "pos_no",
    "pattern",
    "ptn",
    "\uD328\uD134",
    "\uD328\uD134\uADF8\uB8F9",
    "\uADF8\uB8F9",
    "\uC870\uD68C",
    "\uD655\uC778",
    "\uAD00\uB828",
}

_UPDATE_VALUE_PATTERNS = [
    re.compile(r"(?:\uAC12|value|val)\s*[:=]?\s*(?P<value>\"[^\"]+\"|'[^']+'|[^\s]+)", re.IGNORECASE),
    re.compile(
        rf"(?P<value>\"[^\"]+\"|'[^']+'|[^\s]+)\s*(?:\uC73C\uB85C|\uB85C)\s*(?:{_UPDATE_VERB})",
        re.IGNORECASE,
    ),
]


def _extract_pos_no(text: str) -> str | None:
    for pattern in _POS_PATTERNS:
        match = pattern.search(text)
        if match:
            return match.group("pos")

    match = re.search(r"(?<![A-Za-z0-9])(?P<pos>\d{3,6})(?![A-Za-z0-9])", text)
    if match:
        return match.group("pos")

    return None


def _clean_token(value: str) -> str:
    return value.strip().strip("\"'").strip()


def _clean_pos_target(value: str) -> str:
    return re.sub(r"\s+", "", value.strip())


def _extract_pattern_token(text: str, pos_no: str | None = None) -> dict | None:
    numeric_tokens = re.findall(r"\d{2,}", text)

    for pattern in _PATTERN_CODE_PATTERNS:
        match = pattern.search(text)
        if match:
            value = _clean_token(match.group("value"))
            if value:
                if pos_no and value == pos_no and len(numeric_tokens) <= 1:
                    continue
                return {"type": "code", "value": value}

    for pattern in _PATTERN_NAME_PATTERNS:
        match = pattern.search(text)
        if match:
            value = _clean_token(match.group("value"))
            if not value:
                continue
            lower = value.lower()
            if lower in _PATTERN_NAME_IGNORE:
                continue
            if lower.isdigit():
                continue
            return {"type": "name", "value": value}

    return None


def _extract_update_value(text: str) -> str | None:
    for pattern in _UPDATE_VALUE_PATTERNS:
        match = pattern.search(text)
        if match:
            value = _clean_token(match.group("value"))
            if value:
                return value
    return None


def parse_command(text: str):
    if not text:
        return None

    for pattern in _PATTERNS:
        match = pattern.search(text)
        if match:
            return {
                "type": "CREATE_POS_MASTER",
                "pos_no": _clean_pos_target(match.group("pos")),
            }

    if re.search(_PATTERN, text, re.IGNORECASE) and re.search(_UPDATE_VERB, text, re.IGNORECASE):
        pos_no = _extract_pos_no(text)
        pattern_token = _extract_pattern_token(text, pos_no)
        update_value = _extract_update_value(text)

        if pos_no and pattern_token and update_value is not None:
            return {
                "type": "PATTERN_UPDATE",
                "pos_no": pos_no,
                "pattern": pattern_token,
                "value": update_value,
            }
        if pos_no is None:
            return {
                "type": "PATTERN_UPDATE_MISSING_POS",
            }
        if pattern_token is None:
            return {
                "type": "PATTERN_UPDATE_MISSING_PATTERN",
                "pos_no": pos_no,
            }
        return {
            "type": "PATTERN_UPDATE_MISSING_VALUE",
            "pos_no": pos_no,
            "pattern": pattern_token,
        }

    if re.search(_PATTERN, text, re.IGNORECASE):
        pos_no = _extract_pos_no(text)
        pattern_token = _extract_pattern_token(text, pos_no)

        if pos_no:
            return {
                "type": "PATTERN_LOOKUP",
                "pos_no": pos_no,
                "pattern": pattern_token,
            }
        if pattern_token or pos_no is None:
            return {
                "type": "PATTERN_LOOKUP_MISSING_POS",
                "pattern": pattern_token,
            }

    return None
