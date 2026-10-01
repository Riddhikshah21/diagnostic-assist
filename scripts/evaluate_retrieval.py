from dataclasses import dataclass
from pathlib import Path

from diagnostic_assist.loader import load_cases
from diagnostic_assist.retrieval import (
    KeywordIndex,
    SemanticIndex,
    SentenceTransformerEmbedder,
    reciprocal_rank_fusion,
)

DATA_FILE = Path(__file__).parents[1] / "data" / "sample_cases.json"


@dataclass(frozen=True)
class EvaluationCase:
    query_case_id: str
    relevant_case_ids: frozenset[str]


EVALUATION_CASES = [
    EvaluationCase(
        query_case_id="C-48211",
        relevant_case_ids=frozenset(
            {
                "C-48377",  # German: will not start, blank display
                "C-48590",  # English: no crank, dead panel
                "C-49040",  # English: dead, will not power up
            }
        ),
    ),
    EvaluationCase(
        query_case_id="C-48604",
        relevant_case_ids=frozenset(
            {
                "C-48755",  # French: hydraulic boom-cylinder leak
                "C-48801",  # Abbreviated English: boom-cylinder leak
            }
        ),
    ),
    EvaluationCase(
        query_case_id="C-48899",
        relevant_case_ids=frozenset(
            {
                "C-49266",  # Italian: overheating, noise and E207
                "C-48934",  # English: overheating under load
                "C-49203",  # English: rattling under load
            }
        ),
    ),
    EvaluationCase(
        query_case_id="C-49402",
        relevant_case_ids=frozenset(
            {
                "C-49480",  # German: cylinder knocking under load
                "C-49203",  # English: rattling under high load
            }
        ),
    ),
]


def recall_at_five(
    retrieved_ids: list[str],
    relevant_ids: frozenset[str],
) -> float:
    found = set(retrieved_ids[:5]) & relevant_ids
    return len(found) / len(relevant_ids)


def rank_or_dash(
    ranks: dict[str, int],
    case_id: str,
) -> str:
    rank = ranks.get(case_id)
    return str(rank) if rank is not None else "-"


def score_or_dash(
    scores: dict[str, float],
    case_id: str,
) -> str:
    score = scores.get(case_id)
    return f"{score:.4f}" if score is not None else "-"


def main() -> None:
    cases = load_cases(DATA_FILE)
    cases_by_id = {case.case_id: case for case in cases}

    print("Loading multilingual embedding model...")
    embedder = SentenceTransformerEmbedder()

    keyword_index = KeywordIndex(cases)
    semantic_index = SemanticIndex(cases, embedder)

    semantic_recalls: list[float] = []
    fused_recalls: list[float] = []

    for evaluation in EVALUATION_CASES:
        query_case = cases_by_id[evaluation.query_case_id]

        # Leave-one-out evaluation: never retrieve the query case itself.
        candidate_ids = {
            case.case_id
            for case in cases
            if (
                case.equipment_type == query_case.equipment_type
                and case.case_id != query_case.case_id
            )
        }

        result_limit = len(candidate_ids)

        keyword_hits = keyword_index.search(
            query=query_case.customer_description,
            candidate_ids=candidate_ids,
            limit=result_limit,
        )
        semantic_hits = semantic_index.search(
            query=query_case.customer_description,
            candidate_ids=candidate_ids,
            limit=result_limit,
        )
        fused_hits = reciprocal_rank_fusion([keyword_hits, semantic_hits])

        keyword_ranks = {hit.case_id: hit.rank for hit in keyword_hits}
        keyword_scores = {hit.case_id: hit.score for hit in keyword_hits}
        semantic_ranks = {hit.case_id: hit.rank for hit in semantic_hits}
        semantic_scores = {hit.case_id: hit.score for hit in semantic_hits}
        fused_ranks = {hit.case_id: rank for rank, hit in enumerate(fused_hits, start=1)}
        fused_scores = {hit.case_id: hit.rrf_score for hit in fused_hits}

        semantic_top_five = [hit.case_id for hit in semantic_hits[:5]]
        fused_top_five = [hit.case_id for hit in fused_hits[:5]]

        semantic_recall = recall_at_five(
            semantic_top_five,
            evaluation.relevant_case_ids,
        )
        fused_recall = recall_at_five(
            fused_top_five,
            evaluation.relevant_case_ids,
        )

        semantic_recalls.append(semantic_recall)
        fused_recalls.append(fused_recall)

        print()
        print("=" * 88)
        print(f"Query case: {query_case.case_id}")
        print(f"Language:   {query_case.language}")
        print(f"Equipment:  {query_case.equipment_type}")
        print(f"Query:      {query_case.customer_description}")
        print()
        print(f"Semantic Recall@5: {semantic_recall:.2f} | Fused Recall@5: {fused_recall:.2f}")

        print()
        print("Expected relevant cases")
        print(
            f"{'Case':<10}"
            f"{'Lang':<8}"
            f"{'BM25 rank':<12}"
            f"{'BM25 score':<13}"
            f"{'Sem rank':<11}"
            f"{'Sem score':<12}"
            f"{'RRF rank':<10}"
            f"{'RRF score':<10}"
        )

        for case_id in sorted(evaluation.relevant_case_ids):
            case = cases_by_id[case_id]

            print(
                f"{case_id:<10}"
                f"{case.language:<8}"
                f"{rank_or_dash(keyword_ranks, case_id):<12}"
                f"{score_or_dash(keyword_scores, case_id):<13}"
                f"{rank_or_dash(semantic_ranks, case_id):<11}"
                f"{score_or_dash(semantic_scores, case_id):<12}"
                f"{rank_or_dash(fused_ranks, case_id):<10}"
                f"{score_or_dash(fused_scores, case_id):<10}"
            )

        print()
        print("Current fused top five")
        print(f"{'Rank':<7}{'Case':<10}{'Lang':<8}{'Expected':<11}{'RRF score':<12}Description")

        for rank, hit in enumerate(fused_hits[:5], start=1):
            case = cases_by_id[hit.case_id]
            expected = "yes" if hit.case_id in evaluation.relevant_case_ids else "no"

            print(
                f"{rank:<7}"
                f"{hit.case_id:<10}"
                f"{case.language:<8}"
                f"{expected:<11}"
                f"{hit.rrf_score:<12.4f}"
                f"{case.customer_description}"
            )

    average_semantic_recall = sum(semantic_recalls) / len(semantic_recalls)
    average_fused_recall = sum(fused_recalls) / len(fused_recalls)

    print()
    print("=" * 88)
    print("Summary")
    print(f"Queries evaluated:        {len(EVALUATION_CASES)}")
    print(f"Average semantic Recall@5: {average_semantic_recall:.2f}")
    print(f"Average fused Recall@5:    {average_fused_recall:.2f}")


if __name__ == "__main__":
    main()
