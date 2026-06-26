# QueueStorm Investigator — System Architecture

Use this diagram during the **~27 second architecture** segment of the demo video.

---

## High-level flow

```mermaid
flowchart TD
    A["POST /analyze-ticket"] --> B["FastAPI Gateway"]
    B --> C["Truncate complaint ≤ 2000 chars"]
    C --> D["Robustness pre-processor"]
    D --> E["Rules engine: classify + match TXNs"]

    E --> F{"Heuristic router<br/>confidence ≥ 0.9<br/>and not ambiguous?"}

    F -->|Yes — Fast path| G["Deterministic investigation"]
    F -->|No — Slow path| H["LangChain LCEL pipeline"]
    H --> I["Gemini Flash<br/>structured routing"]
    I --> J{"Success within 4.5s?"}
    J -->|No| G
    J -->|Yes| K["Merge case_type<br/>re-match if needed"]
    K --> G

    G --> L["Template replies<br/>agent_summary · next_action · customer_reply"]
    L --> M["Safety guardrails"]
    M --> N["JSON response"]

    style F fill:#fff3cd,stroke:#856404
    style H fill:#cce5ff,stroke:#0056b3
    style I fill:#cce5ff,stroke:#0056b3
    style M fill:#f8d7da,stroke:#dc3545
    style G fill:#d4edda,stroke:#28a745
```

---

## Layer responsibilities

```mermaid
flowchart LR
    subgraph Gateway["API layer"]
        API["FastAPI"]
    end

    subgraph Always["Always on"]
        R["Rules engine<br/>investigator.py"]
        S["Safety vault<br/>safety.py"]
    end

    subgraph Optional["Slow path only"]
        LC["LangChain agent<br/>agent.py"]
        GM["Gemini Flash"]
    end

    API --> R
    R --> LC
    LC --> GM
    GM --> R
    R --> S
    S --> API

    style Always fill:#d4edda,stroke:#28a745
    style Optional fill:#cce5ff,stroke:#0056b3
    style S fill:#f8d7da,stroke:#dc3545
```

---

## What each layer owns

| Layer | File(s) | Responsibility |
|-------|---------|----------------|
| **Gateway** | `main.py` | HTTP, validation, complaint length limit |
| **Pre-processor** | `robustness.py` | Injection stripping, phone/TXN extraction, `{}` escape |
| **Rules engine** | `investigator.py` | `case_type`, TXN match, `evidence_verdict`, department, templates |
| **Heuristic router** | `investigator.py` + `agent.py` | Fast path if confidence ≥ 0.9; else invoke Gemini |
| **LangChain LCEL** | `agent.py` | `prompt \| llm.with_structured_output()` — filter + route only |
| **Guardrails** | `safety.py` | No PIN/OTP requests, no refund promises, credential warnings |

---

## Vault pattern (safety)

```mermaid
flowchart LR
    LLM["Gemini output"] --> ENUM["case_type enum only"]
    ENUM --> RULES["Rules + templates"]
    RULES --> TEXT["customer_reply"]
    TEXT --> SAFE["safety.py"]
    SAFE --> OUT["Final response"]

    LLM -.->|never writes| TEXT

    style LLM fill:#cce5ff,stroke:#0056b3
    style SAFE fill:#f8d7da,stroke:#dc3545
```

> **LLM never authors the final customer reply.** It may suggest routing; templates and guardrails produce safe text.

---

## Sequence (slow path)

```mermaid
sequenceDiagram
    participant Client
    participant API as FastAPI
    participant Rules as Rules engine
    participant Router as Heuristic router
    participant LC as LangChain
    participant Gemini
    participant Safe as Safety guardrails

    Client->>API: POST /analyze-ticket
    API->>Rules: sanitize + classify + match
    Rules->>Router: MatchResult + confidence

    alt Fast path (confidence ≥ 0.9)
        Router->>Rules: use rules case_type
    else Slow path (ambiguous / low confidence)
        Router->>LC: await chain.ainvoke()
        LC->>Gemini: structured JSON request
        alt OK within 4.5s
            Gemini-->>LC: case_type + filtered_complaint
            LC-->>Rules: merge + re-match
        else Timeout / error
            LC-->>Rules: rules fallback
        end
    end

    Rules->>Safe: template customer_reply
    Safe-->>API: guarded text
    API-->>Client: 200 AnalyzeTicketResponse
```

---

## Presenter notes (~27 seconds)

1. **Complaint in** → gateway truncates and sanitizes.
2. **Rules engine** always runs first — matching, evidence, routing.
3. **Fast path** — clear cases, millisecond latency.
4. **Slow path** — ambiguous tickets go to **LangChain + Gemini** for semantic routing.
5. **Vault** — LLM does not write customer replies; **safety guardrails** always run last.
6. **Fallback** — if Gemini fails, rules-only response; no 500.

---

## Color key (for slides)

| Color | Meaning |
|-------|---------|
| Green | Rules engine / fast path |
| Blue | LangChain + Gemini slow path |
| Yellow | Routing decision |
| Red | Safety guardrails |
