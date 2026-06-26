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

**Hybrid architecture: rules-first + Gemini 1.5 Flash (LangChain LCEL slow path)**

| Layer | Role |
|-------|------|
| **Rules engine** (`investigator.py`) | Always runs: sanitization, TXN matching, evidence verdict, routing, templates |
| **Heuristic router** | Fast path when match confidence ≥ 0.9 and not ambiguous |
| **LangChain agent** (`agent.py`) | Slow path: Gemini classifies `case_type` + filters complaint via structured output |
| **Guardrails** (`safety.py`) | Always post-processes customer-facing text (vault pattern — LLM never authors final reply) |

If `USE_GEMINI=false`, Gemini errors, or timeout (>4.5s) → rules-only fallback. All unit tests run with Gemini disabled.

### Enable Gemini locally

```bash
cp .env.example .env
# Edit .env:
# USE_GEMINI=true
# GEMINI_API_KEY=your_google_ai_studio_key
# GEMINI_MODEL=gemini-2.0-flash

pip install -r requirements.txt
uvicorn app.main:app --reload
```

Smoke test (requires API key):

```bash
PYTHONPATH=. python scripts/test_gemini_smoke.py
```

### Render deployment

Set in Render dashboard → Environment:

| Variable | Value |
|----------|--------|
| `USE_GEMINI` | `true` |
| `GEMINI_API_KEY` | secret (Google AI Studio) |
| `GEMINI_MODEL` | `gemini-1.5-flash` |
| `GEMINI_TIMEOUT_SECONDS` | `4.5` |

### Security hardening

- Complaints truncated to 2000 chars at the API gateway (token exhaustion defense)
- `{}` stripped before LangChain prompt formatting (template breakout defense)
- Gemini output limited to structured routing fields — customer replies from deterministic templates only

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

- **Prompt-injection stripping** — adversarial clauses removed in-place (same-line safe); empty result → safe vague handling
- **Explicit `TXN-*` matching** — transaction IDs mentioned in complaints are linked directly
- **Phone number matching** — supports `0171-234-5678` and spaced formats
- **Timezone-safe timestamps** — mixed `Z` / naive ISO datetimes won't crash duplicate detection
- **Broader phishing detection** — SMS/report-style scams without explicit "call" keyword
- **Duplicate detection** — identical payments within 2 minutes; picks latest in a chain
- **Expanded payment-failed keywords** — bill, recharge, "didn't go through", etc.
- **Hardened safety patterns** — catches `we'll refund`, `was refunded`, suspicious third-party contact phrases
- **High-value escalation** — large disputed amounts flagged for human review

Run edge-case tests: `PYTHONPATH=. python scripts/test_hidden_edge.py`

## Sample output

See `samples/sample_output_tkt001.json` for output from public sample case SAMPLE-01.

## MODELS

| Model | Where | Role |
|-------|--------|------|
| **Rules engine** | In-process Python | Investigation, matching, evidence (always) |
| **Gemini 2.0 Flash** | Google AI via LangChain | Slow-path filter + `case_type` routing (`gemini-1.5-flash` unavailable on many new API keys) |
