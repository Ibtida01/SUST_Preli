from __future__ import annotations

import re

UNSAFE_REFUND_PATTERNS = [
    re.compile(p, re.IGNORECASE)
    for p in [
        r"\bwe(?:'ll| will) (?:refund|reverse)\b",
        r"\bwe have refunded\b",
        r"\b(?:has been|was) refunded\b",
        r"\brefund (?:has been|is|was) (?:processed|approved|completed|confirmed)\b",
        r"\bwe will reverse\b",
        r"\b(?:money|amount) (?:will be|has been|is) (?:returned|credited|refunded)\b",
        r"\bamount (?:has been|will be) (?:returned|credited) immediately\b",
        r"\baccount (?:has been|will be) unblocked\b",
        r"\brefund is confirmed\b",
    ]
]

SUSPICIOUS_THIRD_PARTY_PATTERNS = [
    re.compile(p, re.IGNORECASE)
    for p in [
        r"\bcontact (?:us )?on whatsapp\b",
        r"\bmessage (?:us )?on telegram\b",
        r"\bcall this (?:number|line)\b",
        r"\bvisit (?:this )?(?:link|website|url)\b",
        r"\btransfer (?:to|money to) (?:this|another) (?:number|account)\b",
    ]
]

CREDENTIAL_REQUEST_PATTERN = re.compile(
    r"\b(?:share|provide|send|enter|give)\b.{0,40}\b(?:pin|otp|password|card number)\b",
    re.IGNORECASE,
)

SAFE_REFUND_PHRASE = "any eligible amount will be returned through official channels"
OFFICIAL_CHANNELS_PHRASE = "through official support channels"
CREDENTIAL_WARNING_EN = "Please do not share your PIN or OTP with anyone."
CREDENTIAL_WARNING_BN = "অনুগ্রহ করে কারো সাথে আপনার পিন বা ওটিপি শেয়ার করবেন না।"


def is_bangla_text(text: str) -> bool:
    return bool(re.search(r"[\u0980-\u09FF]", text))


def has_credential_warning(text: str) -> bool:
    lower = text.lower()
    if "পিন" in text and "শেয়ার করবেন না" in text:
        return True
    if any(p in lower for p in ("do not share", "don't share", "never share", "never ask")):
        return any(w in lower for w in ("pin", "otp", "password"))
    return False


def contains_credential_request(text: str) -> bool:
    for match in CREDENTIAL_REQUEST_PATTERN.finditer(text):
        start = match.start()
        window = text[max(0, start - 20) : start].lower()
        if any(p in window for p in ("do not ", "don't ", "never ", "not ")):
            continue
        return True
    return False


def apply_safety_guardrails(customer_reply: str, recommended_next_action: str, language: str | None) -> tuple[str, str]:
    reply = customer_reply.strip()
    action = recommended_next_action.strip()

    if contains_credential_request(reply):
        reply = CREDENTIAL_REQUEST_PATTERN.sub(CREDENTIAL_WARNING_EN, reply, count=1)

    for pattern in UNSAFE_REFUND_PATTERNS:
        reply = pattern.sub(
            "Our team will review the case and any eligible amount will be returned through official channels.",
            reply,
        )

    for pattern in SUSPICIOUS_THIRD_PARTY_PATTERNS:
        reply = pattern.sub(
            f"Our team will follow up with you {OFFICIAL_CHANNELS_PHRASE}.",
            reply,
        )

    if not has_credential_warning(reply):
        warning = CREDENTIAL_WARNING_BN if language == "bn" or is_bangla_text(reply) else CREDENTIAL_WARNING_EN
        reply = f"{reply.rstrip('.')}. {warning}"

    if SAFE_REFUND_PHRASE not in reply.lower() and re.search(
        r"\brefund\b|\breversal\b", reply, re.IGNORECASE
    ) and "eligible amount" not in reply.lower():
        reply = f"{reply.rstrip('.')}. Our team will review the case and {SAFE_REFUND_PHRASE}."

    for pattern in UNSAFE_REFUND_PATTERNS:
        action = pattern.sub("Initiate the official review workflow per policy.", action)

    for pattern in SUSPICIOUS_THIRD_PARTY_PATTERNS:
        action = pattern.sub("Direct the customer to official support channels only.", action)

    return reply, action
