"""Untrusted text inside prompts (CU-5).

Text a candidate wrote (own questions, focus chips) goes into prompts as one JSON-quoted line.
Angle brackets are removed, so the text cannot close an `<untrusted_input>` block, and the JSON
quoting escapes any quote marks, so it cannot end the string early.
"""

from __future__ import annotations

import json


def quote_untrusted(text: str) -> str:
    """Untrusted text as one quoted, escaped line, without angle brackets."""
    flat = " ".join(text.replace("<", " ").replace(">", " ").split())
    return json.dumps(flat, ensure_ascii=False)
