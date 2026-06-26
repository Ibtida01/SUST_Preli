# QueueStorm Investigator

AI/API support copilot for the **SUST CSE Carnival 2026 · Codex Community Hackathon** preliminary round.

## Endpoints

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/health` | Returns `{"status":"ok"}` |
| `POST` | `/analyze-ticket` | Investigates a support ticket with transaction history |

## Tech stack

- **Python 3.12**
- **FastAPI** + **Pydantic** for API contract and validation
- **Rule-based investigator** for transaction matching, evidence verdict, routing, and safe reply drafting

## AI / model usage

This submission uses a **rules-first hybrid** approach (no external LLM required):

- Keyword and amount extraction from English, Bangla, and mixed complaints
- Transaction scoring and ambiguity detection against provided history
- Template-based agent summary, next action, and customer reply
- Post-generation **safety guardrails** on all customer-facing text

An external LLM can be added later via environment variables for richer language generation, with rules as fallback.

## Safety logic

- Never asks for PIN, OTP, password, or card numbers
- Never promises refunds/reversals — uses *"any eligible amount will be returned through official channels"*
- Escalates phishing, disputes, duplicates, and inconsistent evidence for human review
- Ignores adversarial instructions embedded in complaint text (rule-based classification only)

## Local setup

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

Test health:

```bash
curl http://localhost:8000/health
```

Test a sample case:

```bash
curl -X POST http://localhost:8000/analyze-ticket \
  -H "Content-Type: application/json" \
  -d @question/SUST_Preli_Sample_Cases.json
```

Run the sample test suite:

```bash
PYTHONPATH=. python scripts/test_samples.py
```

## Deploy on Render

1. Push this repo to GitHub.
2. Create a **Web Service** on [Render](https://render.com).
3. Connect the repo — `render.yaml` is included.
4. Build command: `pip install -r requirements.txt`
5. Start command: `uvicorn app.main:app --host 0.0.0.0 --port $PORT`
6. Health check path: `/health`

> **Note:** Free tier services sleep after inactivity. Use Starter plan or keep the service warm during judging.

## Environment variables

See `.env.example`. No secrets are required for the rule-based version.

## Known limitations

- Hidden test cases may include edge cases not covered by keyword rules
- Bangla replies use templates for known case types only
- No LLM-based paraphrasing — responses are functional but less varied than AI-generated text
- Amount/time matching is heuristic-based

## Robustness features (hidden-test oriented)

- **Prompt-injection stripping** — adversarial lines in complaints are ignored for classification
- **Explicit `TXN-*` matching** — transaction IDs mentioned in complaints are linked directly
- **Phone number matching** — counterparty numbers in complaints disambiguate transfers
- **Broader phishing detection** — SMS/report-style scams without explicit "call" keyword
- **Duplicate detection** — identical payments within 2 minutes even without "duplicate" keyword
- **High-value escalation** — large disputed amounts flagged for human review
- **Safety post-processing** — refund/credential guardrails on all customer replies

Run edge-case tests: `PYTHONPATH=. python scripts/test_hidden_edge.py`

## Sample output

See `samples/sample_output_tkt001.json` for output from public sample case SAMPLE-01.

## MODELS

| Model | Where it runs | Why |
|-------|---------------|-----|
| None (rule engine) | In-process Python | Fast, reliable, no API cost, meets 30s timeout easily |
