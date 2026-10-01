# Diagnostic Assist Technical Design

This design keeps the first version small enough to build and evaluate. It uses a conversational RAG pipeline with an offline ingestion path and an online request path.

## Architecture and pipeline

The offline path prepares closed historical cases for retrieval. It validates each record, preserves the original fields, creates a multilingual embedding for the customer description and writes the searchable record to OpenSearch.

The online path starts when the dispatcher enters an equipment type and problem description. BM25 and multilingual vector search run in parallel. Reciprocal Rank Fusion combines their results into a ranked evidence bundle.

The first useful evidence should appear within three seconds at p95. Cause grouping, follow-up generation and a longer explanation can arrive afterward.

| Path | Flow |
|---|---|
| Offline | Closed cases → validate → embed customer description → index |
| Online | Dispatcher query → hybrid retrieval → rank evidence → cause summary or follow-up |

I would begin with a modular application rather than separate microservices. The current data volume does not justify the additional deployment and operational work.

## Data handling

I would store the unchanged source cases in versioned S3 storage and create a separate record for search.

The customer description was available before the technician arrived. Technician notes, resolution text and replaced parts were created after the diagnosis. New descriptions should therefore be matched against historical customer descriptions. The remaining fields are returned only as evidence after retrieval.

This avoids leaking the historical answer into the matching process.

A searchable record would look like this:

```json
{
  "case_id": "C-48590",
  "equipment_family": "Air Compressor CX",
  "equipment_type": "CX-450",
  "created_at": "2026-01-27T09:41:00Z",
  "language": "en",
  "customer_description": "no crank, dead panel",
  "customer_description_vector": [],
  "technician_notes": "Ground strap at frame was loose...",
  "resolution_text": "Loose ground strap...",
  "parts_replaced": [],
  "pipeline_version": "1"
}
```

The source data has no root-cause field or symptom taxonomy. I would not silently add permanent LLM-generated labels in the prototype. Historical outcomes remain unchanged.

Any cause generated later must cite the exact case and text that supports it.

## Retrieval algorithms

I would use BM25 for exact error codes, part numbers, model names and technical terms. Semantic embeddings may understand meaning, but they can miss short or rare codes.

For semantic retrieval, I would use Cohere Embed Multilingual through Amazon Bedrock. It places descriptions from supported languages in a shared vector space and avoids translating every case into English. Translation would add cost and may change the meaning of technical terms.

OpenSearch would store the text, metadata and vectors. Vector search would use HNSW approximate nearest neighbours. Exact vector search may work for 100,000 records, but HNSW provides more predictable latency as the index grows. Its cost is that approximate search can miss a relevant neighbour.

For each request, I would:

1. prefer cases from the same equipment type;
2. run BM25 and vector search in parallel;
3. collect the leading candidates from both searches;
4. combine them using Reciprocal Rank Fusion;
5. return the strongest cases with their original evidence.

Reciprocal Rank Fusion uses rank positions rather than comparing BM25 and vector scores directly. This keeps the first version simple because those scores have different meanings and scales.

If an equipment type has too little history, retrieval expands to its equipment family. The interface clearly marks this fallback because family-level evidence may be less specific.

## Causes and probability estimates

A retrieval score is not the probability that a cause is correct.

After retrieval, a constrained LLM may group the raw historical outcomes into temporary candidate causes. Each candidate must contain cited case IDs and exact supporting text. These causes are created only for the current request and are not written back to the historical records.

The backend can calculate an evidence-share estimate by adding the retrieval weights of the cases supporting each candidate and normalizing them across the candidates. Cases with missing resolutions, administrative closures or unclear outcomes should not contribute.

The interface should also show the supporting case count. An estimate based on three cases is weaker than the same estimate based on three hundred cases.

This is not a calibrated diagnostic probability. I would validate it against a human-reviewed set before displaying it as a percentage in production. A trained probability model becomes reasonable only after reliable confirmed outcomes are available.

## Follow-up questions

The conversation state contains the equipment, reported symptoms, error codes, previous answers and unknown information.

The LLM receives this state and the retrieved evidence. It returns structured JSON containing:

- possible causes;
- cited case IDs;
- exact supporting text;
- one optional follow-up question.

The backend rejects case IDs or supporting text that do not exist in the retrieved evidence.

A follow-up should only be asked when its answer can separate the current possibilities. `Unknown` is always valid and should not change the evidence. Questions requiring tools, measurements, technical knowledge or unsafe actions are left for the technician.

Generated questions may still be inconsistent. A later version could use a reviewed question catalogue for common equipment and symptoms.

## Initial load and daily processing

The initial 100,000 cases are small enough for a batch process.

A Python job running on ECS Fargate would:

