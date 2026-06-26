# QueueStorm Investigator

Support ticket investigator for the SUST CSE Carnival 2026 Codex Community Hackathon.

## Endpoints

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/health` | Returns `{"status":"ok"}` |
| `POST` | `/analyze-ticket` | Investigates a ticket against transaction history |

## Stack

- Python 3.12, FastAPI, Pydantic
- Rules engine for matching, evidence, and routing
- Optional Gemini via LangChain on the slow path (confidence &lt; 0.9 or ambiguous)
- Safety guardrails on all customer-facing text

See [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) for the system diagram.

## Local setup

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # optional: enable USE_GEMINI
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

```bash
curl http://localhost:8000/health

curl -X POST http://localhost:8000/analyze-ticket \
  -H "Content-Type: application/json" \
  -d @question/SUST_Preli_Sample_Cases.json
```

## Tests

```bash
PYTHONPATH=. python scripts/test_samples.py
PYTHONPATH=. python scripts/test_hidden_edge.py
PYTHONPATH=. python scripts/test_attacker.py
PYTHONPATH=. python scripts/test_robustness.py
PYTHONPATH=. python scripts/test_banglish.py
PYTHONPATH=. python scripts/test_extreme_cases.py
```

With Gemini enabled in `.env`:

```bash
PYTHONPATH=. python scripts/test_gemini_smoke.py
```

## Environment variables

| Variable | Description |
|----------|-------------|
| `USE_GEMINI` | `true` to enable slow-path routing |
| `GEMINI_API_KEY` | Google AI Studio key |
| `GEMINI_MODEL` | Default `gemini-2.0-flash` |
| `GEMINI_TIMEOUT_SECONDS` | Default `4.5` |

## Deploy on Render

`render.yaml` is included. Set `GEMINI_API_KEY` in the dashboard. Health check: `/health`.

## Sample output

`samples/sample_output_tkt001.json`
