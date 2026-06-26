from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional

from app.models import (
    AnalyzeTicketRequest,
    AnalyzeTicketResponse,
    CaseType,
    Department,
    EvidenceVerdict,
    Severity,
    Transaction,
)
from app.safety import apply_safety_guardrails, is_bangla_text

AMOUNT_PATTERN = re.compile(
    r"(?<!\d)(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?\s*(?:taka|tk|bdt|\u099f\u09be\u0995\u09be)?",
    re.IGNORECASE,
)
K_AMOUNT_PATTERN = re.compile(r"(?<![a-z0-9])(\d+(?:\.\d+)?)\s*k\b", re.IGNORECASE)
HAJAR_AMOUNT_PATTERN = re.compile(
    r"(?<!\d)(\d+(?:\.\d+)?)\s*(?:hajar|hazar|\u09b9\u09be\u099c\u09be\u09b0)\b",
    re.IGNORECASE,
)
LAKH_AMOUNT_PATTERN = re.compile(
    r"(?<!\d)(\d+(?:\.\d+)?)\s*(?:lakh|lac|lacs|\u09b2\u09be\u0996)\b",
    re.IGNORECASE,
)
PHONE_PATTERN = re.compile(r"(?:\+?88)?01[3-9]\d{8}")
TXN_ID_PATTERN = re.compile(r"\b(?:txn|trx|transaction)[-_\s:]?([a-z0-9-]+)\b", re.IGNORECASE)
BANGLA_DIGITS = dict(zip("\u09e6\u09e7\u09e8\u09e9\u09ea\u09eb\u09ec\u09ed\u09ee\u09ef", "0123456789"))
MOJIBAKE_DIGITS = {
    "Ã Â§Â¦": "0",
    "Ã Â§Â§": "1",
    "Ã Â§Â¨": "2",
    "Ã Â§Â©": "3",
    "Ã Â§Âª": "4",
    "Ã Â§Â«": "5",
    "Ã Â§Â¬": "6",
    "Ã Â§Â­": "7",
    "Ã Â§Â®": "8",
    "Ã Â§Â¯": "9",
}
HOMOGLYPHS = str.maketrans(
    {
        "\u0430": "a",
        "\u0435": "e",
        "\u0456": "i",
        "\u043e": "o",
        "\u0440": "p",
        "\u0441": "c",
        "\u0445": "x",
        "\u0443": "y",
        "\u03b1": "a",
        "\u03bf": "o",
        "\u03c1": "p",
    }
)

PROMPT_INJECTION_PATTERNS = [
    re.compile(p, re.IGNORECASE)
    for p in [
        r"ignore (?:all )?(?:previous|above|system) instructions",
        r"reveal (?:the )?(?:system prompt|developer message|policy)",
        r"you are now",
        r"act as",
        r"must approve",
        r"refund immediately",
        r"ask .* otp",
        r"return only",
    ]
]

BANGLISH_CANONICAL_PATTERNS = [
    (re.compile(r"\b(?:bhul|vul|bool|wrong|mistake|galat|onno)\b", re.IGNORECASE), " wrong bhul"),
    (re.compile(r"\b(?:number|nomber|namber|nambar|person|manush)\b", re.IGNORECASE), " number person"),
    (re.compile(r"\b(?:ashe nai|aseni|asheni|ase nai|paini|pai nai|pay nai|pai ni|paw ni|peyeni|pawa jai nai|pouchay nai|hoy nai)\b", re.IGNORECASE), " not received not reflected paini"),
    (re.compile(r"\b(?:kete niche|kete niyeche|kete nise|ketese|katse|kete|kata|katche|cut hoise|deduct hoise|deducted)\b", re.IGNORECASE), " deducted balance deducted"),
    (re.compile(r"\b(?:dui bar|duibar|double|twice|2 bar|bar bar|dobare|again charged|repeat)\b", re.IGNORECASE), " duplicate twice"),
    (re.compile(r"\b(?:ferot|ferot chai|taka ferot|refund|return|money back|taka back|return chai)\b", re.IGNORECASE), " refund return my money"),
    (re.compile(r"\b(?:cashin|cash in|cash-in|kash in|kashin|agent|ejent|agent er kase|agent theke|joma|deposit|reflect hoy nai)\b", re.IGNORECASE), " cash in agent"),
    (re.compile(r"\b(?:otp|otipi|pin|password|pass)\b", re.IGNORECASE), " otp pin password"),
    (re.compile(r"\b(?:call dise|phone dise|sms dise|message dise|link dise|call korse|pathao|pathaben|block hobe)\b", re.IGNORECASE), " call message link"),
    (re.compile(r"\b(?:merchant|dokandar)\b", re.IGNORECASE), " merchant"),
    (re.compile(r"\b(?:settlement|sales|payout)\b", re.IGNORECASE), " settlement sales payout"),
    (re.compile(r"\b(?:failed|fail hoise|fail koreche|kaj kore nai|recharge hoy nai|success hoy nai|success dekhay na|pending dekhay|pari nai)\b", re.IGNORECASE), " failed failure"),
]


