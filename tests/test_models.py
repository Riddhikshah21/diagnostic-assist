import pytest
from pydantic import ValidationError

from diagnostic_assist.models import (
    EvidenceBundle,
    EvidenceHit,
    HistoricalCase,
    SearchHit,
)


def make_case(**overrides: object) -> HistoricalCase:
    values = {
        "case_id": "C-48590",
        "equipment_family": "Air Compressor CX",
        "equipment_type": "CX-450",
        "created_at": "2026-01-27T09:41:00Z",
        "language": "en",
        "customer_description": "no crank, dead panel",
        "technician_notes": ("Ground strap was loose. Contactor tested OK."),
        "parts_replaced": [],
        "resolution_text": "Loose ground strap.",
    }
    values.update(overrides)
    return HistoricalCase.model_validate(values)


def test_valid_historical_case() -> None:
    case = make_case()

    assert case.case_id == "C-48590"
    assert case.created_at.tzinfo is not None


def test_missing_resolution_is_allowed() -> None:
    case = make_case(resolution_text=None)

    assert case.resolution_text is None


def test_blank_optional_text_becomes_none() -> None:
    case = make_case(technician_notes="   ")

    assert case.technician_notes is None


def test_parts_are_cleaned() -> None:
    case = make_case(parts_replaced=[" CONTACTOR-M1 ", "", "  "])

    assert case.parts_replaced == ["CONTACTOR-M1"]


def test_blank_customer_description_is_rejected() -> None:
    with pytest.raises(ValidationError):
        make_case(customer_description="   ")


def test_unexpected_fields_are_rejected() -> None:
    with pytest.raises(ValidationError):
        make_case(root_cause="Contactor failure")


def test_search_rank_must_be_positive() -> None:
    with pytest.raises(ValidationError):
        SearchHit(
            case_id="C-48590",
            source="bm25",
            rank=0,
            score=1.0,
        )


def test_evidence_preserves_negation() -> None:
    case = make_case()
    hit = EvidenceHit(
        case=case,
        rrf_score=0.02,
        source_ranks={"bm25": 1, "semantic": 2},
        match_scope="equipment_type",
    )

    result = EvidenceBundle(
        query="dead control panel",
        equipment_type="CX-450",
        equipment_family="Air Compressor CX",
        hits=[hit],
    )

    assert "Contactor tested OK" in result.hits[0].case.technician_notes
