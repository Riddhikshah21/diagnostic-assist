from collections import defaultdict
from dataclasses import dataclass
from itertools import product

from evaluate_retrieval import DATA_FILE, EVALUATION_CASES

from diagnostic_assist.loader import load_cases
from diagnostic_assist.retrieval import (
    KeywordIndex,
    SemanticIndex,
    SentenceTransformerEmbedder,
)

CROSS_LANGUAGE_TARGETS = {
    "C-48211": "C-48377",
    "C-48604": "C-48755",
    "C-48899": "C-49266",
    "C-49402": "C-49480",
}


@dataclass(frozen=True)
class RankedCandidate:
    case_id: str
    score: float


def weighted_rrf(
    keyword_hits,
    semantic_hits,
    candidate_depth: int,
    semantic_weight: float,
    rank_constant: int = 60,
) -> list[RankedCandidate]:
    scores: defaultdict[str, float] = defaultdict(float)

    for hit in keyword_hits[:candidate_depth]:
        scores[hit.case_id] += 1 / (rank_constant + hit.rank)

    for hit in semantic_hits[:candidate_depth]:
        scores[hit.case_id] += semantic_weight / (rank_constant + hit.rank)

    return sorted(
        (RankedCandidate(case_id=case_id, score=score) for case_id, score in scores.items()),
        key=lambda candidate: (
            -candidate.score,
            candidate.case_id,
        ),
    )


def main() -> None:
    cases = load_cases(DATA_FILE)
    cases_by_id = {case.case_id: case for case in cases}

    print("Loading multilingual embedding model...")
    embedder = SentenceTransformerEmbedder()

    keyword_index = KeywordIndex(cases)
    semantic_index = SemanticIndex(cases, embedder)

    prepared_results = {}

    for evaluation in EVALUATION_CASES:
        query_case = cases_by_id[evaluation.query_case_id]

        candidate_ids = {
            case.case_id
            for case in cases
            if (
                case.equipment_type == query_case.equipment_type
                and case.case_id != query_case.case_id
            )
        }

        keyword_hits = keyword_index.search(
            query=query_case.customer_description,
            candidate_ids=candidate_ids,
            limit=len(candidate_ids),
        )
        semantic_hits = semantic_index.search(
            query=query_case.customer_description,
            candidate_ids=candidate_ids,
            limit=len(candidate_ids),
        )

        prepared_results[evaluation.query_case_id] = (
            candidate_ids,
            keyword_hits,
            semantic_hits,
        )

        print()
        print("=" * 90)
        print(f"Semantic top five for {evaluation.query_case_id}")
        print(f"{'Rank':<7}{'Case':<10}{'Lang':<8}{'Expected':<11}{'Score':<10}Description")

        for hit in semantic_hits[:5]:
            case = cases_by_id[hit.case_id]
            expected = "yes" if hit.case_id in evaluation.relevant_case_ids else "no"

            print(
                f"{hit.rank:<7}"
                f"{hit.case_id:<10}"
                f"{case.language:<8}"
                f"{expected:<11}"
                f"{hit.score:<10.4f}"
                f"{case.customer_description}"
            )

    configurations = list(
        product(
            (3, 5, 10),
            (1.0, 2.0, 3.0),
        )
    )

    print()
    print("=" * 90)
    print("Fusion comparison")
    print(
        f"{'Depth':<8}"
        f"{'Semantic weight':<18}"
        f"{'Recall@5':<12}"
        f"{'Precision@5':<15}"
        f"{'Cross-lang hit':<16}"
        f"{'Cross-lang MRR':<15}"
    )

    for candidate_depth, semantic_weight in configurations:
        recalls: list[float] = []
        precisions: list[float] = []
        cross_language_hits: list[float] = []
        reciprocal_ranks: list[float] = []

        for evaluation in EVALUATION_CASES:
            (
                candidate_ids,
                keyword_hits,
                semantic_hits,
            ) = prepared_results[evaluation.query_case_id]

            fused = weighted_rrf(
                keyword_hits=keyword_hits,
                semantic_hits=semantic_hits,
                candidate_depth=candidate_depth,
                semantic_weight=semantic_weight,
            )

            top_five = [candidate.case_id for candidate in fused[:5]]

            relevant_found = set(top_five) & evaluation.relevant_case_ids

            recall = len(relevant_found) / len(evaluation.relevant_case_ids)
            denominator = min(5, len(candidate_ids))
            precision = len(relevant_found) / denominator

            target_id = CROSS_LANGUAGE_TARGETS[evaluation.query_case_id]

            if target_id in top_five:
                target_rank = top_five.index(target_id) + 1
                cross_language_hits.append(1.0)
                reciprocal_ranks.append(1 / target_rank)
            else:
                cross_language_hits.append(0.0)
                reciprocal_ranks.append(0.0)

            recalls.append(recall)
            precisions.append(precision)

        average_recall = sum(recalls) / len(recalls)
        average_precision = sum(precisions) / len(precisions)
        cross_language_hit_rate = sum(cross_language_hits) / len(cross_language_hits)
        cross_language_mrr = sum(reciprocal_ranks) / len(reciprocal_ranks)

        print(
            f"{candidate_depth:<8}"
            f"{semantic_weight:<18.1f}"
            f"{average_recall:<12.2f}"
            f"{average_precision:<15.2f}"
            f"{cross_language_hit_rate:<16.2f}"
            f"{cross_language_mrr:<15.2f}"
        )


if __name__ == "__main__":
    main()
