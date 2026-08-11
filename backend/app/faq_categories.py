FAQ_CATEGORY_NAMES = {
    "1": "POS공통",
    "2": "PPOS",
    "3": "APOS",
    "4": "서버",
    "5": "HBO",
    "6": "키오스크",
}

FAQ_CATEGORY_ALIASES = {
    "1": ("1", "POS공통", "POS 공통"),
    "2": ("2", "PPOS"),
    "3": ("3", "APOS"),
    "4": ("4", "서버", "POS서버", "POS 서버"),
    "5": ("5", "HBO"),
    "6": ("6", "KIOSK", "키오스크"),
}


def normalize_faq_category(value: str | None) -> str | None:
    normalized = str(value or "").strip()
    if not normalized:
        return None

    normalized_upper = normalized.upper()
    for code, aliases in FAQ_CATEGORY_ALIASES.items():
        if any(normalized_upper == alias.upper() for alias in aliases):
            return code
    return None
