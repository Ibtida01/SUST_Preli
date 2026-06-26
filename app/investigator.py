from __future__ import annotations

import asyncio
import re
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
from app.robustness import (
    extract_phone_numbers,
    extract_transaction_ids,
    normalize_phone,
    sanitize_complaint_for_analysis,
)
from app.safety import apply_safety_guardrails, is_bangla_text

AMOUNT_PATTERN = re.compile(
    r"(?<!\d)(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?\s*(?:taka|tk|bdt|টাকা)?",
    re.IGNORECASE,
)
K_AMOUNT_PATTERN = re.compile(r"(?<![a-z0-9])(\d+(?:\.\d+)?)\s*k\b", re.IGNORECASE)
HAJAR_AMOUNT_PATTERN = re.compile(
    r"(?<!\d)(\d+(?:\.\d+)?)\s*(?:hajar|hazar|হাজার)\b",
    re.IGNORECASE,
)
LAKH_AMOUNT_PATTERN = re.compile(
    r"(?<!\d)(\d+(?:\.\d+)?)\s*(?:lakh|lac|lacs|লাখ)\b",
    re.IGNORECASE,
)
BANGLA_DIGITS = str.maketrans("০১২৩৪৫৬৭৮৯", "0123456789")


@dataclass
class MatchResult:
    transaction: Optional[Transaction]
    verdict: EvidenceVerdict
    confidence: float
    reason_codes: list[str]
    ambiguous: bool = False


def normalize_complaint(text: str) -> str:
    return text.translate(BANGLA_DIGITS)


def extract_amounts(text: str) -> list[float]:
    normalized = normalize_complaint(text.lower())
    amounts: list[float] = []
    for match in AMOUNT_PATTERN.finditer(normalized):
        raw = match.group(0)
        digits = re.sub(r"[^\d.]", "", raw.split()[0] if " " in raw else raw)
        if digits:
            try:
                amounts.append(float(digits))
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


def parse_timestamp(value: str) -> Optional[datetime]:
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        else:
            dt = dt.astimezone(timezone.utc)
        return dt
    except ValueError:
        return None


