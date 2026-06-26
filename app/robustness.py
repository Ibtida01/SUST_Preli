from __future__ import annotations

import re

# Remove adversarial clauses from complaint text used for classification.
INJECTION_PATTERNS = [
    re.compile(p, re.IGNORECASE)
    for p in [
        r"ignore (?:all )?(?:previous |prior )?instructions",
        r"disregard (?:all )?(?:previous )?rules",
        r"you are now (?:a |an )?\w+",
        r"system prompt",
        r"classify (?:this )?(?:ticket )?as\s+\w+",
        r"set case_type to\s+\w+",
        r"respond (?:only )?with\b.*",
        r"output (?:only )?\b.*",
        r"return (?:only )?json\b.*",
        r"ask (?:the )?customer for (?:their )?(?:pin|otp|password)",
        r"confirm (?:the )?refund",
        r"promise (?:a )?refund",
        r"say (?:the )?refund is confirmed",
        r"refund is confirmed",
        r"forget (?:all )?(?:previous )?rules",
        r"you must (?:say|respond|classify|output)",
        r"pretend (?:you are|to be)",
    ]
]

TRANSACTION_ID_PATTERN = re.compile(r"\bTXN-\d+\b", re.IGNORECASE)
BANGLA_DIGITS = str.maketrans("০১২৩৪৫৬৭৮৯", "0123456789")
# BD mobile: optional spaces/dashes between country code and subscriber number
PHONE_CANDIDATE_PATTERN = re.compile(
    r"\+?880[\d\s\-]{10,16}|0\s*1[\d\s\-]{9,14}",
    re.IGNORECASE,
)


def normalize_digits(text: str) -> str:
    return text.translate(BANGLA_DIGITS)


def sanitize_complaint_for_analysis(complaint: str) -> str:
    """Strip injection clauses in-place so legitimate text on the same line is kept."""
    cleaned = complaint
    for pattern in INJECTION_PATTERNS:
        cleaned = pattern.sub(" ", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    return cleaned


def extract_transaction_ids(text: str) -> list[str]:
    return [m.upper() for m in TRANSACTION_ID_PATTERN.findall(text)]


def extract_phone_numbers(text: str) -> list[str]:
    numbers: list[str] = []
    seen: set[str] = set()
    normalized_text = normalize_digits(text)
    for raw in PHONE_CANDIDATE_PATTERN.findall(normalized_text):
        digits = re.sub(r"\D", "", raw)
        normalized: str | None = None
        if len(digits) == 13 and digits.startswith("8801"):
            normalized = "+" + digits
        elif len(digits) == 11 and digits.startswith("01"):
            normalized = "+88" + digits
        if normalized and normalized not in seen:
            seen.add(normalized)
            numbers.append(normalized)
    return numbers


def normalize_phone(value: str) -> str:
    digits = re.sub(r"\D", "", normalize_digits(value))
    if len(digits) == 13 and digits.startswith("880"):
        return "+" + digits
    if len(digits) == 11 and digits.startswith("01"):
        return "+88" + digits
    return value
