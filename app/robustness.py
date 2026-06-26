from __future__ import annotations

import re

# Strip adversarial instruction blocks from complaint text used for classification.
INJECTION_LINE_PATTERNS = [
    re.compile(p, re.IGNORECASE)
    for p in [
        r"ignore (?:all )?(?:previous |prior )?instructions",
        r"disregard (?:all )?(?:previous )?rules",
        r"you are now (?:a |an )?",
        r"system prompt",
        r"classify (?:this )?(?:ticket )?as",
        r"set case_type to",
        r"respond (?:only )?with",
        r"output (?:only )?",
        r"return (?:only )?json",
        r"ask (?:the )?customer for (?:their )?(?:pin|otp|password)",
        r"confirm (?:the )?refund",
        r"promise (?:a )?refund",
    ]
]

TRANSACTION_ID_PATTERN = re.compile(r"\bTXN-\d+\b", re.IGNORECASE)
PHONE_PATTERN = re.compile(r"(?:\+?880|0)1[0-9]{9}\b")


def sanitize_complaint_for_analysis(complaint: str) -> str:
    """Remove prompt-injection style lines; never trust embedded agent instructions."""
    lines = complaint.splitlines()
    kept: list[str] = []
    for line in lines:
        if any(p.search(line) for p in INJECTION_LINE_PATTERNS):
            continue
        kept.append(line)
    cleaned = " ".join(kept).strip()
    return cleaned or complaint.strip()


def extract_transaction_ids(text: str) -> list[str]:
    return [m.upper() for m in TRANSACTION_ID_PATTERN.findall(text)]


def extract_phone_numbers(text: str) -> list[str]:
    numbers: list[str] = []
    for raw in PHONE_PATTERN.findall(text):
        digits = re.sub(r"\D", "", raw)
        if digits.startswith("880"):
            numbers.append("+" + digits)
        elif digits.startswith("01"):
            numbers.append("+88" + digits)
    return numbers


def normalize_phone(value: str) -> str:
    digits = re.sub(r"\D", "", value)
    if digits.startswith("880"):
        return "+" + digits
    if digits.startswith("01"):
        return "+88" + digits
    return value