def detect_case_type(complaint: str, user_type: str | None) -> CaseType:
    text = normalize_complaint(complaint.lower())

    phishing_signals = [
        "otp", "pin", "password", "scam", "phishing", "fake call", "fraud", "fake",
        "ওটিপি", "পিন", "পাসওয়ার্ড", "প্রতারণা", "নকল", "ঠকানো",
    ]
    contact_signals = [
        "call", "sms", "message", "phone", "texted", "emailed", "whatsapp",
        "ফোন", "মেসেজ", "called", "asked", "asking", "told me", "জিজ্ঞাসা",
        "pathao", "pathaben", "block hobe", "ব্লক", "পাঠান",
    ]
    report_signals = [
        "is this real", "legit", "safe", "haven't shared", "did not share",
        "শেয়ার করিনি", "eta ki sotti", "sotti ki", "is this true",
    ]
    if any(k in text for k in phishing_signals):
        if any(w in text for w in contact_signals) or any(w in text for w in report_signals):
            return "phishing_or_social_engineering"
        if re.search(r"(?:asked|asking|wanted|want|bole).{0,40}(?:otp|pin|password)", text):
            return "phishing_or_social_engineering"

    duplicate_signals = [
        "duplicate", "twice", "double", "duibar", "dui bar", "দুইবার", "two times",
        "bar bar", "2 bar", "dobare", "repeat", "again charged", "আবার কেটেছে", "বারবার",
    ]
    if any(s in text for s in duplicate_signals):
        return "duplicate_payment"

    if user_type == "merchant" and (
        "settlement" in text or "settled" in text or "settlement delay" in text
    ):
        return "merchant_settlement_delay"

    wrong_transfer_signals = [
        "wrong", "mistake", "ভুল", "vul", "bhul", "galat", "incorrect number",
        "wrong number", "vul number", "bhul number", "vul nomber", "bhul nomber",
        "onno number", "paw ni", "peyeni", "pouchay nai", "transfer korechi",
        "pathanor", "ভুল নম্বরে", "অন্য নম্বরে", "পাচ্ছে না",
    ]
    if any(w in text for w in wrong_transfer_signals) or "pathaisi" in text or "pathiye" in text:
        return "wrong_transfer"

    agent_cash_in_signals = [
        "cash in", "kash in", "cash-in", "cashin", "kashin", "ক্যাশ ইন",
        "joma", "deposit", "reflect hoy nai", "balance e ashe nai", "agent theke",
        "জমা", "রিফ্লেক্ট", "ব্যালেন্সে আসেনি",
    ]
    if (
        any(s in text for s in agent_cash_in_signals)
        or (user_type == "agent" and "balance" in text)
        or ("agent" in text and ("balance" in text or "kache" in text or "ashe nai" in text or "asheni" in text))
        or ("এজেন্ট" in text and ("ব্যালেন্স" in text or "টাকা" in text))
    ):
        return "agent_cash_in_issue"

    failure_context_signals = [
        "failed", "deducted", "error", "unsuccessful", "did not complete",
        "not completed", "stuck", "didn't go through", "did not go through",
        "money was cut", "balance cut", "balance was cut", "balance was",
        "recharge", "top up", "top-up", "electricity", "bill payment",
        "dekhay", "dekhacche", "hoise", "kete niye", "kata", "katche",
        "cut hoise", "pari nai", "recharge hoy nai", "success hoy nai",
        "success dekhay na", "pending dekhay",
        "ব্যালেন্স কাট", "ফেল", "হয়নি", "কেটে নিয়েছে", "সফল হয়নি", "জমা হয়নি",
    ]
    has_failure_context = any(s in text for s in failure_context_signals)

    if has_failure_context and not any(w in text for w in wrong_transfer_signals):
        return "payment_failed"

    refund_signals = [
        "refund", "ফেরত", "ferot", "change my mind", "cancel",
        "money back", "taka back", "return chai", "cancel kore",
        "pochondo hoy nai", "ফেরত চাই", "টাকা ফেরত", "রিফান্ড",
    ]
    if any(s in text for s in refund_signals):
        return "refund_request"

    not_received_signals = [
        "didn't get", "not received", "did not receive", "পায়নি", "পাইনি",
    ]
    if any(s in text for s in not_received_signals):
        return "wrong_transfer"

    return "other"


def is_vague_complaint(complaint: str) -> bool:
    text = normalize_complaint(complaint.lower().strip())
    amounts = extract_amounts(text)
    vague_phrases = [
        "something is wrong",
        "please check",
        "help me",
        "সমস্যা",
        "kisu somossa",
        "somossa hocche",
        "check korben",
        "dekhben",
        "help lagbe",
        "taka niye",
    ]
    vague_without_amount = any(p in text for p in vague_phrases) and not amounts
    short_and_vague = len(text) < 60 and "my money" in text and not amounts
    return vague_without_amount or short_and_vague


def find_duplicate_pair(transactions: list[Transaction]) -> Optional[Transaction]:
    """Return the latest transaction in the most recent duplicate pair within 120 seconds."""
    best: Optional[Transaction] = None
    best_time: Optional[datetime] = None

    for i, a in enumerate(transactions):
        for b in transactions[i + 1 :]:
            if (
                a.type == b.type == "payment"
                and a.amount == b.amount
                and a.counterparty == b.counterparty
                and a.status == b.status == "completed"
            ):
                ta = parse_timestamp(a.timestamp)
                tb = parse_timestamp(b.timestamp)
                if not ta or not tb:
                    continue
                if abs((tb - ta).total_seconds()) > 120:
                    continue
                later = b if tb >= ta else a
                later_time = tb if tb >= ta else ta
                if best_time is None or later_time > best_time:
                    best = later
                    best_time = later_time
    return best


def should_infer_duplicate_payment(complaint: str, transactions: list[Transaction]) -> bool:
    """Infer duplicate_payment when history has a duplicate pair and complaint hints at double charge."""
    duplicate = find_duplicate_pair(transactions)
    if not duplicate:
        return False
    text = normalize_complaint(complaint.lower())
    amounts = extract_amounts(text)
    if amounts and any(abs(duplicate.amount - a) < 0.01 for a in amounts):
        return True
    charge_signals = [
        "bill", "biller", "desco", "electricity", "বিল",
        "katche", "kata", "charged", "cut", "kete", "কেটেছে",
        "bar bar", "2 bar",
    ]
    return any(s in text for s in charge_signals)


