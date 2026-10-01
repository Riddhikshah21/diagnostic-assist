from collections.abc import Sequence
from pathlib import Path

import numpy as np

from diagnostic_assist.loader import load_cases
from diagnostic_assist.models import SearchHit
from diagnostic_assist.retrieval import (
    HybridRetriever,
    KeywordIndex,
    reciprocal_rank_fusion,
    tokenize,
)

DATA_FILE = Path(__file__).parents[1] / "data" / "sample_cases.json"


class ControlledEmbedder:
    """Small deterministic test replacement for the real model."""

    def encode(self, texts: Sequence[str]) -> np.ndarray:
        return np.asarray(
            [self._vector(text) for text in texts],
            dtype=np.float32,
        )

    @staticmethod
    def _vector(text: str) -> list[float]:
        value = text.casefold()
        vector = [0.0, 0.0, 0.0, 0.0]

        start_terms = (
            "start",
            "panel",
            "display",
            "crank",
            "power up",
            "maschine startet",
            "anzeige",
        )
        battery_terms = ("battery", "batterie")
        heat_terms = (
            "overheat",
            "surriscalda",
            "e-207",
            "e207",
            "rattl",
            "rumore metallico",
        )
        leak_terms = (
            "leak",
            "fuite",
            "drip",
            "leckt",
            "spraying",
        )

        if any(term in value for term in start_terms):
            vector[0] = 1.0

        if any(term in value for term in battery_terms):
            vector[1] = 1.0

        if any(term in value for term in heat_terms):
            vector[2] = 1.0

        if any(term in value for term in leak_terms):
            vector[3] = 1.0

        if vector == [0.0, 0.0, 0.0, 0.0]:
            vector[3] = 0.1

        return vector


def test_loads_all_sample_cases() -> None:
    cases = load_cases(DATA_FILE)

    assert len(cases) == 22
    assert len({case.case_id for case in cases}) == 22


def test_tokenizer_preserves_and_normalizes_error_code() -> None:
    tokens = tokenize("Panel shows E-207.")

    assert "e-207" in tokens
    assert "e207" in tokens


def test_bm25_finds_both_error_code_formats() -> None:
    cases = load_cases(DATA_FILE)
    index = KeywordIndex(cases)

    results = index.search("E-207", limit=5)
    case_ids = {result.case_id for result in results}

    assert "C-48899" in case_ids
    assert "C-49266" in case_ids


def test_keyword_search_does_not_use_resolution_text() -> None:
    cases = load_cases(DATA_FILE)
    index = KeywordIndex(cases)

    results = index.search(
        "retorqued treated corrosion",
        limit=5,
    )

    assert results == []


def test_query_case_can_be_excluded() -> None:
    cases = load_cases(DATA_FILE)
    retriever = HybridRetriever(
        cases,
        ControlledEmbedder(),
    )

    result = retriever.search(
        query=("Unit won't start at all. No lights on the control panel."),
        equipment_type="CX-450",
        equipment_family="Air Compressor CX",
        limit=5,
        exclude_case_ids={"C-48211"},
    )

    returned_ids = {hit.case.case_id for hit in result.hits}

    assert "C-48211" not in returned_ids

def test_semantic_weight_changes_fusion_order() -> None:
    keyword = [
        SearchHit(
            case_id="keyword-only",
            source="bm25",
            rank=1,
            score=4.0,
        )
    ]
    semantic = [
        SearchHit(
            case_id="semantic-only",
            source="semantic",
            rank=1,
            score=0.8,
        )
    ]

    results = reciprocal_rank_fusion(
        [keyword, semantic],
        source_weights={
            "bm25": 1.0,
            "semantic": 2.0,
        },
    )

    assert results[0].case_id == "semantic-only"
    
def test_rrf_is_deterministic() -> None:
    keyword = [
        SearchHit(
            case_id="A",
            source="bm25",
            rank=1,
            score=5.0,
        ),
        SearchHit(
            case_id="B",
            source="bm25",
            rank=2,
            score=4.0,
        ),
    ]
    semantic = [
        SearchHit(
            case_id="B",
            source="semantic",
            rank=1,
            score=0.9,
        ),
        SearchHit(
            case_id="A",
            source="semantic",
            rank=2,
            score=0.8,
        ),
    ]

    first = reciprocal_rank_fusion([keyword, semantic])
    second = reciprocal_rank_fusion([keyword, semantic])

    assert first == second
    assert [result.case_id for result in first] == ["A", "B"]


def test_hybrid_search_returns_cross_language_case() -> None:
    cases = load_cases(DATA_FILE)
    retriever = HybridRetriever(cases, ControlledEmbedder())

    result = retriever.search(
        query="Machine will not start and the display is blank",
        equipment_type="CX-450",
        equipment_family="Air Compressor CX",
        limit=5,
    )

    case_ids = {hit.case.case_id for hit in result.hits}

    assert "C-48377" in case_ids


def test_original_negation_is_preserved() -> None:
    cases = load_cases(DATA_FILE)
    retriever = HybridRetriever(cases, ControlledEmbedder())

    result = retriever.search(
        query="no crank dead panel",
        equipment_type="CX-450",
        equipment_family="Air Compressor CX",
        limit=5,
    )

    matching_hit = next(hit for hit in result.hits if hit.case.case_id == "C-48590")

    assert matching_hit.case.technician_notes is not None
    assert "Contactor tested OK" in matching_hit.case.technician_notes


def test_family_fallback_is_visible() -> None:
    cases = load_cases(DATA_FILE)
    retriever = HybridRetriever(cases, ControlledEmbedder())

    result = retriever.search(
        query="machine overheats with E207",
        equipment_type="CX-999",
        equipment_family="Air Compressor CX",
        limit=3,
    )

    assert result.used_family_fallback is True
    assert result.warnings
    assert all(hit.match_scope == "equipment_family" for hit in result.hits)
