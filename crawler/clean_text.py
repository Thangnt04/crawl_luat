from __future__ import annotations

import re


NOISE_PATTERNS = [
    r"^\s*trang chủ\s*$",
    r"^\s*liên hệ\s*$",
    r"^\s*đăng nhập\s*$",
    r"^\s*hướng dẫn khai thác\s*$",
    r"^\s*sơ đồ cổng thông tin\s*$",
]


def clean_legal_text(text: str) -> str:
    if not text:
        return ""

    text = text.replace("\u00a0", " ")
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"[ \t]+", " ", text)

    lines = [line.strip() for line in text.split("\n")]
    cleaned_lines: list[str] = []
    seen_recent: set[str] = set()
    for line in lines:
        if not line:
            continue
        lowered = line.lower()
        if any(re.match(pattern, lowered) for pattern in NOISE_PATTERNS):
            continue
        compact = re.sub(r"\s+", " ", line)
        if compact in seen_recent:
            continue
        cleaned_lines.append(compact)
        seen_recent.add(compact)
        if len(seen_recent) > 2000:
            seen_recent.clear()

    merged = "\n".join(cleaned_lines)
    merged = re.sub(r"\n{3,}", "\n\n", merged)
    return merged.strip()