def score_transaction(txn: Transaction, complaint: str, amounts: list[float], case_type: CaseType) -> float:
    score = 0.0
    text = normalize_complaint(complaint.lower())

    if amounts and any(abs(txn.amount - a) < 0.01 for a in amounts):
        score += 3.0

    if case_type == "payment_failed" and txn.status == "failed":
        score += 4.0
    if case_type == "agent_cash_in_issue" and txn.type == "cash_in":
        score += 4.0
    if case_type == "merchant_settlement_delay" and txn.type == "settlement":
        score += 4.0
    if case_type == "wrong_transfer" and txn.type == "transfer":
        score += 2.0
    if case_type == "refund_request" and txn.type == "payment" and txn.status == "completed":
        score += 3.0

    if "yesterday" in text or "গতকাল" in text:
        ts = parse_timestamp(txn.timestamp)
        if ts and ts.day:
            score += 0.5

    if "today" in text or "আজ" in text:
        score += 0.5

    if txn.status == "pending" and (
        "pending" in text or "not reflected" in text or "আসেনি" in text
        or "ashe nai" in text or "asheni" in text
    ):
        score += 2.0

    return score


def check_established_recipient_pattern(transactions: list[Transaction], target: Transaction) -> bool:
    same_counterparty = [
        t
        for t in transactions
        if t.counterparty == target.counterparty
        and t.type == "transfer"
        and t.status == "completed"
    ]
    return len(same_counterparty) >= 2


def has_transaction_disambiguators(complaint: str) -> bool:
    return bool(
        extract_amounts(complaint)
        or extract_phone_numbers(complaint)
        or extract_transaction_ids(complaint)
    )


def resolve_phone_amount_matches(
    matches: list[Transaction],
    complaint: str,
    case_type: CaseType,
    transactions: list[Transaction],
) -> MatchResult | None:
    """Disambiguate multiple phone matches using amount and transaction status."""
    amounts = extract_amounts(complaint)
    if amounts:
        matches = [t for t in matches if any(abs(t.amount - a) < 0.01 for a in amounts)]
    if not matches:
        return None
    if len(matches) == 1:
        txn = matches[0]
        verdict: EvidenceVerdict = "consistent"
        reasons = ["counterparty_phone_match", "transaction_match"]
        if amounts:
            reasons.append("phone_and_amount_match")
        if case_type == "wrong_transfer" and check_established_recipient_pattern(transactions, txn):
            verdict = "inconsistent"
            reasons.append("evidence_inconsistent")
        confidence = 0.88 if len(reasons) == 2 else 0.87
        return MatchResult(txn, verdict, confidence, reasons)
    if case_type == "wrong_transfer":
        completed = [t for t in matches if t.status == "completed"]
        if len(completed) == 1:
            txn = completed[0]
            verdict = "consistent"
            reasons = ["counterparty_phone_match", "transaction_match", "phone_and_amount_match"]
            if check_established_recipient_pattern(transactions, txn):
                verdict = "inconsistent"
                reasons.append("evidence_inconsistent")
            return MatchResult(txn, verdict, 0.87, reasons)
    return MatchResult(
        None,
        "insufficient_data",
        0.65,
        ["ambiguous_match", "needs_clarification"],
        ambiguous=True,
    )


def match_by_explicit_ids(complaint: str, transactions: list[Transaction]) -> Optional[Transaction]:
    mentioned = {tid.upper() for tid in extract_transaction_ids(complaint)}
    if not mentioned:
        return None
    for txn in transactions:
        if txn.transaction_id.upper() in mentioned:
            return txn
    return None


def match_by_phone(complaint: str, transactions: list[Transaction]) -> list[Transaction]:
    phones = {normalize_phone(p) for p in extract_phone_numbers(complaint)}
    if not phones:
        return []
    return [t for t in transactions if normalize_phone(t.counterparty) in phones]