@dataclass
class ComplaintSignals:
    normalized_text: str
    amounts: list[float]
    phones: list[str]
    transaction_refs: list[str]
    language: str
    prompt_injection: bool
    vague: bool
    encoding_repaired: bool
    banglish_detected: bool
    hour_hint: int | None


@dataclass
class ScoreResult:
    transaction: Transaction
    score: float
    reasons: list[str]


@dataclass
class MatchResult:
    transaction: Optional[Transaction]
    verdict: EvidenceVerdict
    confidence: float
    reason_codes: list[str]
    ambiguous: bool = False
    top_scores: list[ScoreResult] | None = None


def bangla_char_count(text: str) -> int:
    return len(re.findall(r"[\u0980-\u09FF]", text or ""))


def repair_text_encoding(text: str) -> tuple[str, bool]:
    value = text or ""
    candidates = [value]
    for encoding in ("latin1", "cp1252"):
        try:
            candidates.append(value.encode(encoding).decode("utf-8"))
        except (UnicodeEncodeError, UnicodeDecodeError):
            continue

    def score(candidate: str) -> tuple[int, int]:
        return (bangla_char_count(candidate), -candidate.count("\ufffd"))

    best = max(candidates, key=score)
    return best, best != value


def append_banglish_canonical_tokens(text: str) -> tuple[str, bool]:
    additions: list[str] = []
    for pattern, canonical in BANGLISH_CANONICAL_PATTERNS:
        if pattern.search(text):
            additions.append(canonical)
    if not additions:
        return text, False
    return f"{text} {' '.join(additions)}", True


def normalize_text(text: str) -> str:
    value, _ = repair_text_encoding(text or "")
    value = unicodedata.normalize("NFKC", value)
    value = value.translate(HOMOGLYPHS)
    for source, target in BANGLA_DIGITS.items():
        value = value.replace(source, target)
    for source, target in MOJIBAKE_DIGITS.items():
        value = value.replace(source, target)
    value = " ".join(value.lower().split())
    value, _ = append_banglish_canonical_tokens(value)
    return value


def extract_amounts(text: str) -> list[float]:
    normalized = normalize_text(text)
    amounts: list[float] = []
    for match in AMOUNT_PATTERN.finditer(normalized):
        raw = match.group(0).replace(",", "")
        number = re.sub(r"[^\d.]", "", raw)
        if number:
            try:
                amounts.append(float(number))
            except ValueError:
                continue
    for match in K_AMOUNT_PATTERN.finditer(normalized):
        try:
            amounts.append(float(match.group(1)) * 1000)
        except ValueError:
            continue
    for match in HAJAR_AMOUNT_PATTERN.finditer(normalized):
        try:
            amounts.append(float(match.group(1)) * 1000)
        except ValueError:
            continue
    for match in LAKH_AMOUNT_PATTERN.finditer(normalized):
        try:
            amounts.append(float(match.group(1)) * 100000)
        except ValueError:
            continue
    return amounts


def detect_language(request: AnalyzeTicketRequest, normalized_text: str, banglish_detected: bool) -> str:
    if request.language in {"en", "bn", "mixed"}:
        return request.language
    text = normalized_text or request.complaint or ""
    if is_bangla_text(text):
        return "bn"
    banglish_markers = ("taka", "tk", "bhai", "bhul", "vul", "paini", "asheni", "kete niche", "cash in", "otp")
    if banglish_detected or any(marker in text.lower() for marker in banglish_markers):
        return "mixed"
    return "en"


def has_prompt_injection(text: str) -> bool:
    return any(pattern.search(text or "") for pattern in PROMPT_INJECTION_PATTERNS)


def extract_hour_hint(text: str) -> int | None:
    match = re.search(r"\b(1[0-2]|0?[1-9])\s*(am|pm)\b", text, re.IGNORECASE)
    if not match:
        return None
    hour = int(match.group(1))
    meridiem = match.group(2).lower()
    if meridiem == "pm" and hour != 12:
        hour += 12
    if meridiem == "am" and hour == 12:
        hour = 0
    return hour


