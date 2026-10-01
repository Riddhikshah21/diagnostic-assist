# Diagnostic Assist

Diagnostic Assist is a conversational support tool for service dispatchers. It helps them understand a machine problem, find similar historical cases and prepare a more useful handoff for the technician.

This repository was created for a three-hour technical assignment. It is intentionally a focused prototype rather than a complete production system.

## Problem

When a machine breaks, the customer often describes the problem using short, unclear or multilingual text. The dispatcher must decide what information to give the technician, how urgent the visit is and which parts may be useful.

The company has approximately 100,000 closed service cases, but they do not contain a root-cause field or a consistent symptom taxonomy. Useful information is mainly stored in customer descriptions, technician notes and resolution text.

## Proposed approach

The proposed system uses conversational retrieval-augmented generation.

The dispatcher selects the equipment and enters the customer’s description. The system searches for similar historical cases using:

- BM25 keyword search for error codes, model names and technical terms;
- multilingual semantic search for descriptions with similar meaning;
- Reciprocal Rank Fusion to combine both result lists.

Search is performed against historical customer descriptions. Technician notes, resolutions and replaced parts are returned afterward as evidence of what happened in those cases.

An LLM could use this evidence to suggest possible causes and a useful follow-up question. Every suggestion would need to cite the historical cases that support it.

## Conversation flow

1. The dispatcher enters the equipment type and customer description.
2. The system returns relevant historical cases within the first three seconds.
3. It may suggest one short follow-up question when another answer could separate the possible causes.
4. The dispatcher records the answer or selects `Unknown`.
5. Retrieval runs again using the updated information.
6. The system prepares a handoff for the technician.
7. The technician confirms the real cause onsite.

The assistant supports the decision. It does not replace the technician’s diagnosis.

## Prototype scope

The implemented component focuses on hybrid retrieval and evidence assembly. It includes:

- loading and validating historical cases;
- BM25 retrieval;
- multilingual semantic retrieval;
- equipment-type preference;
- equipment-family fallback;
- Reciprocal Rank Fusion;
- structured evidence output;
- automated tests.

The user interface, production AWS services, LLM response generation and probability calibration are outside the implemented scope.

## Important design decisions

Historical cases remain unchanged. The prototype does not create permanent root-cause labels using an LLM.

Only information available before the technician’s visit is used for matching. Technician notes and resolution text are returned as outcome evidence, but they are not included in the searchable query text. This reduces the risk of leaking the final answer into retrieval.

A vector similarity score is not treated as a diagnostic probability. Reliable probabilities would require human-reviewed root causes or confirmed outcomes collected over time.

## Technology

The prototype uses:

- Python;
- Pydantic for data validation;
- `rank-bm25` for keyword retrieval;
- a multilingual sentence-transformer for semantic retrieval;
- pytest for automated tests.
- Reciprocal Rank Fusion, the below values came from a small exploratory evaluation.:
    candidate depth 5;
    BM25 weight 1.0;
    semantic weight 2.0;

The production design uses Amazon S3, OpenSearch, Bedrock, ECS Fargate, DynamoDB, EventBridge, FastAPI, React and TypeScript.

## Running locally

```bash
python3 -m venv .venv
source .venv/bin/activate

python -m pip install --upgrade pip
python -m pip install -e ".[dev]"

Copy the supplied sample data to:

```text
data/sample_cases.json
```

The first semantic search downloads the multilingual embedding model. This cold start is not representative of the production design, where historical embeddings would be created offline and the API would remain warm.

## Run a normal search

```bash
diagnostic-assist \
  --data data/sample_cases.json \
  --equipment-type CX-450 \
  --equipment-family "Air Compressor CX" \
  --query "Customer says the unit is completely dead" \
  --limit 5
```

## Run leave-one-out evaluation

When a historical case is used as a simulated new query, its own case ID must be excluded:

```bash
diagnostic-assist \
  --data data/sample_cases.json \
  --equipment-type CX-450 \
  --equipment-family "Air Compressor CX" \
  --query "Unit won't start at all. No lights on the control panel." \
  --exclude-case-id C-48211 \
  --limit 5
```

A genuine new case is not already present in the historical index, so it does not need an excluded case ID.

Run the tests with:

```bash
pytest
```

## Repository structure

```text
diagnostic-assist/
├── docs/
│   ├── design-note.md
│   ├── product-overview.md
├── src/diagnostic_assist/
├── tests/
├── data/
├── scripts/
│   ├── evaluate_retrieval.py
│   ├── tune_fusion.py
├── pyproject.toml
└── README.md
```

## Limitations

The sample contains only 22 cases and is not statistically representative. The prototype cannot produce calibrated diagnostic probabilities from this data.

Semantic retrieval quality depends on the selected embedding model, while historical notes may contain missing information, incorrect conclusions or unclear language. Any generated cause or part recommendation would therefore need visible supporting evidence and technician confirmation.

The detailed product flow and technical decisions are described in the `docs` directory.