def match_transactions(
    complaint: str,
    transactions: list[Transaction],
    case_type: CaseType,
) -> MatchResult:
    if not transactions:
        return MatchResult(None, "insufficient_data", 0.6, ["no_transactions"])

    if case_type == "duplicate_payment":
        duplicate = find_duplicate_pair(transactions)
        if duplicate:
            return MatchResult(
                duplicate,
                "consistent",
                0.93,
                ["duplicate_payment", "biller_verification_required"],
            )

    explicit = match_by_explicit_ids(complaint, transactions)
    if explicit:
        verdict: EvidenceVerdict = "consistent"
        reasons = ["explicit_transaction_id", "transaction_match"]
        if case_type == "wrong_transfer" and check_established_recipient_pattern(transactions, explicit):
            verdict = "inconsistent"
            reasons.extend(["established_recipient_pattern", "evidence_inconsistent"])
        return MatchResult(explicit, verdict, 0.92, reasons)

    phone_matches = match_by_phone(complaint, transactions)
    if len(phone_matches) == 1:
        txn = phone_matches[0]
        verdict = "consistent"
        reasons = ["counterparty_phone_match", "transaction_match"]
        if case_type == "wrong_transfer" and check_established_recipient_pattern(transactions, txn):
            verdict = "inconsistent"
            reasons.append("evidence_inconsistent")
        return MatchResult(txn, verdict, 0.88, reasons)
    if len(phone_matches) > 1:
        resolved = resolve_phone_amount_matches(phone_matches, complaint, case_type, transactions)
        if resolved:
            return resolved

    amounts = extract_amounts(complaint)
    if case_type == "wrong_transfer" and not has_transaction_disambiguators(complaint):
        transfer_txns = [t for t in transactions if t.type == "transfer"]
        if len(transfer_txns) > 1:
            return MatchResult(
                None,
                "insufficient_data",
                0.65,
                ["ambiguous_match", "needs_clarification"],
                ambiguous=True,
            )
        if len(transfer_txns) == 1:
            return MatchResult(None, "insufficient_data", 0.6, ["no_clear_match", "needs_clarification"])

    amounts = extract_amounts(complaint)
    scored = [(txn, score_transaction(txn, complaint, amounts, case_type)) for txn in transactions]
    scored.sort(key=lambda item: item[1], reverse=True)

    best_txn, best_score = scored[0]
    second_score = scored[1][1] if len(scored) > 1 else 0.0

    if case_type == "wrong_transfer" and amounts:
        matching_amount = [txn for txn, s in scored if s >= 3.0]
        if len(matching_amount) > 1 and second_score >= best_score - 0.5:
            return MatchResult(
                None,
                "insufficient_data",
                0.65,
                ["ambiguous_match", "needs_clarification"],
                ambiguous=True,
            )

    if case_type == "wrong_transfer" and not has_transaction_disambiguators(complaint):
        return MatchResult(None, "insufficient_data", 0.6, ["no_clear_match", "needs_clarification"])

    if best_score < 2.0:
        return MatchResult(None, "insufficient_data", 0.6, ["no_clear_match"])

    verdict: EvidenceVerdict = "consistent"
    reasons = ["transaction_match"]

    if case_type == "wrong_transfer" and check_established_recipient_pattern(transactions, best_txn):
        verdict = "inconsistent"
        reasons.extend(["wrong_transfer_claim", "established_recipient_pattern", "evidence_inconsistent"])

    if case_type == "payment_failed" and best_txn.status == "failed":
        reasons.append("potential_balance_deduction")
    elif case_type == "payment_failed" and best_txn.status == "completed":
        verdict = "inconsistent"
        reasons.append("payment_claim_mismatch")

    if case_type == "agent_cash_in_issue" and best_txn.status == "pending":
        reasons.extend(["agent_cash_in", "pending_transaction", "agent_ops"])

    if case_type == "merchant_settlement_delay" and best_txn.status == "pending":
        reasons.extend(["merchant_settlement", "delay", "pending"])

    return MatchResult(best_txn, verdict, min(0.95, 0.7 + best_score * 0.05), reasons)


def route_department(case_type: CaseType, severity: Severity) -> Department:
    mapping: dict[CaseType, Department] = {
        "wrong_transfer": "dispute_resolution",
        "payment_failed": "payments_ops",
        "refund_request": "customer_support",
        "duplicate_payment": "payments_ops",
        "merchant_settlement_delay": "merchant_operations",
        "agent_cash_in_issue": "agent_operations",
        "phishing_or_social_engineering": "fraud_risk",
        "other": "customer_support",
    }
    dept = mapping[case_type]
    if case_type == "refund_request" and severity in ("high", "critical"):
        return "dispute_resolution"
    return dept