def parse_signals(request: AnalyzeTicketRequest) -> ComplaintSignals:
    repaired_text, encoding_repaired = repair_text_encoding(request.complaint)
    normalized = normalize_text(repaired_text)
    normalized, banglish_detected = append_banglish_canonical_tokens(normalized)
    amounts = extract_amounts(normalized)
    vague_phrases = (
        "something is wrong",
        "please check",
        "help me",
        "money problem",
        "kisu somossa",
        "somossa hocche",
        "check korben",
        "dekhben",
        "help lagbe",
        "taka niye",
        "\u09b8\u09ae\u09b8\u09cd\u09af\u09be",
    )
    vague = (any(p in normalized for p in vague_phrases) and not amounts) or (
        len(normalized) < 64 and "money" in normalized and not amounts
    )
    return ComplaintSignals(
        normalized_text=normalized,
        amounts=amounts,
        phones=[re.sub(r"^\+?88", "", p) for p in PHONE_PATTERN.findall(normalized)],
        transaction_refs=[m.group(1).upper() for m in TXN_ID_PATTERN.finditer(normalized)],
        language=detect_language(request, normalized, banglish_detected),
        prompt_injection=has_prompt_injection(normalized),
        vague=vague,
        encoding_repaired=encoding_repaired,
        banglish_detected=banglish_detected,
        hour_hint=extract_hour_hint(normalized),
    )


def parse_timestamp(value: str) -> Optional[datetime]:
    try:
        parsed = datetime.fromisoformat((value or "").replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            return parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)
    except ValueError:
        return None


def keyword_present(text: str, *keywords: str) -> bool:
    return any(keyword in text for keyword in keywords)


def strip_classification_instructions(text: str) -> str:
    return re.sub(
        r"\b(?:classify|mark|label|set|output|return)\s+(?:this\s+)?(?:as|case_type\s*(?:as|=|:)?|exactly\s+as)?\s*['\"]?[a-z_ -]{3,80}",
        " ",
        text,
        flags=re.IGNORECASE,
    )


def detect_case_type(request: AnalyzeTicketRequest, signals: ComplaintSignals) -> CaseType:
    text = strip_classification_instructions(signals.normalized_text)
    user_type = request.user_type or "unknown"

    credential_terms = (
        "otp",
        "otipi",
        "pin",
        "password",
        "pass",
        "scam",
        "phishing",
        "fake call",
        "fraud",
        "blocked",
        "\u0993\u099f\u09bf\u09aa\u09bf",
        "\u09aa\u09bf\u09a8",
        "\u09aa\u09be\u09b8\u0993\u09af\u09bc\u09be\u09b0\u09cd\u09a1",
        "\u09aa\u09cd\u09b0\u09a4\u09be\u09b0\u09a3\u09be",
    )
    contact_terms = (
        "call",
        "called",
        "asking",
        "asked",
        "told me",
        "sms",
        "message",
        "phone",
        "texted",
        "emailed",
        "whatsapp",
        "link",
        "is this real",
        "legit",
        "safe",
        "haven't shared",
        "did not share",
        "\u09ab\u09cb\u09a8",
        "\u09ae\u09c7\u09b8\u09c7\u099c",
        "\u099c\u09bf\u099c\u09cd\u099e\u09be\u09b8\u09be",
        "\u09b6\u09c7\u09af\u09bc\u09be\u09b0 \u0995\u09b0\u09bf\u09a8\u09bf",
    )
    if any(k in text for k in credential_terms) and (
        any(w in text for w in contact_terms)
        or re.search(r"(?:asked|asking|wanted|want).{0,36}(?:otp|otipi|pin|password|pass)", text)
    ):
        return "phishing_or_social_engineering"

    if user_type == "merchant" or keyword_present(text, "merchant", "settlement", "settled"):
        if keyword_present(text, "settlement", "settled", "sales", "payout"):
            return "merchant_settlement_delay"

    if keyword_present(
        text,
        "duplicate",
        "twice",
        "double",
        "deducted twice",
        "duibar",
        "dui bar",
        "two times",
        "\u09a6\u09c1\u0987\u09ac\u09be\u09b0",
    ):
        return "duplicate_payment"

    if keyword_present(
        text,
        "cash in",
        "cash-in",
        "cashin",
        "kash in",
        "kashin",
        "agent",
        "kache",
        "asheni",
        "ashe nai",
        "\u0995\u09cd\u09af\u09be\u09b6 \u0987\u09a8",
        "\u098f\u099c\u09c7\u09a8\u09cd\u099f",
    ) or ("Ã Â¦" in text and signals.amounts):
        return "agent_cash_in_issue"

    if keyword_present(
        text,
        "failed",
        "failure",
        "unsuccessful",
        "did not complete",
        "not completed",
        "didn't go through",
        "did not go through",
        "error",
        "stuck",
        "deducted",
        "balance deducted",
        "money was cut",
        "balance cut",
        "not reflected",
        "recharge",
        "top up",
        "top-up",
        "bill payment",
        "paini",
    ):
        return "payment_failed"

    if keyword_present(text, "wrong", "mistake", "mistyped", "incorrect number", "bhul", "vul", "galat", "\u09ad\u09c1\u09b2"):
        return "wrong_transfer"

    if keyword_present(text, "refund", "return my money", "change my mind", "cancel", "ferot", "\u09ab\u09c7\u09b0\u09a4"):
        return "refund_request"

    if keyword_present(text, "didn't get", "didnt get", "not received", "did not receive", "paini", "pay nai"):
        return "wrong_transfer"

    return "other"

