#!/usr/bin/env python3

from __future__ import annotations

import asyncio
import sys

from dotenv import load_dotenv

load_dotenv()

from app.agent import is_gemini_enabled, route_with_gemini
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
    if not is_gemini_enabled():
        print("SKIP")
        sys.exit(0)

    req = AnalyzeTicketRequest.model_validate(AMBIGUOUS_CASE)
    probe = await route_with_gemini(req, req.complaint)
    out = (await analyze_ticket_async(req)).model_dump()

    assert out["case_type"] == "wrong_transfer"
    assert out["evidence_verdict"] == "insufficient_data"
    assert out["relevant_transaction_id"] is None

    if probe is None:
        print("PASS (rules fallback)")
        return

    assert "gemini_routed" in (out.get("reason_codes") or [])
    print("PASS")


if __name__ == "__main__":
    asyncio.run(main())
