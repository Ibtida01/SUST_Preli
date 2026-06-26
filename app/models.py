from __future__ import annotations

from typing import Any, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator

Language = Literal["en", "bn", "mixed"]
Channel = Literal["in_app_chat", "call_center", "email", "merchant_portal", "field_agent"]
UserType = Literal["customer", "merchant", "agent", "unknown"]
TransactionType = Literal["transfer", "payment", "cash_in", "cash_out", "settlement", "refund"]
TransactionStatus = Literal["completed", "failed", "pending", "reversed"]
EvidenceVerdict = Literal["consistent", "inconsistent", "insufficient_data"]
CaseType = Literal[
    "wrong_transfer",
    "payment_failed",
    "refund_request",
    "duplicate_payment",
    "merchant_settlement_delay",
    "agent_cash_in_issue",
    "phishing_or_social_engineering",
    "other",
]
Severity = Literal["low", "medium", "high", "critical"]
Department = Literal[
    "customer_support",
    "dispute_resolution",
    "payments_ops",
    "merchant_operations",
    "agent_operations",
    "fraud_risk",
]


class Transaction(BaseModel):
    model_config = ConfigDict(extra="ignore")

    transaction_id: str = ""
    timestamp: str = ""
    type: TransactionType = "payment"
    amount: float = 0.0
    counterparty: str = ""
    status: TransactionStatus = "pending"

    @field_validator("transaction_id", "timestamp", "counterparty", mode="before")
    @classmethod
    def stringify_text_fields(cls, value: Any) -> str:
        return "" if value is None else str(value)

    @field_validator("amount", mode="before")
    @classmethod
    def normalize_amount(cls, value: Any) -> float:
        if value is None:
            return 0.0
        if isinstance(value, (int, float)):
            return float(value)
        cleaned = str(value).replace(",", "").strip()
        try:
            return float(cleaned)
        except ValueError:
            return 0.0

    @field_validator("type", mode="before")
    @classmethod
    def normalize_type(cls, value: Any) -> TransactionType:
        normalized = str(value or "").strip().lower().replace("-", "_").replace(" ", "_")
        aliases = {
            "agent_cash_in": "cash_in",
            "bill_pay": "payment",
            "bill_payment": "payment",
            "cash_deposit": "cash_in",
            "cashin": "cash_in",
            "cashout": "cash_out",
            "merchant_payment": "payment",
            "merchant_settlement": "settlement",
            "mobile_recharge": "payment",
            "p2p": "transfer",
            "payout": "settlement",
            "send_money": "transfer",
        }
        normalized = aliases.get(normalized, normalized)
        allowed = {"transfer", "payment", "cash_in", "cash_out", "settlement", "refund"}
        return normalized if normalized in allowed else "payment"

    @field_validator("status", mode="before")
    @classmethod
    def normalize_status(cls, value: Any) -> TransactionStatus:
        normalized = str(value or "").strip().lower()
        aliases = {
            "cancelled": "reversed",
            "canceled": "reversed",
            "complete": "completed",
            "declined": "failed",
            "error": "failed",
            "in_progress": "pending",
            "processing": "pending",
            "queued": "pending",
            "refunded": "reversed",
            "rejected": "failed",
            "reversal": "reversed",
            "succeeded": "completed",
            "success": "completed",
            "successful": "completed",
        }
        normalized = aliases.get(normalized, normalized)
        allowed = {"completed", "failed", "pending", "reversed"}
        return normalized if normalized in allowed else "pending"


class AnalyzeTicketRequest(BaseModel):
    model_config = ConfigDict(extra="ignore")

    ticket_id: str
    complaint: str = Field(min_length=1)
    language: Optional[Language] = None
    channel: Optional[Channel] = None
    user_type: Optional[UserType] = None
    campaign_context: Optional[str] = None
    transaction_history: list[Transaction] = Field(default_factory=list)
    metadata: Optional[dict] = None

    @field_validator("ticket_id", "complaint", mode="before")
    @classmethod
    def stringify_required_text(cls, value: Any) -> str:
        return "" if value is None else str(value)

    @field_validator("language", mode="before")
    @classmethod
    def normalize_language(cls, value: Any) -> Language | None:
        normalized = str(value or "").strip().lower()
        if normalized in {"en", "english"}:
            return "en"
        if normalized in {"bn", "bangla", "bengali"}:
            return "bn"
        if normalized in {"mixed", "banglish", "bn-en"}:
            return "mixed"
        return None

    @field_validator("channel", mode="before")
    @classmethod
    def normalize_channel(cls, value: Any) -> Channel | None:
        normalized = str(value or "").strip().lower().replace("-", "_").replace(" ", "_")
        allowed = {"in_app_chat", "call_center", "email", "merchant_portal", "field_agent"}
        return normalized if normalized in allowed else None

    @field_validator("user_type", mode="before")
    @classmethod
    def normalize_user_type(cls, value: Any) -> UserType | None:
        normalized = str(value or "").strip().lower()
        allowed = {"customer", "merchant", "agent", "unknown"}
        return normalized if normalized in allowed else None

    @field_validator("transaction_history", mode="before")
    @classmethod
    def normalize_transaction_history(cls, value: Any) -> list[Any]:
        if not isinstance(value, list):
            return []
        return [item for item in value if isinstance(item, dict)]


class AnalyzeTicketResponse(BaseModel):
    ticket_id: str
    relevant_transaction_id: Optional[str]
    evidence_verdict: EvidenceVerdict
    case_type: CaseType
    severity: Severity
    department: Department
    agent_summary: str
    recommended_next_action: str
    customer_reply: str
    human_review_required: bool
    confidence: Optional[float] = Field(default=None, ge=0.0, le=1.0)
    reason_codes: Optional[list[str]] = None


class HealthResponse(BaseModel):
    status: Literal["ok"] = "ok"


class ErrorResponse(BaseModel):
    detail: str
