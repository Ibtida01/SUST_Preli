#!/usr/bin/env bash
set -euo pipefail

BASE_URL="${BASE_URL:-http://localhost:8000}"
SAMPLES="question/SUST_Preli_Sample_Cases.json"

green() { printf '\033[0;32m%s\033[0m\n' "$*"; }
red()   { printf '\033[0;31m%s\033[0m\n' "$*"; }
hr()    { printf '\n%s\n' "────────────────────────────────────────"; }

get_case() {
  .venv/bin/python -c "import json,sys; print(json.dumps(json.load(open('$SAMPLES'))['cases'][int(sys.argv[1])]['input']))" "$1"
}

get_case_field() {
  .venv/bin/python -c "import json,sys; c=json.load(open('$SAMPLES'))['cases'][int(sys.argv[1])]; print(c[sys.argv[2]])" "$1" "$2"
}

hr
echo "1) Health check"
curl -sS "$BASE_URL/health"
echo ""
test "$(curl -sS "$BASE_URL/health" | grep -c '"status":"ok"')" -eq 1 && green "PASS" || red "FAIL"

hr
echo "2) All 10 public sample cases"
for i in $(seq 0 9); do
  id=$(get_case_field "$i" id)
  label=$(get_case_field "$i" label)
  input=$(get_case "$i")
  code=$(curl -sS -o /tmp/qs_response.json -w "%{http_code}" \
    -X POST "$BASE_URL/analyze-ticket" \
    -H "Content-Type: application/json" \
    -d "$input")
  ticket=$(cat /tmp/qs_response.json | .venv/bin/python -c "import json,sys; print(json.load(sys.stdin).get('ticket_id','error'))")
  case_type=$(cat /tmp/qs_response.json | .venv/bin/python -c "import json,sys; print(json.load(sys.stdin).get('case_type','error'))")
  if [[ "$code" == "200" && "$ticket" != "null" && "$ticket" != "error" ]]; then
    green "PASS $id ($label) → HTTP $code, case_type=$case_type"
  else
    red "FAIL $id ($label) → HTTP $code"
    cat /tmp/qs_response.json
  fi
done

hr
echo "3) Malformed JSON → expect HTTP 400"
code=$(curl -sS -o /tmp/qs_response.json -w "%{http_code}" \
  -X POST "$BASE_URL/analyze-ticket" \
  -H "Content-Type: application/json" \
  -d '{bad json}')
echo "HTTP $code — $(cat /tmp/qs_response.json)"
[[ "$code" == "400" ]] && green "PASS" || red "FAIL (wanted 400)"

hr
echo "4) Missing required field (complaint) → expect HTTP 400"
code=$(curl -sS -o /tmp/qs_response.json -w "%{http_code}" \
  -X POST "$BASE_URL/analyze-ticket" \
  -H "Content-Type: application/json" \
  -d '{"ticket_id":"TKT-BAD"}')
echo "HTTP $code — $(cat /tmp/qs_response.json)"
[[ "$code" == "400" ]] && green "PASS" || red "FAIL (wanted 400)"

hr
echo "5) Empty complaint → expect HTTP 422"
code=$(curl -sS -o /tmp/qs_response.json -w "%{http_code}" \
  -X POST "$BASE_URL/analyze-ticket" \
  -H "Content-Type: application/json" \
  -d '{"ticket_id":"TKT-EMPTY","complaint":"   "}')
echo "HTTP $code — $(cat /tmp/qs_response.json)"
[[ "$code" == "422" ]] && green "PASS" || red "FAIL (wanted 422)"

hr
echo "6) Phishing case — customer_reply must NOT ask for OTP"
input=$(get_case 4)
curl -sS -X POST "$BASE_URL/analyze-ticket" \
  -H "Content-Type: application/json" \
  -d "$input" | .venv/bin/python -m json.tool
reply=$(curl -sS -X POST "$BASE_URL/analyze-ticket" -H "Content-Type: application/json" -d "$input" | .venv/bin/python -c "import json,sys; print(json.load(sys.stdin)['customer_reply'])")
if .venv/bin/python -c "
import re, sys
reply = sys.argv[1]
pat = re.compile(r'(?<!do not )(?<!never )\\b(?:share|provide|send|enter|give)\\b.{0,40}\\b(?:pin|otp|password)\\b', re.I)
sys.exit(0 if not pat.search(reply) else 1)
" "$reply"; then
  green "PASS — reply does not request credentials"
else
  red "FAIL — reply asks for credentials"
fi

hr
echo "7) Refund case — must NOT promise refund"
input=$(get_case 3)
reply=$(curl -sS -X POST "$BASE_URL/analyze-ticket" -H "Content-Type: application/json" -d "$input" | .venv/bin/python -c "import json,sys; print(json.load(sys.stdin)['customer_reply'])")
echo "$reply"
if echo "$reply" | grep -qiE 'we will refund|has been refunded|refund is approved'; then
  red "FAIL — unsafe refund promise"
else
  green "PASS — no unauthorized refund promise"
fi

hr
echo "8) Bangla case (SAMPLE-07)"
input=$(get_case 6)
curl -sS -X POST "$BASE_URL/analyze-ticket" \
  -H "Content-Type: application/json" \
  -d "$input" | .venv/bin/python -m json.tool

hr
echo "9) Pretty-print full response for SAMPLE-01 (wrong transfer)"
input=$(get_case 0)
curl -sS -X POST "$BASE_URL/analyze-ticket" \
  -H "Content-Type: application/json" \
  -d "$input" | .venv/bin/python -m json.tool

hr
green "Done. For schema validation run: PYTHONPATH=. python scripts/test_samples.py"