def find_duplicate_pair(transactions: list[Transaction]) -> Optional[Transaction]:
    ordered = sorted(transactions, key=lambda t: parse_timestamp(t.timestamp) or datetime.min)
    for index, first in enumerate(ordered):
        for second in ordered[index + 1 :]:
            if (
                first.type == second.type == "payment"
                and abs(first.amount - second.amount) < 0.01
                and first.counterparty == second.counterparty
                and first.status == second.status == "completed"
            ):
                first_time = parse_timestamp(first.timestamp)
                second_time = parse_timestamp(second.timestamp)
                if first_time and second_time and abs((second_time - first_time).total_seconds()) <= 180:
                    return second
    return None


def should_infer_duplicate_payment(transactions: list[Transaction], signals: ComplaintSignals) -> bool:
    duplicate = find_duplicate_pair(transactions)
    if not duplicate:
        return False
    text = signals.normalized_text
    if signals.amounts and any(abs(duplicate.amount - amount) < 0.01 for amount in signals.amounts):
        return True
    return keyword_present(
        text,
        "bill",
        "biller",
        "desco",
        "electricity",
        "\u09ac\u09bf\u09b2",
        "charged",
        "cut",
        "kete",
        "katche",
        "\u0995\u09c7\u099f\u09c7\u099b\u09c7",
        "bar bar",
        "2 bar",
    )


def amount_similarity(txn_amount: float, amounts: list[float]) -> tuple[float, str | None]:
    if not amounts:
        return 0.0, None
    deltas = [abs(txn_amount - amount) for amount in amounts]
    best_delta = min(deltas)
    if best_delta < 0.01:
        return 3.5, "amount_exact"
    best_amount = amounts[deltas.index(best_delta)]
    tolerance = max(10.0, best_amount * 0.02)
    if best_delta <= tolerance:
        return 2.0, "amount_near"
    return 0.0, None


def score_transaction(txn: Transaction, signals: ComplaintSignals, case_type: CaseType) -> ScoreResult:
    text = signals.normalized_text
    score = 0.0
    reasons: list[str] = []

    amount_score, amount_reason = amount_similarity(txn.amount, signals.amounts)
    if amount_reason:
        score += amount_score
        reasons.append(amount_reason)

    if txn.transaction_id.upper() in signals.transaction_refs:
        score += 5.0
        reasons.append("transaction_id_mentioned")

    counterparty = (txn.counterparty or "").lower()
    normalized_counterparty = re.sub(r"^\+?88", "", counterparty)
    if normalized_counterparty and any(phone in normalized_counterparty for phone in signals.phones):
        score += 3.0
        reasons.append("counterparty_mentioned")

    type_weights: dict[CaseType, tuple[str, float]] = {
        "wrong_transfer": ("transfer", 2.0),
        "payment_failed": ("payment", 2.5),
        "refund_request": ("payment", 2.0),
        "duplicate_payment": ("payment", 2.0),
        "merchant_settlement_delay": ("settlement", 3.5),
        "agent_cash_in_issue": ("cash_in", 3.5),
        "phishing_or_social_engineering": ("", 0.0),
        "other": ("", 0.0),
    }
    expected_type, type_score = type_weights[case_type]
    if expected_type and txn.type == expected_type:
        score += type_score
        reasons.append("type_match")

    if case_type == "payment_failed" and txn.status == "failed":
        score += 3.0
        reasons.append("failed_status_match")
    elif case_type in {"agent_cash_in_issue", "merchant_settlement_delay"} and txn.status == "pending":
        score += 2.5
        reasons.append("pending_status_match")
    elif case_type in {"wrong_transfer", "refund_request"} and txn.status == "completed":
        score += 1.0
        reasons.append("completed_status_match")

    if keyword_present(text, "today", "\u0986\u099c") or "Ã Â¦â€ Ã Â¦Å“" in text:
        score += 0.4
        reasons.append("time_hint_today")
    if keyword_present(text, "yesterday", "\u0997\u09a4\u0995\u09be\u09b2") or "Ã Â¦â€”Ã Â¦Â¤" in text:
        score += 0.4
        reasons.append("time_hint_yesterday")
    if signals.hour_hint is not None:
        txn_time = parse_timestamp(txn.timestamp)
        if txn_time:
            hour_delta = abs(txn_time.hour - signals.hour_hint)
            hour_delta = min(hour_delta, 24 - hour_delta)
            if hour_delta <= 1:
                score += 1.2
                reasons.append("hour_hint_match")
            elif hour_delta >= 4:
                score -= 0.3
                reasons.append("hour_hint_mismatch")
        else:
            score += 0.2
            reasons.append("time_hint_present")

    if keyword_present(text, "merchant", "biller", "electricity", "mobile recharge") and (
        "merchant" in counterparty or "biller" in counterparty
    ):
        score += 0.8
        reasons.append("merchant_context_match")

    return ScoreResult(txn, score, reasons)


