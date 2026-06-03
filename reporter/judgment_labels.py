def to_display_judgment(judgment: str) -> str:
    value = (judgment or "").strip()
    normalized = value.upper()

    mapping = {
        "VIOLATION": "乱价",
        "DELIST": "需下架",
        "REVIEW": "需人工审核",
        "PREVIEW": "需人工审核",
        "NORMAL": "正常",
        "SUSPECTED": "疑似引流",
    }
    return mapping.get(normalized, value)
