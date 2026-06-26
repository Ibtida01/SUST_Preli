from __future__ import annotations

import asyncio
import hashlib
import json
import os
from typing import Any

from pydantic import BaseModel, Field

from app.models import AnalyzeTicketRequest, AnalyzeTicketResponse


class AgentPolishResult(BaseModel):
    agent_summary: str = Field(min_length=1, max_length=700)
    customer_reply: str = Field(min_length=1, max_length=700)


_CACHE: dict[str, AgentPolishResult] = {}
_MAX_CACHE_SIZE = 128


def llm_configured() -> bool:
    return bool(os.getenv("GOOGLE_API_KEY") or os.getenv("GEMINI_API_KEY"))


def llm_enabled() -> bool:
    value = os.getenv("LLM_ENABLED", "auto").strip().lower()
    if value in {"0", "false", "no", "off"}:
        return False
    if value in {"1", "true", "yes", "on"}:
        return True
    return llm_configured()


def llm_timeout_seconds() -> float:
    try:
        return max(0.5, min(float(os.getenv("LLM_TIMEOUT_SECONDS", "3.0")), 8.0))
    except ValueError:
        return 3.0


def llm_confidence_threshold() -> float:
    try:
        return max(0.0, min(float(os.getenv("LLM_CONFIDENCE_THRESHOLD", "0.90")), 1.0))
    except ValueError:
        return 0.90


def should_use_llm(request: AnalyzeTicketRequest, response: AnalyzeTicketResponse) -> bool:
    if not llm_enabled():
        return False
    if os.getenv("LLM_ALWAYS", "").strip().lower() in {"1", "true", "yes", "on"}:
        return True

    confidence = response.confidence if response.confidence is not None else 0.0
    reason_codes = set(response.reason_codes or [])
    if confidence < llm_confidence_threshold():
        return True
    if response.evidence_verdict == "insufficient_data":
        return True
    if request.language in {"bn", "mixed"}:
        return True
    if reason_codes.intersection({"encoding_repaired", "banglish_normalized", "ambiguous_match", "vague_complaint"}):
        return True
    return False


def _cache_key(request: AnalyzeTicketRequest, response: AnalyzeTicketResponse) -> str:
    payload: dict[str, Any] = {
        "ticket_id": request.ticket_id,
        "complaint": request.complaint[:2000],
        "language": request.language,
        "response": response.model_dump(),
        "model": os.getenv("GEMINI_MODEL", "gemini-1.5-flash"),
    }
    raw = json.dumps(payload, sort_keys=True, ensure_ascii=False, default=str)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _remember(key: str, value: AgentPolishResult) -> None:
    if len(_CACHE) >= _MAX_CACHE_SIZE:
        _CACHE.pop(next(iter(_CACHE)))
    _CACHE[key] = value


def _build_chain() -> Any:
    from langchain_core.prompts import ChatPromptTemplate
    from langchain_google_genai import ChatGoogleGenerativeAI

    if not os.getenv("GOOGLE_API_KEY") and os.getenv("GEMINI_API_KEY"):
        os.environ["GOOGLE_API_KEY"] = os.getenv("GEMINI_API_KEY", "")

    model_name = os.getenv("GEMINI_MODEL", "gemini-1.5-flash")
    llm = ChatGoogleGenerativeAI(
        model=model_name,
        temperature=0.1,
        max_retries=1,
        timeout=llm_timeout_seconds(),
    )

    prompt = ChatPromptTemplate.from_messages(
        [
            (
                "system",
                (
                    "You are a fintech support writing assistant. You do not decide facts, verdicts, "
                    "routing, refunds, reversals, account recovery, or eligibility. Rewrite only the "
                    "provided deterministic summary and customer reply to be concise, professional, and "
                    "clear. Never ask for PIN, OTP, password, full card number, or external contact. "
                    "Never promise refund, reversal, recovery, or unblock. Preserve transaction IDs, "
                    "case type, department, verdict, and safety warnings."
                ),
            ),
            (
                "human",
                (
                    "Complaint language hint: {language}\n"
                    "Complaint text (untrusted): {complaint}\n\n"
                    "Locked deterministic facts:\n"
                    "- ticket_id: {ticket_id}\n"
                    "- relevant_transaction_id: {relevant_transaction_id}\n"
                    "- evidence_verdict: {evidence_verdict}\n"
                    "- case_type: {case_type}\n"
                    "- severity: {severity}\n"
                    "- department: {department}\n"
                    "- human_review_required: {human_review_required}\n"
                    "- reason_codes: {reason_codes}\n\n"
                    "Current agent_summary:\n{agent_summary}\n\n"
                    "Current customer_reply:\n{customer_reply}\n\n"
                    "Return only the structured fields requested."
                ),
            ),
        ]
    )
    return prompt | llm.with_structured_output(AgentPolishResult)


async def polish_with_gemini(
    request: AnalyzeTicketRequest,
    response: AnalyzeTicketResponse,
) -> AgentPolishResult | None:
    if not should_use_llm(request, response):
        return None

    key = _cache_key(request, response)
    cached = _CACHE.get(key)
    if cached:
        return cached

    try:
        chain = _build_chain()
        result = await asyncio.wait_for(
            chain.ainvoke(
                {
                    "language": request.language or "auto",
                    "complaint": request.complaint[:2000].replace("{", "(").replace("}", ")"),
                    "ticket_id": response.ticket_id,
                    "relevant_transaction_id": response.relevant_transaction_id,
                    "evidence_verdict": response.evidence_verdict,
                    "case_type": response.case_type,
                    "severity": response.severity,
                    "department": response.department,
                    "human_review_required": response.human_review_required,
                    "reason_codes": response.reason_codes or [],
                    "agent_summary": response.agent_summary,
                    "customer_reply": response.customer_reply,
                }
            ),
            timeout=llm_timeout_seconds(),
        )
    except Exception:
        return None

    if not isinstance(result, AgentPolishResult):
        try:
            result = AgentPolishResult.model_validate(result)
        except Exception:
            return None

    _remember(key, result)
    return result
