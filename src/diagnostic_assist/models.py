from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

RetrievalSource = Literal["bm25", "semantic"]
MatchScope = Literal["equipment_type", "equipment_family"]


class HistoricalCase(BaseModel):
    """A closed historical case in its original form."""

    model_config = ConfigDict(
        extra="forbid",
        str_strip_whitespace=True,
    )

    case_id: str = Field(min_length=1)
    equipment_family: str = Field(min_length=1)
    equipment_type: str = Field(min_length=1)
    created_at: datetime
    language: str = Field(min_length=2)
    customer_description: str = Field(min_length=1)
    technician_notes: str | None = None
    parts_replaced: list[str] = Field(default_factory=list)
    resolution_text: str | None = None

    @field_validator("created_at")
    @classmethod
    def require_timezone(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("created_at must contain a timezone")
        return value

    @field_validator("technician_notes", "resolution_text", mode="before")
    @classmethod
    def blank_text_as_none(cls, value: object) -> object:
        if isinstance(value, str) and not value.strip():
            return None
        return value

    @field_validator("parts_replaced")
    @classmethod
    def clean_parts(cls, parts: list[str]) -> list[str]:
        return [part.strip() for part in parts if part.strip()]


class SearchHit(BaseModel):
    """One result returned by BM25 or semantic search."""

    case_id: str = Field(min_length=1)
    source: RetrievalSource
    rank: int = Field(ge=1)
    score: float


class EvidenceHit(BaseModel):
    """A historical case after retrieval results have been fused."""

    case: HistoricalCase
    rrf_score: float = Field(ge=0)
    source_ranks: dict[str, int] = Field(default_factory=dict)
    match_scope: MatchScope

    @field_validator("source_ranks")
    @classmethod
    def validate_source_ranks(cls, ranks: dict[str, int]) -> dict[str, int]:
        allowed_sources = {"bm25", "semantic"}

        if not set(ranks).issubset(allowed_sources):
            raise ValueError("source_ranks contains an unknown retrieval source")

        if any(rank < 1 for rank in ranks.values()):
            raise ValueError("source ranks must be greater than zero")

        return ranks


class EvidenceBundle(BaseModel):
    """The retrieval component's complete output."""

    query: str = Field(min_length=1)
    equipment_type: str = Field(min_length=1)
    equipment_family: str | None = None
    hits: list[EvidenceHit] = Field(default_factory=list)
    used_family_fallback: bool = False
    warnings: list[str] = Field(default_factory=list)
