from __future__ import annotations

import re

BANGLA_PIN = "\u09aa\u09bf\u09a8"
BANGLA_OTP = "\u0993\u099f\u09bf\u09aa\u09bf"
BANGLA_SHARE = "\u09b6\u09c7\u09af\u09bc\u09be\u09b0"
BANGLA_NOT = "\u09a8\u09be"

UNSAFE_REFUND_PATTERNS = [
    re.compile(p, re.IGNORECASE)
    for p in [
        r"\bwe will refund\b",
        r"\bwe have refunded\b",
        r"\brefund (?:has been|is) (?:processed|approved|completed)\b",
        r"\bwe will reverse\b",
        r"\bwe guarantee\b.{0,40}\b(?:refund|reversal|unblock|recovery)\b",
        r"\bamount (?:has been|will be) (?:returned|credited) immediately\b",
        r"\baccount (?:has been|will be) unblocked\b",
        r"\brefund kore dibo\b",
        r"\btaka ferot diye dibo\b",
        r"\bimmediate reversal\b",
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
    r"\b(?:(?:share|provide|send|enter|give|confirm|tell us|din|den|diye den|pathan|bolun)\b.{0,48}\b(?:pin|otp|otipi|password|pass|card number)|(?:pin|otp|otipi|password|pass|card number)\b.{0,48}\b(?:din|den|diye den|pathan|bolun|share|send|provide))\b",
    re.IGNORECASE,
)
BANGLA_CREDENTIAL_REQUEST_PATTERN = re.compile(
    r"(?:(?:দিন|দেন|বলুন|শেয়ার|শেয়ার|পাঠান).{0,48}(?:পিন|ওটিপি|পাসওয়ার্ড|পাসওয়ার্ড)|(?:পিন|ওটিপি|পাসওয়ার্ড|পাসওয়ার্ড).{0,48}(?:দিন|দেন|বলুন|শেয়ার|শেয়ার|পাঠান))"
)

SAFE_REFUND_PHRASE = "any eligible amount will be returned through official channels"
OFFICIAL_CHANNELS_PHRASE = "through official support channels"
CREDENTIAL_WARNING_EN = "Please do not share your PIN or OTP with anyone."
CREDENTIAL_WARNING_BN = (
    "\u0985\u09a8\u09c1\u0997\u09cd\u09b0\u09b9 \u0995\u09b0\u09c7 "
    "\u0995\u09be\u09b0\u09cb \u09b8\u09be\u09a5\u09c7 \u0986\u09aa\u09a8\u09be\u09b0 "
    "\u09aa\u09bf\u09a8 \u09ac\u09be \u0993\u099f\u09bf\u09aa\u09bf "
    "\u09b6\u09c7\u09af\u09bc\u09be\u09b0 \u0995\u09b0\u09ac\u09c7\u09a8 \u09a8\u09be\u0964"
)


def is_bangla_text(text: str) -> bool:
    return bool(re.search(r"[\u0980-\u09FF]", text or ""))


def has_credential_warning(text: str) -> bool:
    lower = text.lower()
    if BANGLA_PIN in text and BANGLA_SHARE in text and BANGLA_NOT in text:
        return True
    if any(p in lower for p in ("do not share", "don't share", "never share", "never ask")):
        return any(w in lower for w in ("pin", "otp", "password"))
    return False


def contains_credential_request(text: str) -> bool:
    if BANGLA_CREDENTIAL_REQUEST_PATTERN.search(text or ""):
        return True
    for match in CREDENTIAL_REQUEST_PATTERN.finditer(text or ""):
        start = match.start()
        window = text[max(0, start - 28) : start].lower()
        if any(p in window for p in ("do not ", "don't ", "never ", "not ")):
            continue
        return True
    return False


def apply_safety_guardrails(customer_reply: str, recommended_next_action: str, language: str | None) -> tuple[str, str]:
    reply = (customer_reply or "").strip()
    action = (recommended_next_action or "").strip()

    if BANGLA_CREDENTIAL_REQUEST_PATTERN.search(reply):
        reply = BANGLA_CREDENTIAL_REQUEST_PATTERN.sub(CREDENTIAL_WARNING_BN, reply, count=1)
    elif contains_credential_request(reply):
        reply = CREDENTIAL_REQUEST_PATTERN.sub(CREDENTIAL_WARNING_EN, reply, count=1)

    for pattern in UNSAFE_REFUND_PATTERNS:
        reply = pattern.sub(
            "Our team will review the case and any eligible amount will be returned through official channels.",
            reply,
        )
        action = pattern.sub("Initiate the official review workflow per policy.", action)

    for pattern in SUSPICIOUS_THIRD_PARTY_PATTERNS:
        reply = pattern.sub(f"Our team will follow up with you {OFFICIAL_CHANNELS_PHRASE}.", reply)
        action = pattern.sub("Direct the customer to official support channels only.", action)

    warning = CREDENTIAL_WARNING_BN if language == "bn" or is_bangla_text(reply) else CREDENTIAL_WARNING_EN
    if not has_credential_warning(reply):
        reply = f"{reply.rstrip('.')}. {warning}"

    refund_language = re.search(r"\brefund\b|\breversal\b|\breturned\b|\bcredited\b", reply, re.IGNORECASE)
    if refund_language and SAFE_REFUND_PHRASE not in reply.lower():
        reply = f"{reply.rstrip('.')}. Our team will review the case and {SAFE_REFUND_PHRASE}."

    return reply, action