def determine_severity(case_type: CaseType, match: MatchResult, complaint: str) -> Severity:
    if case_type == "phishing_or_social_engineering":
        return "critical"
    if case_type in ("duplicate_payment", "payment_failed", "agent_cash_in_issue", "wrong_transfer"):
        if match.verdict == "inconsistent":
            return "medium"
        return "high"
    if case_type == "merchant_settlement_delay":
        return "medium"
    if case_type == "refund_request":
        return "low"
    return "low"


def needs_human_review(case_type: CaseType, match: MatchResult, severity: Severity) -> bool:
    if case_type == "phishing_or_social_engineering":
        return True
    if match.verdict == "insufficient_data" and case_type in ("wrong_transfer", "duplicate_payment"):
        return False
    if case_type in ("wrong_transfer", "duplicate_payment") and match.verdict == "consistent":
        return True
    if match.verdict == "inconsistent":
        return True
    if case_type == "agent_cash_in_issue" and match.transaction:
        return True
    if severity == "critical":
        return True
    if match.transaction and match.transaction.amount >= 10000 and case_type in (
        "wrong_transfer",
        "duplicate_payment",
        "payment_failed",
    ):
        return True
    return False


def build_agent_summary(
    request: AnalyzeTicketRequest,
    case_type: CaseType,
    match: MatchResult,
) -> str:
    complaint = request.complaint
    txn = match.transaction

    if case_type == "phishing_or_social_engineering":
        return (
            "Customer reports an unsolicited contact claiming to be from the company and asking for credentials. "
            "Customer has not shared credentials. Likely social engineering attempt."
        )

    if is_vague_complaint(request.complaint):
        return (
            "Customer reports a vague concern about their money without specifying transaction, amount, or issue. "
            "Insufficient detail to identify any relevant transaction."
        )

    if match.ambiguous:
        return (
            "Customer reports a transfer that was not received, but multiple transactions of the same amount exist. "
            "Cannot determine the correct transaction without further input."
        )

    if txn:
        return (
            f"Customer concern relates to {txn.transaction_id} ({txn.amount:.0f} BDT, {txn.type}, "
            f"status {txn.status}). Case classified as {case_type.replace('_', ' ')}."
        )

    return f"Customer concern classified as {case_type.replace('_', ' ')} with insufficient transaction evidence."


def build_next_action(case_type: CaseType, match: MatchResult, txn_id: str | None) -> str:
    if match.ambiguous:
        return (
            "Reply to customer asking for the recipient's number to identify the correct transaction. "
            "Do not initiate dispute until the transaction is confirmed."
        )

    if case_type == "phishing_or_social_engineering":
        return (
            "Escalate to fraud_risk team immediately. Confirm that the company never asks for OTP. "
            "Log the reported number for fraud pattern analysis."
        )

    if case_type == "other" and match.verdict == "insufficient_data":
        return (
            "Reply to customer asking for specific details: which transaction, what amount, "
            "what went wrong, and approximate time."
        )

    if case_type == "wrong_transfer" and match.verdict == "inconsistent" and txn_id:
        return (
            "Flag for human review. Verify with the customer whether this was genuinely a wrong transfer "
            "given the established transaction pattern with this recipient."
        )

    if case_type == "wrong_transfer" and txn_id:
        return f"Verify {txn_id} details with the customer and initiate the wrong-transfer dispute workflow per policy."

    if case_type == "payment_failed" and txn_id:
        return (
            f"Investigate {txn_id} ledger status. If balance was deducted on a failed payment, "
            "initiate the automatic reversal flow within standard SLA."
        )

    if case_type == "refund_request":
        return (
            "Inform the customer that refund eligibility depends on the merchant's own policy. "
            "Provide guidance on contacting the merchant directly for a refund."
        )

    if case_type == "duplicate_payment" and txn_id:
        return (
            f"Verify the duplicate with payments_ops. If the biller confirms only one payment was received, "
            f"initiate reversal of {txn_id}."
        )

    if case_type == "merchant_settlement_delay" and txn_id:
        return (
            "Route to merchant_operations to verify settlement batch status. "
            "If the batch is delayed, communicate a revised ETA to the merchant."
        )

    if case_type == "agent_cash_in_issue" and txn_id:
        return (
            f"Investigate {txn_id} pending status with agent operations. "
            "Confirm settlement state and resolve within the standard cash-in SLA."
        )

    return "Review the case details and follow the standard support workflow."


