#!/usr/bin/env python3
"""Banglish romanized complaint test cases."""

from __future__ import annotations

from app.investigator import analyze_ticket
from app.models import AnalyzeTicketRequest

BANGLISH_CASES = [
    {
        "id": "BNGL-01",
        "input": {
            "ticket_id": "BNGL-01",
            "complaint": "ami 5000 taka vul number e pathaisi, ekhon ferot chai. wrong number chilo.",
            "language": "mixed",
            "user_type": "customer",
            "transaction_history": [
                {
                    "transaction_id": "TXN-9101",
                    "timestamp": "2026-04-14T14:08:22Z",
                    "type": "transfer",
                    "amount": 5000,
                    "counterparty": "+8801719876543",
                    "status": "completed",
                }
            ],
        },
        "expect": {"case_type": "wrong_transfer", "department": "dispute_resolution"},
    },
    {
        "id": "BNGL-02",
        "input": {
            "ticket_id": "BNGL-02",
            "complaint": "ami +880 17 1234 5678 e 5k taka pathaisi but vul number chilo.",
            "language": "mixed",
            "user_type": "customer",
            "transaction_history": [
                {
                    "transaction_id": "TXN-2",
                    "timestamp": "2026-04-14T12:00:00Z",
                    "type": "transfer",
                    "amount": 5000,
                    "counterparty": "+8801712345678",
                    "status": "completed",
                }
            ],
        },
        "expect": {"case_type": "wrong_transfer", "relevant_transaction_id": "TXN-2"},
    },
    {
        "id": "BNGL-03",
        "input": {
            "ticket_id": "BNGL-03",
            "complaint": "amar 500 tk deduct hoise but failed dekhay, recharge hoy nai.",
            "language": "mixed",
            "user_type": "customer",
            "transaction_history": [
                {
                    "transaction_id": "TXN-9301",
                    "timestamp": "2026-04-14T16:00:00Z",
                    "type": "payment",
                    "amount": 500,
                    "counterparty": "MERCHANT-MOBILE-OP",
                    "status": "failed",
                }
            ],
        },
        "expect": {"case_type": "payment_failed", "department": "payments_ops"},
        "reply_must_not_contain": ["through official channels. through official"],
    },
    {
        "id": "BNGL-04",
        "input": {
            "ticket_id": "BNGL-04",
            "complaint": "ajke sokal e agent er kache 2000 taka kash in korechi kintu balance e ashe nai.",
            "language": "mixed",
            "user_type": "customer",
            "transaction_history": [
                {
                    "transaction_id": "TXN-9701",
                    "timestamp": "2026-04-14T09:30:00Z",
                    "type": "cash_in",
                    "amount": 2000,
                    "counterparty": "AGENT-318",
                    "status": "pending",
                }
            ],
        },
        "expect": {"case_type": "agent_cash_in_issue", "department": "agent_operations"},
    },
    {
        "id": "BNGL-05",
        "input": {
            "ticket_id": "BNGL-05",
            "complaint": "bill er 850 taka duibar katche, ekbar pay korechi only.",
            "language": "mixed",
            "user_type": "customer",
            "transaction_history": [
                {
                    "transaction_id": "TXN-10001",
                    "timestamp": "2026-04-14T08:15:30Z",
                    "type": "payment",
                    "amount": 850,
                    "counterparty": "BILLER-DESCO",
                    "status": "completed",
                },
                {
                    "transaction_id": "TXN-10002",
                    "timestamp": "2026-04-14T08:15:42Z",
                    "type": "payment",
                    "amount": 850,
                    "counterparty": "BILLER-DESCO",
                    "status": "completed",
                },
            ],
        },
        "expect": {"case_type": "duplicate_payment", "relevant_transaction_id": "TXN-10002"},
    },
    {
        "id": "BNGL-06",
        "input": {
            "ticket_id": "BNGL-06",
            "complaint": "keu phone kore bole otp pathao na hole account block hobe. eta ki sotti?",
            "language": "mixed",
            "user_type": "customer",
            "transaction_history": [],
        },
        "expect": {"case_type": "phishing_or_social_engineering", "department": "fraud_risk"},
    },
    {
        "id": "BNGL-07",
        "input": {
            "ticket_id": "BNGL-07",
            "complaint": "merchant ke 800 taka diyechi kintu product pochondo hoy nai, ferot chai.",
            "language": "mixed",
            "user_type": "customer",
            "transaction_history": [
                {
                    "transaction_id": "TXN-9401",
                    "timestamp": "2026-04-14T13:00:00Z",
                    "type": "payment",
                    "amount": 800,
                    "counterparty": "MERCHANT-7821",
                    "status": "completed",
                }
            ],
        },
        "expect": {"case_type": "refund_request", "department": "customer_support"},
    },
    {
        "id": "BNGL-08",
        "input": {
            "ticket_id": "BNGL-08",
            "complaint": "amar taka niye kisu somossa hocche, please check korben.",
            "language": "mixed",
            "user_type": "customer",
            "transaction_history": [
                {
                    "transaction_id": "TXN-9601",
                    "timestamp": "2026-04-13T10:00:00Z",
                    "type": "cash_in",
                    "amount": 3000,
                    "counterparty": "AGENT-220",
                    "status": "completed",
                }
            ],
        },
        "expect": {"case_type": "other", "evidence_verdict": "insufficient_data"},
    },
]


def main() -> None:
    passed = 0
    for case in BANGLISH_CASES:
        req = AnalyzeTicketRequest.model_validate(case["input"])
        out = analyze_ticket(req).model_dump()
        ok = True
        for key, value in case["expect"].items():
            if out.get(key) != value:
                print(f"FAIL {case['id']}: {key}={out.get(key)!r} want {value!r}")
                ok = False
        for bad in case.get("reply_must_not_contain", []):
            if bad in out.get("customer_reply", "").lower():
                print(f"FAIL {case['id']}: bad phrase in reply: {bad!r}")
                ok = False
        if ok:
            print(f"PASS {case['id']}")
            passed += 1
    print(f"\n{passed}/{len(BANGLISH_CASES)} Banglish cases passed")


if __name__ == "__main__":
    main()
