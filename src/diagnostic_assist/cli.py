import argparse
from collections.abc import Sequence

from diagnostic_assist.loader import CaseLoadError, load_cases
from diagnostic_assist.retrieval import (
    HybridRetriever,
    SentenceTransformerEmbedder,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Search similar historical service cases.")
    parser.add_argument(
        "--data",
        required=True,
        help="Path to sample_cases.json",
    )
    parser.add_argument(
        "--query",
        required=True,
        help="Customer problem description",
    )
    parser.add_argument(
        "--equipment-type",
        required=True,
        help="Equipment type, for example CX-450",
    )
    parser.add_argument(
        "--equipment-family",
        help="Optional equipment family",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=5,
        help="Maximum number of results",
    )
    parser.add_argument(
        "--exclude-case-id",
        action="append",
        default=[],
        help=("Case ID to exclude from results. May be provided more than once."),
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    arguments = parser.parse_args(argv)

    try:
        cases = load_cases(arguments.data)
        embedder = SentenceTransformerEmbedder()
        retriever = HybridRetriever(cases, embedder)

        result = retriever.search(
            query=arguments.query,
            equipment_type=arguments.equipment_type,
            equipment_family=arguments.equipment_family,
            limit=arguments.limit,
            exclude_case_ids=set(arguments.exclude_case_id),
        )
    except (CaseLoadError, ValueError) as exc:
        parser.error(str(exc))

    print(result.model_dump_json(indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