def build_customer_reply(
    request: AnalyzeTicketRequest,
    case_type: CaseType,
    match: MatchResult,
    txn_id: str | None,
) -> str:
    lang = request.language or ("bn" if is_bangla_text(request.complaint) else "en")

    if case_type == "phishing_or_social_engineering":
        if lang == "bn":
            return (
                "যোগাযোগ করার জন্য ধন্যবাদ। আমরা কখনোই আপনার পিন, ওটিপি বা পাসওয়ার্ড চাই না। "
                "অনুগ্রহ করে কারো সাথে এগুলো শেয়ার করবেন না। আমাদের ফ্রড দলকে জানানো হয়েছে।"
            )
        return (
            "Thank you for reaching out before sharing any information. "
            "We never ask for your PIN, OTP, or password under any circumstances. "
            "Please do not share these with anyone, even if they claim to be from us. "
            "Our fraud team has been notified of this incident."
        )

    if is_vague_complaint(request.complaint):
        return (
            "Thank you for reaching out. To help you faster, please share the transaction ID, "
            "the amount involved, and a short description of what went wrong. "
            "Please do not share your PIN or OTP with anyone."
        )

    if match.ambiguous:
        return (
            "Thank you for reaching out. We see multiple transactions of the same amount on that date. "
            "Could you share the recipient's number so we can identify the right transaction? "
            "Please do not share your PIN or OTP with anyone."
        )

    if case_type == "refund_request" and txn_id:
        return (
            "Thank you for reaching out. Refunds for completed merchant payments depend on the merchant's own policy. "
            "We recommend contacting the merchant directly. If you need help reaching them, please reply and we will guide you. "
            "Please do not share your PIN or OTP with anyone."
        )

    if case_type == "payment_failed" and txn_id:
        return (
            f"We have noted that transaction {txn_id} may have caused an unexpected balance deduction. "
            "Our payments team will review the case and any eligible amount will be returned through official channels. "
            "Please do not share your PIN or OTP with anyone."
        )

    if case_type == "duplicate_payment" and txn_id:
        return (
            f"We have noted the possible duplicate payment for transaction {txn_id}. "
            "Our payments team will verify with the biller and any eligible amount will be returned through official channels. "
            "Please do not share your PIN or OTP with anyone."
        )

    if case_type == "merchant_settlement_delay" and txn_id:
        return (
            f"We have noted your concern about settlement {txn_id}. "
            "Our merchant operations team will check the batch status and update you on the expected settlement time "
            "through official channels."
        )

    if case_type == "agent_cash_in_issue" and txn_id:
        if lang == "bn":
            return (
                f"আপনার লেনদেন {txn_id} এর বিষয়ে আমরা অবগত হয়েছি। "
                "আমাদের এজেন্ট অপারেশন্স দল এটি দ্রুত যাচাই করবে এবং অফিসিয়াল চ্যানেলে আপনাকে জানাবে। "
                "অনুগ্রহ করে কারো সাথে আপনার পিন বা ওটিপি শেয়ার করবেন না।"
            )
        return (
            f"We have noted your concern about transaction {txn_id}. "
            "Our agent operations team will review the case and contact you through official support channels. "
            "Please do not share your PIN or OTP with anyone."
        )

    if case_type == "wrong_transfer" and txn_id:
        return (
            f"We have noted your concern about transaction {txn_id}. "
            "Please do not share your PIN or OTP with anyone. "
            "Our dispute team will review the case and contact you through official support channels."
        )

    return (
        "Thank you for contacting us. Our support team will review your case and follow up through official channels. "
        "Please do not share your PIN or OTP with anyone."
    )


def analyze_ticket(request: AnalyzeTicketRequest) -> AnalyzeTicketResponse:
    """Sync entry point for tests and scripts."""
    return asyncio.run(analyze_ticket_async(request))


