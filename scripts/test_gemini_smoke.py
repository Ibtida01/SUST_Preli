#!/usr/bin/env python3
"""Live Gemini slow-path smoke test — skips when USE_GEMINI is not configured."""

from __future__ import annotations

import asyncio
import sys

from dotenv import load_dotenv

load_dotenv()

from app.agent import gemini_status, is_gemini_enabled, route_with_gemini
from app.investigator import analyze_ticket_async
from app.models import AnalyzeTicketRequest

AMBIGUOUS_CASE = {
    "ticket_id": "GEMINI-SMOKE-01",
    "complaint": "I sent money to the wrong number. Please help.",
    "language": "en",
    "user_type": "customer",
    "transaction_history": [
        {
            "transaction_id": "TXN-1",
            "timestamp": "2026-04-14T10:00:00Z",
            "type": "transfer",
            "amount": 500,
            "counterparty": "01700000000",
            "status": "completed",
        },
        {
            "transaction_id": "TXN-2",
            "timestamp": "2026-04-14T11:00:00Z",
            "type": "transfer",
            "amount": 1000,
            "counterparty": "01800000000",
            "status": "completed",
        },
    ],
}


async def main() -> None:
    print(f"Gemini status: {gemini_status()}")
    if not is_gemini_enabled():
        print("SKIP: set USE_GEMINI=true and GEMINI_API_KEY in .env to run")
        sys.exit(0)

    req = AnalyzeTicketRequest.model_validate(AMBIGUOUS_CASE)
    probe = await route_with_gemini(req, req.complaint)
    out = (await analyze_ticket_async(req)).model_dump()

    assert out["case_type"] == "wrong_transfer"
    assert out["evidence_verdict"] == "insufficient_data"
    assert out["relevant_transaction_id"] is None

    if probe is None:
        print("WARN: Gemini API unreachable (quota/model). Rules fallback OK.")
        print("PASS: ambiguous wrong-transfer stays insufficient_data without blind TXN pick")
        return

    assert "gemini_routed" in (out.get("reason_codes") or [])
    print("PASS: Gemini slow path + rules fallback semantics")
    print("reason_codes:", out.get("reason_codes"))


if __name__ == "__main__":
    asyncio.run(main())