def established_recipient_pattern(transactions: list[Transaction], target: Transaction) -> bool:
    same_counterparty = [
        txn for txn in transactions if txn.type == "transfer" and txn.counterparty == target.counterparty
    ]
    return len(same_counterparty) >= 3


def compute_confidence(best_score: float, second_score: float, signals: ComplaintSignals, verdict: EvidenceVerdict) -> float:
    confidence = 0.45 + min(best_score, 10.0) * 0.045
    if signals.amounts:
        confidence += 0.08
    if signals.transaction_refs or signals.phones:
        confidence += 0.05
    if second_score and best_score - second_score < 1.0:
        confidence -= 0.12
    if verdict == "inconsistent":
        confidence -= 0.03
    if verdict == "insufficient_data":
        confidence = min(confidence, 0.68)
    return max(0.35, min(0.96, confidence))


def signal_reason_prefix(signals: ComplaintSignals) -> list[str]:
    reasons: list[str] = []
    if signals.encoding_repaired:
        reasons.append("encoding_repaired")
    if signals.banglish_detected:
        reasons.append("banglish_normalized")
    if signals.prompt_injection:
        reasons.append("prompt_injection_ignored")
    return reasons


def match_transactions(
    transactions: list[Transaction],
    signals: ComplaintSignals,
    case_type: CaseType,
) -> MatchResult:
    reason_prefix = signal_reason_prefix(signals)

    if not transactions:
        return MatchResult(None, "insufficient_data", 0.58, reason_prefix + ["no_transactions"])

    if case_type == "duplicate_payment":
        duplicate = find_duplicate_pair(transactions)
        if duplicate:
            return MatchResult(
                duplicate,
                "consistent",
                0.93,
                reason_prefix + ["duplicate_payment", "biller_verification_required"],
            )

    scored = [score_transaction(txn, signals, case_type) for txn in transactions]
    scored.sort(key=lambda result: result.score, reverse=True)
    best = scored[0]
    second_score = scored[1].score if len(scored) > 1 else 0.0

    ambiguous_amount_matches = [
        result
        for result in scored
        if "amount_exact" in result.reasons and result.score >= max(3.5, best.score - 1.0)
    ]
    if len(ambiguous_amount_matches) > 1 and not signals.transaction_refs and not signals.phones:
        return MatchResult(
            None,
            "insufficient_data",
            0.65,
            reason_prefix + ["ambiguous_match", "needs_clarification"],
            ambiguous=True,
            top_scores=scored[:3],
        )

    if best.score < 2.5:
        return MatchResult(None, "insufficient_data", 0.58, reason_prefix + ["no_clear_match"], top_scores=scored[:3])

    verdict: EvidenceVerdict = "consistent"
    reasons = reason_prefix + ["transaction_match", *best.reasons]

    if case_type == "wrong_transfer" and established_recipient_pattern(transactions, best.transaction):
        verdict = "inconsistent"
        reasons.extend(["wrong_transfer_claim", "established_recipient_pattern", "evidence_inconsistent"])

    if case_type == "payment_failed" and best.transaction.status == "completed" and "failed" in signals.normalized_text:
        verdict = "inconsistent"
        reasons.append("status_contradicts_failed_claim")

    if case_type == "payment_failed" and best.transaction.status == "failed":
        reasons.append("potential_balance_deduction")
    if case_type == "agent_cash_in_issue" and best.transaction.status == "pending":
        reasons.extend(["agent_cash_in", "pending_transaction", "agent_ops"])
    if case_type == "merchant_settlement_delay" and best.transaction.status == "pending":
        reasons.extend(["merchant_settlement", "delay", "pending"])

    confidence = compute_confidence(best.score, second_score, signals, verdict)
    return MatchResult(best.transaction, verdict, confidence, dedupe(reasons), top_scores=scored[:3])