async def analyze_ticket_async(request: AnalyzeTicketRequest) -> AnalyzeTicketResponse:
    complaint = sanitize_complaint_for_analysis(request.complaint)
    if not complaint.strip():
        case_type: CaseType = "other"
        match = MatchResult(None, "insufficient_data", 0.5, ["sanitized_empty", "needs_clarification"])
        txn_id = None
        severity = determine_severity(case_type, match, complaint)
        department = route_department(case_type, severity)
        human_review = needs_human_review(case_type, match, severity)
        agent_summary = (
            "Customer message contained no usable complaint details after safety sanitization. "
            "Insufficient detail to investigate."
        )
        next_action = (
            "Reply to customer asking for specific details: which transaction, what amount, "
            "what went wrong, and approximate time."
        )
        customer_reply = (
            "Thank you for reaching out. To help you faster, please share the transaction ID, "
            "the amount involved, and a short description of what went wrong. "
            "Please do not share your PIN or OTP with anyone."
        )
        lang = request.language or "en"
        customer_reply, next_action = apply_safety_guardrails(customer_reply, next_action, lang)
        return AnalyzeTicketResponse(
            ticket_id=request.ticket_id,
            relevant_transaction_id=None,
            evidence_verdict=match.verdict,
            case_type=case_type,
            severity=severity,
            department=department,
            agent_summary=agent_summary,
            recommended_next_action=next_action,
            customer_reply=customer_reply,
            human_review_required=human_review,
            confidence=match.confidence,
            reason_codes=match.reason_codes,
        )

    case_type = detect_case_type(complaint, request.user_type)

    if case_type != "phishing_or_social_engineering" and should_infer_duplicate_payment(
        complaint, request.transaction_history
    ):
        case_type = "duplicate_payment"

    if is_vague_complaint(complaint):
        case_type = "other"
        match = MatchResult(None, "insufficient_data", 0.6, ["vague_complaint", "needs_clarification"])
    elif case_type == "phishing_or_social_engineering":
        match = MatchResult(None, "insufficient_data", 0.95, ["phishing", "credential_protection", "critical_escalation"])
    else:
        match = match_transactions(complaint, request.transaction_history, case_type)

    vague = is_vague_complaint(complaint)
    rules_case_type = case_type

    import os

    if os.getenv("USE_GEMINI", "").strip().lower() in ("1", "true", "yes", "on"):
        from app.agent import merge_case_type, route_with_gemini, should_invoke_gemini

        if should_invoke_gemini(
            match.confidence,
            ambiguous=match.ambiguous,
            case_type=case_type,
            vague=vague,
        ):
            gemini = await route_with_gemini(request, complaint)
            if gemini:
                merged_type = merge_case_type(rules_case_type, gemini)
                complaint_for_match = (
                    gemini.filtered_complaint.strip()
                    if gemini.filtered_complaint.strip()
                    else complaint
                )
                if merged_type != case_type:
                    case_type = merged_type
                    if case_type == "phishing_or_social_engineering":
                        match = MatchResult(
                            None,
                            "insufficient_data",
                            max(match.confidence, gemini.confidence),
                            ["phishing", "credential_protection", "critical_escalation", "gemini_routed"],
                        )
                    else:
                        match = match_transactions(
                            complaint_for_match, request.transaction_history, case_type
                        )
                reason_codes = list(match.reason_codes)
                if "gemini_routed" not in reason_codes:
                    reason_codes.append("gemini_routed")
                match = MatchResult(
                    match.transaction,
                    match.verdict,
                    round(max(match.confidence, gemini.confidence), 2),
                    reason_codes,
                    ambiguous=match.ambiguous,
                )

    txn_id = match.transaction.transaction_id if match.transaction else None
    severity = determine_severity(case_type, match, complaint)
    department = route_department(case_type, severity)
    human_review = needs_human_review(case_type, match, severity)

    agent_summary = build_agent_summary(request, case_type, match)
    next_action = build_next_action(case_type, match, txn_id)
    customer_reply = build_customer_reply(request, case_type, match, txn_id)

    lang = request.language or ("bn" if is_bangla_text(request.complaint) else "en")
    customer_reply, next_action = apply_safety_guardrails(customer_reply, next_action, lang)

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
