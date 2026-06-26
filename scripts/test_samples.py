#!/usr/bin/env python3
"""Quick local test runner against public sample cases."""

import json
from pathlib import Path

from app.investigator import analyze_ticket
from app.models import AnalyzeTicketRequest

SAMPLES = Path(__file__).resolve().parent.parent / "question" / "SUST_Preli_Sample_Cases.json"


def main() -> None:
    data = json.loads(SAMPLES.read_text())
    passed = 0
    total = len(data["cases"])

    for case in data["cases"]:
        request = AnalyzeTicketRequest.model_validate(case["input"])
        expected = case["expected_output"]
        actual = analyze_ticket(request).model_dump()

        checks = {
            "relevant_transaction_id": actual["relevant_transaction_id"] == expected["relevant_transaction_id"],
            "evidence_verdict": actual["evidence_verdict"] == expected["evidence_verdict"],
            "case_type": actual["case_type"] == expected["case_type"],
            "department": actual["department"] == expected["department"],
            "human_review_required": actual["human_review_required"] == expected["human_review_required"],
        }
        ok = all(checks.values())
        status = "PASS" if ok else "FAIL"
        print(f"{status} {case['id']} - {case['label']}")
        if not ok:
            for field, match in checks.items():
                if not match:
                    print(f"  {field}: got {actual[field]!r}, want {expected[field]!r}")
        else:
            passed += 1

    print(f"\n{passed}/{total} cases passed core field checks")


if __name__ == "__main__":
    main()
