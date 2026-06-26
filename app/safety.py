from __future__ import annotations

import re

CREDENTIAL_REQUEST_PATTERNS = [
    re.compile(p, re.IGNORECASE)
    for p in [
        r"\b(?:share|provide|send|enter|give)\b.{0,40}\b(?:pin|otp|password|card number)\b",
        r"\b(?:what is|tell us|confirm)\b.{0,30}\b(?:pin|otp|password)\b",
    ]
]

UNSAFE_REFUND_PATTERNS = [
    re.compile(p, re.IGNORECASE)
    for p in [
        r"\bwe will refund\b",
        r"\bwe have refunded\b",
        r"\brefund (?:has been|is) (?:processed|approved|completed)\b",
        r"\bwe will reverse\b",
        r"\bamount (?:has been|will be) (?:returned|credited) immediately\b",
        r"\baccount (?:has been|will be) unblocked\b",
    ]
]

SAFE_REFUND_PHRASE = "any eligible amount will be returned through official channels"
CREDENTIAL_WARNING_EN = "Please do not share your PIN or OTP with anyone."
CREDENTIAL_WARNING_BN = "অনুগ্রহ করে কারো সাথে আপনার পিন বা ওটিপি শেয়ার করবেন না।"


def is_bangla_text(text: str) -> bool:
    return bool(re.search(r"[\u0980-\u09FF]", text))


def apply_safety_guardrails(customer_reply: str, recommended_next_action: str, language: str | None) -> tuple[str, str]:
    reply = customer_reply.strip()
    action = recommended_next_action.strip()

    for pattern in CREDENTIAL_REQUEST_PATTERNS:
        reply = pattern.sub(CREDENTIAL_WARNING_EN, reply)

    for pattern in UNSAFE_REFUND_PATTERNS:
        reply = pattern.sub(
            "Our team will review the case and any eligible amount will be returned through official channels.",
            reply,
        )

    warning = CREDENTIAL_WARNING_BN if language == "bn" or is_bangla_text(reply) else CREDENTIAL_WARNING_EN
    if warning.lower() not in reply.lower() and "পিন" not in reply:
        reply = f"{reply.rstrip('.')}. {warning}"

    if SAFE_REFUND_PHRASE not in reply.lower() and re.search(
        r"\brefund\b|\breversal\b|\breturned\b", reply, re.IGNORECASE
    ):
        if SAFE_REFUND_PHRASE not in reply:
            reply = f"{reply.rstrip('.')}. Our team will review the case and {SAFE_REFUND_PHRASE}."

    for pattern in UNSAFE_REFUND_PATTERNS:
        action = pattern.sub("Initiate the official review workflow per policy.", action)

    return reply, action