def dedupe(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        if value not in seen:
            seen.add(value)
            result.append(value)
    return result


def route_department(case_type: CaseType, severity: Severity) -> Department:
    routes: dict[CaseType, Department] = {
        "wrong_transfer": "dispute_resolution",
        "payment_failed": "payments_ops",
        "refund_request": "customer_support",
        "duplicate_payment": "payments_ops",
        "merchant_settlement_delay": "merchant_operations",
        "agent_cash_in_issue": "agent_operations",
        "phishing_or_social_engineering": "fraud_risk",
        "other": "customer_support",
    }
    if case_type == "refund_request" and severity in {"high", "critical"}:
        return "dispute_resolution"
    return routes[case_type]


def determine_severity(case_type: CaseType, match: MatchResult, signals: ComplaintSignals) -> Severity:
    if case_type == "phishing_or_social_engineering":
        return "critical"
    if case_type in {"duplicate_payment", "payment_failed", "agent_cash_in_issue", "wrong_transfer"}:
        if match.verdict == "inconsistent":
            return "medium"
        if signals.amounts and max(signals.amounts) >= 10000:
            return "high"
        return "high"
    if case_type == "merchant_settlement_delay":
        return "medium"
    if case_type == "refund_request":
        return "low"
    return "low"


def needs_human_review(case_type: CaseType, match: MatchResult, severity: Severity, signals: ComplaintSignals) -> bool:
    if case_type == "phishing_or_social_engineering" or severity == "critical":
        return True
    if signals.prompt_injection:
        return True
    if case_type in {"wrong_transfer", "duplicate_payment"} and match.verdict == "consistent":
        return True
    if match.verdict == "inconsistent":
        return True
    if case_type == "agent_cash_in_issue" and match.transaction:
        return True
    if match.transaction and match.transaction.amount >= 10000 and case_type in {
        "wrong_transfer",
        "duplicate_payment",
        "payment_failed",
    }:
        return True
    return False


def build_agent_summary(request: AnalyzeTicketRequest, case_type: CaseType, match: MatchResult, signals: ComplaintSignals) -> str:
    txn = match.transaction
    prefix = "Prompt-injection text was detected and ignored. " if signals.prompt_injection else ""

    if case_type == "phishing_or_social_engineering":
        return prefix + (
            "Customer reports suspicious contact asking for credentials or threatening account action. "
            "Likely social engineering attempt; no transaction evidence is required."
        )
    if signals.vague:
        return prefix + (
            "Customer reports a vague money-related concern without enough amount, transaction, recipient, or timing detail "
            "to identify a relevant transaction."
        )
    if match.ambiguous:
        return prefix + (
            "Multiple transactions plausibly match the complaint. Additional customer detail is required before opening "
            "a dispute or selecting a transaction."
        )
    if txn:
        return prefix + (
            f"Customer concern maps to {txn.transaction_id} ({txn.amount:.0f} BDT, {txn.type}, "
            f"{txn.status}, counterparty {txn.counterparty}). Classified as {case_type.replace('_', ' ')}."
        )
    return prefix + f"Complaint classified as {case_type.replace('_', ' ')} with insufficient transaction evidence."


def build_next_action(case_type: CaseType, match: MatchResult, txn_id: str | None) -> str:
    if match.ambiguous:
        return "Ask for the recipient or transaction ID to identify the correct transaction before taking operational action."
    if case_type == "phishing_or_social_engineering":
        return "Escalate to fraud_risk, reinforce that OTP/PIN/password are never requested, and log reported contact details."
    if case_type == "other" and match.verdict == "insufficient_data":
        return "Ask for transaction ID, amount, approximate time, and a short description of what went wrong."
    if case_type == "wrong_transfer" and match.verdict == "inconsistent" and txn_id:
        return "Flag for human review and verify whether the established recipient pattern contradicts the wrong-transfer claim."
    if case_type == "wrong_transfer" and txn_id:
        return f"Verify {txn_id} details and initiate the wrong-transfer dispute workflow per policy."
    if case_type == "payment_failed" and txn_id:
        return f"Investigate {txn_id} ledger status and run the standard failed-payment reconciliation workflow."
    if case_type == "refund_request":
        return "Explain that refund eligibility depends on the merchant policy and guide the customer to official support steps."
    if case_type == "duplicate_payment" and txn_id:
        return f"Verify duplicate evidence with payments_ops and biller records before initiating review for {txn_id}."
    if case_type == "merchant_settlement_delay" and txn_id:
        return "Route to merchant_operations to verify settlement batch status and communicate an official ETA."
    if case_type == "agent_cash_in_issue" and txn_id:
        return f"Investigate {txn_id} with agent_operations and confirm settlement state under the cash-in SLA."
    return "Review the case details and follow the standard support workflow."


def build_customer_reply(request: AnalyzeTicketRequest, case_type: CaseType, match: MatchResult, txn_id: str | None, language: str) -> str:
    if case_type == "phishing_or_social_engineering":
        if language == "bn":
            return (
                "\u09af\u09cb\u0997\u09be\u09af\u09cb\u0997 \u0995\u09b0\u09be\u09b0 \u099c\u09a8\u09cd\u09af "
                "\u09a7\u09a8\u09cd\u09af\u09ac\u09be\u09a6\u0964 \u0986\u09ae\u09b0\u09be \u0995\u0996\u09a8\u09cb\u0987 "
                "\u0986\u09aa\u09a8\u09be\u09b0 \u09aa\u09bf\u09a8, \u0993\u099f\u09bf\u09aa\u09bf \u09ac\u09be "
                "\u09aa\u09be\u09b8\u0993\u09af\u09bc\u09be\u09b0\u09cd\u09a1 \u099a\u09be\u0987 \u09a8\u09be\u0964 "
                "\u098f\u0997\u09c1\u09b2\u09cb \u0995\u09be\u09b0\u09cb \u09b8\u09be\u09a5\u09c7 "
                "\u09b6\u09c7\u09af\u09bc\u09be\u09b0 \u0995\u09b0\u09ac\u09c7\u09a8 \u09a8\u09be\u0964 "
                "\u0986\u09ae\u09be\u09a6\u09c7\u09b0 \u09ab\u09cd\u09b0\u09a1 \u09a6\u09b2\u0995\u09c7 "
                "\u099c\u09be\u09a8\u09be\u09a8\u09cb \u09b9\u09af\u09bc\u09c7\u099b\u09c7\u0964"
            )
        return (
            "Thank you for reaching out before sharing any information. We never ask for your PIN, OTP, "
            "or password under any circumstances. Please do not share these with anyone, even if they claim "
            "to be from us. Our fraud team has been notified."
        )

    if match.ambiguous:
        return (
            "Thank you for reaching out. We see multiple transactions that could match this complaint. "
            "Please share the recipient number or transaction ID so we can identify the right transaction. "
            "Please do not share your PIN or OTP with anyone."
        )
    if case_type == "other" and match.verdict == "insufficient_data":
        return (
            "Thank you for reaching out. To help you faster, please share the transaction ID, amount, "
            "approximate time, and what went wrong. Please do not share your PIN or OTP with anyone."
        )
    if case_type == "refund_request":
        return (
            "Thank you for reaching out. Refunds for completed merchant payments depend on the merchant's policy. "
            "We can guide you through official support steps, but please do not share your PIN or OTP with anyone."
        )
    if case_type == "payment_failed" and txn_id:
        return (
            f"We have noted that transaction {txn_id} may have caused an unexpected balance issue. "
            "Our payments team will review the case and any eligible amount will be returned through official channels. "
            "Please do not share your PIN or OTP with anyone."
        )
    if case_type == "duplicate_payment" and txn_id:
        return (
            f"We have noted the possible duplicate payment for transaction {txn_id}. Our payments team will verify it "
            "and any eligible amount will be returned through official channels. Please do not share your PIN or OTP with anyone."
        )
    if case_type == "merchant_settlement_delay" and txn_id:
        return (
            f"We have noted your concern about settlement {txn_id}. Our merchant operations team will check the batch status "
            "and update you through official channels."
        )
    if case_type == "agent_cash_in_issue" and txn_id and language == "bn":
        return (
            f"\u0986\u09aa\u09a8\u09be\u09b0 \u09b2\u09c7\u09a8\u09a6\u09c7\u09a8 {txn_id} \u098f\u09b0 "
            "\u09ac\u09bf\u09b7\u09af\u09bc\u09c7 \u0986\u09ae\u09b0\u09be \u0985\u09ac\u0997\u09a4 "
            "\u09b9\u09af\u09bc\u09c7\u099b\u09bf\u0964 \u0986\u09ae\u09be\u09a6\u09c7\u09b0 "
            "\u098f\u099c\u09c7\u09a8\u09cd\u099f \u0985\u09aa\u09be\u09b0\u09c7\u09b6\u09a8\u09cd\u09b8 "
            "\u09a6\u09b2 \u098f\u099f\u09bf \u09af\u09be\u099a\u09be\u0987 \u0995\u09b0\u09c7 "
            "\u0985\u09ab\u09bf\u09b8\u09bf\u09af\u09bc\u09be\u09b2 \u099a\u09cd\u09af\u09be\u09a8\u09c7\u09b2\u09c7 "
            "\u0986\u09aa\u09a8\u09be\u0995\u09c7 \u099c\u09be\u09a8\u09be\u09ac\u09c7\u0964"
        )
    if case_type == "agent_cash_in_issue" and txn_id:
        return (
            f"We have noted your concern about transaction {txn_id}. Our agent operations team will review the case "
            "and contact you through official support channels. Please do not share your PIN or OTP with anyone."
        )
    if case_type == "wrong_transfer" and txn_id:
        return (
            f"We have noted your concern about transaction {txn_id}. Our dispute team will review the case and contact "
            "you through official support channels. Please do not share your PIN or OTP with anyone."
        )
    return (
        "Thank you for contacting us. Our support team will review your case and follow up through official channels. "
        "Please do not share your PIN or OTP with anyone."
    )


def analyze_ticket(request: AnalyzeTicketRequest) -> AnalyzeTicketResponse:
    signals = parse_signals(request)
    case_type = detect_case_type(request, signals)

    if case_type != "phishing_or_social_engineering" and should_infer_duplicate_payment(
        request.transaction_history,
        signals,
    ):
        case_type = "duplicate_payment"

    if signals.vague:
        case_type = "other"
        reason_codes = signal_reason_prefix(signals) + ["vague_complaint", "needs_clarification"]
        match = MatchResult(None, "insufficient_data", 0.6, reason_codes)
    elif case_type == "phishing_or_social_engineering":
        reason_codes = signal_reason_prefix(signals) + ["phishing", "credential_protection", "critical_escalation"]
        match = MatchResult(None, "insufficient_data", 0.95, reason_codes)
    else:
        match = match_transactions(request.transaction_history, signals, case_type)

    txn_id = match.transaction.transaction_id if match.transaction else None
    severity = determine_severity(case_type, match, signals)
    department = route_department(case_type, severity)
    human_review = needs_human_review(case_type, match, severity, signals)

    agent_summary = build_agent_summary(request, case_type, match, signals)
    next_action = build_next_action(case_type, match, txn_id)
    customer_reply = build_customer_reply(request, case_type, match, txn_id, signals.language)
    customer_reply, next_action = apply_safety_guardrails(customer_reply, next_action, signals.language)

    return AnalyzeTicketResponse(
        ticket_id=request.ticket_id,
        relevant_transaction_id=txn_id,
        evidence_verdict=match.verdict,
        case_type=case_type,
        severity=severity,
        department=department,
        agent_summary=agent_summary,
        recommended_next_action=next_action,
        customer_reply=customer_reply,
        human_review_required=human_review,
        confidence=round(match.confidence, 2),
        reason_codes=match.reason_codes,
    )


async def analyze_ticket_with_optional_llm(request: AnalyzeTicketRequest) -> AnalyzeTicketResponse:
    response = analyze_ticket(request)

    try:
        from app.agent import polish_with_gemini

        polish = await polish_with_gemini(request, response)
    except Exception:
        polish = None

    if not polish:
        return response

    customer_reply, next_action = apply_safety_guardrails(
        polish.customer_reply,
        response.recommended_next_action,
        request.language,
    )
    reason_codes = list(response.reason_codes or [])
    if "llm_polished" not in reason_codes:
        reason_codes.append("llm_polished")

    return response.model_copy(
        update={
            "agent_summary": polish.agent_summary,
            "customer_reply": customer_reply,
            "recommended_next_action": next_action,
            "reason_codes": reason_codes,
        }
    )