1. read the source records from S3 in batches;
2. validate them using Pydantic;
3. preserve the original outcome fields;
4. request multilingual embeddings in batches;
5. write processed records to S3;
6. index the records in OpenSearch.

The process is idempotent. `case_id` and `pipeline_version` identify an indexed record, so retrying a batch updates the record instead of creating a duplicate.

Progress is checkpointed after each batch. Invalid or repeatedly failing records are written to a separate S3 prefix for review without stopping the complete import.

For approximately 500 new closed cases per day, EventBridge Scheduler starts the same incremental job. A streaming architecture is unnecessary at this volume.

If the embedding model or indexing logic changes, I would build and validate a new OpenSearch index and then switch an alias. This avoids partially updating the live index.

## Three-second response

The three-second requirement applies to the first useful output, not necessarily the complete generated diagnosis.

To meet it:

- historical embeddings are calculated offline;
- the API service remains warm on ECS Fargate;
- BM25 and vector search run concurrently;
- retrieval returns only a small candidate set;
- RRF and evidence assembly happen in the backend;
- slower LLM output is fetched or streamed separately.

The UI can first show the matching historical evidence and then add possible causes and a follow-up question.

I would measure p50 and p95 latency separately for query embedding, BM25, vector search, fusion and generation. Any latency budget used before testing is a target, not a measured result.

## AWS and application stack

- **S3:** immutable raw cases, processed records and rejected records.
- **OpenSearch Service:** BM25, HNSW vector search, metadata filters and hybrid retrieval.
- **Amazon Bedrock:** multilingual embeddings and the LLM, both behind provider interfaces.
- **Python, FastAPI, Pydantic, boto3 and opensearch-py:** API and ingestion code.
- **ECS Fargate:** continuously available API and scheduled batch jobs.
- **DynamoDB:** conversation state and user feedback.
- **EventBridge Scheduler:** incremental ingestion.
- **React and TypeScript:** dispatcher interface.
- **CloudWatch and OpenTelemetry:** logs, traces, latency, index lag and cost metrics.
- **AWS CDK or Terraform:** repeatable infrastructure.

OpenSearch keeps lexical and vector retrieval in one service, but its fixed cost may be high for this corpus size. PostgreSQL with `pgvector` would be a cheaper alternative if retrieval remains simple.

Bedrock reduces model-hosting work but introduces provider cost and dependence. Keeping model access behind an interface makes future replacement easier.

## Failure modes

| Failure | Detection or control |
|---|---|
| Missing or invalid fields | Pydantic validation and rejected-record counts |
| Weak multilingual retrieval | Recall@k reported separately by language |
| Exact codes are missed | Dedicated keyword-retrieval tests |
| Negation is misunderstood | Tests containing phrases such as “contactor tested OK” |
| Irrelevant evidence is returned | Human relevance judgements and nDCG or Recall@k |
| Unsupported cause is generated | Case-ID and exact-text validation |
| Records are missing or duplicated | Source/index counts, version checks and indexing lag |
| Rare equipment gives poor results | Metrics by equipment volume and visible family fallback |
| Requests become slow or expensive | p50/p95 latency and cost per conversation |

When the evidence is weak, the system should say that an onsite diagnosis is required. A confident unsupported answer is the more serious failure.

## Key trade-offs

| Decision | Cost |
|---|---|
| Keep historical outcomes unlabelled | Avoids permanent synthetic errors, but requires query-time interpretation |
| Use RRF without a reranker | Faster and easier to inspect, but may reduce ranking precision |
| Use HNSW | More predictable latency, but approximate search may miss a case |
| Fall back to equipment family | Improves coverage, but the evidence is less model-specific |
| Use scheduled ingestion | Simple at 500 cases per day, but updates are not immediate |
| Return evidence before generation | Meets the latency goal, but the complete response arrives in stages |

## AI suggestions I did not follow

AI suggested creating permanent root-cause labels for all historical cases. I did not use this approach because the source data has no ground truth. A silently incorrect label would become part of future retrieval and probability calculations.

AI also suggested using a cross-encoder reranker immediately. I kept BM25, semantic search and RRF for the prototype because they are easier to implement, inspect and test within the timebox. A reranker remains a possible later improvement.

## Component selected for implementation

I would implement hybrid retrieval and evidence assembly.

If retrieval does not find relevant cases across languages, exact error codes and uneven equipment volumes, every downstream cause or follow-up will be unreliable. The component is also small enough to test honestly against the supplied sample.

The prototype will implement data validation, BM25, semantic retrieval, equipment matching, family fallback, RRF and structured evidence output. Cause synthesis, probability calibration, the production embedding service and the user interface remain explicit downstream interfaces.