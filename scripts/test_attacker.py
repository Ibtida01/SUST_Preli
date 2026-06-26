#!/usr/bin/env python3
"""Adversarial edge cases from team red-team evaluation."""

from __future__ import annotations

import traceback

from app.investigator import analyze_ticket
from app.models import AnalyzeTicketRequest

ATTACKER_CASES = [
    {
        "id": "ATTACK-01",
        "label": "Blind Guessing (No Amount/Phone triggers first item pick)",
        "input": {
            "ticket_id": "TKT-A01",
            "complaint": "I sent money to the wrong number. Please help.",
            "language": "en",
            "channel": "in_app_chat",
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
        },
        "expect": {"evidence_verdict": "insufficient_data"},
    },
    {
        "id": "ATTACK-02",
        "label": "Bangla Digit Phone Number Failure",
        "input": {
            "ticket_id": "TKT-A02",
            "complaint": "ami ০১৭১২৩৪৫৬৭৮ e tk pathaisi vul kore.",
            "language": "bn",
            "channel": "in_app_chat",
            "user_type": "customer",
            "transaction_history": [
                {
                    "transaction_id": "TXN-3",
                    "timestamp": "2026-04-14T10:00:00Z",
                    "type": "transfer",
                    "amount": 500,
                    "counterparty": "+8801712345678",
                    "status": "completed",
                }
            ],
        },
        "expect": {"relevant_transaction_id": "TXN-3"},
    },
    {
        "id": "ATTACK-03",
        "label": "Failed transaction creates fake Established Recipient pattern",
        "input": {
            "ticket_id": "TKT-A03",
            "complaint": "I sent 500 to 01711111111 by mistake.",
            "language": "en",
            "channel": "in_app_chat",
            "user_type": "customer",
            "transaction_history": [
                {
                    "transaction_id": "TXN-4",
                    "timestamp": "2026-04-14T09:00:00Z",
                    "type": "transfer",
                    "amount": 500,
                    "counterparty": "01711111111",
                    "status": "failed",
                },
                {
                    "transaction_id": "TXN-5",
                    "timestamp": "2026-04-14T09:05:00Z",
                    "type": "transfer",
                    "amount": 500,
                    "counterparty": "01711111111",
                    "status": "completed",
                },
            ],
        },
        "expect": {"evidence_verdict": "consistent", "relevant_transaction_id": "TXN-5"},
    },
    {
        "id": "ATTACK-04",
        "label": "Transaction ID Hijacking (Multiple IDs in prompt)",
        "input": {
            "ticket_id": "TKT-A04",
            "complaint": "TXN-8 failed but I want a refund for TXN-7 which was a wrong transfer.",
            "language": "en",
            "channel": "in_app_chat",
            "user_type": "customer",
            "transaction_history": [
                {
                    "transaction_id": "TXN-7",
                    "timestamp": "2026-04-14T10:00:00Z",
                    "type": "transfer",
                    "amount": 5000,
                    "counterparty": "01700000000",
                    "status": "completed",
                },
                {
                    "transaction_id": "TXN-8",
                    "timestamp": "2026-04-14T11:00:00Z",
                    "type": "payment",
                    "amount": 100,
                    "counterparty": "MERCH",
                    "status": "failed",
                },
            ],
        },
        "expect": {"relevant_transaction_id": "TXN-7"},
    },
    {
        "id": "ATTACK-05",
        "label": "Hierarchy Shadowing (Wrong overrides Merchant Delay)",
        "input": {
            "ticket_id": "TKT-A05",
            "complaint": "I am a merchant, my settlement is delayed and the amount is wrong.",
            "language": "en",
            "channel": "merchant_portal",
            "user_type": "merchant",
            "transaction_history": [
                {
                    "transaction_id": "TXN-9",
                    "timestamp": "2026-04-14T10:00:00Z",
                    "type": "settlement",
                    "amount": 50000,
                    "counterparty": "SELF",
                    "status": "pending",
                }
            ],
        },
        "expect": {"case_type": "merchant_settlement_delay"},
    },
]


def main() -> None:
    passed = 0
    for case in ATTACKER_CASES:
        req = AnalyzeTicketRequest.model_validate(case["input"])
        try:
            out = analyze_ticket(req).model_dump()
            ok = True
            for key, value in case["expect"].items():
                if out.get(key) != value:
                    print(f"FAIL {case['id']}: {case['label']}")
                    print(f"  {key}={out.get(key)!r} want {value!r}")
                    ok = False
            if ok:
                print(f"PASS {case['id']}: {case['label']}")
                passed += 1
        except Exception as exc:
            print(f"CRASH {case['id']}: {case['label']} — {exc}")
            traceback.print_exc()
    print(f"\n{passed}/{len(ATTACKER_CASES)} attacker cases passed")


if __name__ == "__main__":
    main()
