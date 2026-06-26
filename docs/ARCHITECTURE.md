# QueueStorm Investigator — Architecture

## High-level flow

```mermaid
flowchart TD
    A["POST /analyze-ticket"] --> B["FastAPI Gateway"]
    B --> C["Truncate complaint ≤ 2000 chars"]
    C --> D["Pre-processor"]
    D --> E["Rules engine: classify + match TXNs"]

    E --> F{"Heuristic router<br/>confidence ≥ 0.9<br/>and not ambiguous?"}

    F -->|Yes — Fast path| G["Deterministic investigation"]
    F -->|No — Slow path| H["LangChain pipeline"]
    H --> I["Gemini Flash<br/>structured routing"]
    I --> J{"Success within 4.5s?"}
    J -->|No| G
    J -->|Yes| K["Merge case_type<br/>re-match if needed"]
    K --> G

    G --> L["Template replies"]
    L --> M["Safety guardrails"]
    M --> N["JSON response"]

    style F fill:#856404,stroke:#ffc107,color:#ffffff
    style H fill:#1a4480,stroke:#4a9eff,color:#ffffff
    style I fill:#1a4480,stroke:#4a9eff,color:#ffffff
    style M fill:#721c24,stroke:#f5a5b0,color:#ffffff
    style G fill:#155724,stroke:#6fcf97,color:#ffffff
```

## Layer responsibilities

```mermaid
flowchart LR
    subgraph Gateway["API layer"]
        API["FastAPI"]
    end

    subgraph Always["Always on"]
        R["Rules engine<br/>investigator.py"]
        S["Safety<br/>safety.py"]
    end

    subgraph Optional["Slow path only"]
        LC["LangChain<br/>agent.py"]
        GM["Gemini Flash"]
    end

    API --> R
    R --> LC
    LC --> GM
    GM --> R
    R --> S
    S --> API

    style Always fill:#155724,stroke:#6fcf97,color:#ffffff
    style Optional fill:#1a4480,stroke:#4a9eff,color:#ffffff
    style S fill:#721c24,stroke:#f5a5b0,color:#ffffff
```

| Layer | File(s) | Responsibility |
|-------|---------|----------------|
| Gateway | `main.py` | HTTP, validation, complaint length limit |
| Pre-processor | `robustness.py` | Injection stripping, phone/TXN extraction |
| Rules engine | `investigator.py` | Classification, TXN match, evidence, templates |
| Heuristic router | `investigator.py` + `agent.py` | Fast path at confidence ≥ 0.9; else Gemini |
| LangChain | `agent.py` | Structured `case_type` routing |
| Guardrails | `safety.py` | PIN/OTP/refund safety on all replies |

## Reply flow

```mermaid
flowchart LR
    LLM["Gemini output"] --> ENUM["case_type enum"]
    ENUM --> RULES["Rules + templates"]
    RULES --> TEXT["customer_reply"]
    TEXT --> SAFE["safety.py"]
    SAFE --> OUT["Final response"]

    LLM -.->|never writes| TEXT

    style LLM fill:#1a4480,stroke:#4a9eff,color:#ffffff
    style SAFE fill:#721c24,stroke:#f5a5b0,color:#ffffff
```

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
    else Slow path
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
