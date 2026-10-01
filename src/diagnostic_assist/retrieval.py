import re
from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Protocol

import numpy as np
from rank_bm25 import BM25Okapi

from diagnostic_assist.models import (
    EvidenceBundle,
    EvidenceHit,
    HistoricalCase,
    SearchHit,
)

TOKEN_PATTERN = re.compile(
    r"[^\W_]+(?:[-./][^\W_]+)*",
    flags=re.UNICODE,
)


def tokenize(text: str) -> list[str]:
    """Tokenize normal text while preserving technical codes."""

    tokens: list[str] = []

    for match in TOKEN_PATTERN.finditer(text.casefold()):
        token = match.group()
        tokens.append(token)

        compact = re.sub(r"[-./]", "", token)

        has_letter = any(character.isalpha() for character in compact)
        has_number = any(character.isdigit() for character in compact)

        if compact != token and has_letter and has_number:
            tokens.append(compact)

    return tokens


class Embedder(Protocol):
    """Interface shared by local and production embedding providers."""

    def encode(self, texts: Sequence[str]) -> np.ndarray:
        """Return one vector for each input text."""


class SentenceTransformerEmbedder:
    """Local multilingual embedding provider used by the prototype."""

    def __init__(
        self,
        model_name: str = ("sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"),
    ) -> None:
        self.model_name = model_name
        self._model = None

    def encode(self, texts: Sequence[str]) -> np.ndarray:
        if self._model is None:
            from sentence_transformers import SentenceTransformer

            self._model = SentenceTransformer(self.model_name)

        vectors = self._model.encode(
            list(texts),
            convert_to_numpy=True,
            normalize_embeddings=True,
            show_progress_bar=False,
        )
        return np.asarray(vectors, dtype=np.float32)


def normalize_rows(vectors: np.ndarray) -> np.ndarray:
    matrix = np.atleast_2d(np.asarray(vectors, dtype=np.float32))

    norms = np.linalg.norm(matrix, axis=1, keepdims=True)
    safe_norms = np.where(norms == 0, 1.0, norms)

    return matrix / safe_norms


class KeywordIndex:
    """BM25 index over customer descriptions only."""

    def __init__(self, cases: Sequence[HistoricalCase]) -> None:
        self._case_ids = [case.case_id for case in cases]
        corpus = [tokenize(case.customer_description) for case in cases]

        if not corpus:
            raise ValueError("KeywordIndex requires at least one case")

        self._index = BM25Okapi(corpus)

    def search(
        self,
        query: str,
        candidate_ids: set[str] | None = None,
        limit: int = 20,
    ) -> list[SearchHit]:
        query_tokens = tokenize(query)

        if not query_tokens or limit < 1:
            return []

        scores = self._index.get_scores(query_tokens)
        candidates: list[tuple[str, float]] = []

        for case_id, score in zip(
            self._case_ids,
            scores,
            strict=True,
        ):
            if candidate_ids is not None and case_id not in candidate_ids:
                continue

            numeric_score = float(score)

            # Zero means that none of the query terms matched.
            if numeric_score <= 0:
                continue

            candidates.append((case_id, numeric_score))

        candidates.sort(key=lambda item: (-item[1], item[0]))

        return [
            SearchHit(
                case_id=case_id,
                source="bm25",
                rank=rank,
                score=score,
            )
            for rank, (case_id, score) in enumerate(
                candidates[:limit],
                start=1,
            )
        ]


class SemanticIndex:
    """In-memory cosine-similarity index used by the prototype."""

    def __init__(
        self,
        cases: Sequence[HistoricalCase],
        embedder: Embedder,
    ) -> None:
        if not cases:
            raise ValueError("SemanticIndex requires at least one case")

        self._case_ids = [case.case_id for case in cases]
        self._embedder = embedder

        descriptions = [case.customer_description for case in cases]
        vectors = embedder.encode(descriptions)

        if len(vectors) != len(cases):
            raise ValueError("The embedder returned the wrong number of vectors")

        self._vectors = normalize_rows(vectors)

    def search(
        self,
        query: str,
        candidate_ids: set[str] | None = None,
        limit: int = 20,
    ) -> list[SearchHit]:
        if not query.strip() or limit < 1:
            return []

        query_vector = normalize_rows(self._embedder.encode([query]))[0]
        scores = self._vectors @ query_vector

        candidates: list[tuple[str, float]] = []

        for case_id, score in zip(
            self._case_ids,
            scores,
            strict=True,
        ):
            if candidate_ids is not None and case_id not in candidate_ids:
                continue

            candidates.append((case_id, float(score)))

        candidates.sort(key=lambda item: (-item[1], item[0]))

        return [
            SearchHit(
                case_id=case_id,
                source="semantic",
                rank=rank,
                score=score,
            )
            for rank, (case_id, score) in enumerate(
                candidates[:limit],
                start=1,
            )
        ]


@dataclass(frozen=True)
class FusedCandidate:
    case_id: str
    rrf_score: float
    source_ranks: dict[str, int]


def reciprocal_rank_fusion(
    rankings: Sequence[Sequence[SearchHit]],
    rank_constant: int = 60,
) -> list[FusedCandidate]:
    """Combine ranked result lists without comparing raw scores."""

    if rank_constant < 1:
        raise ValueError("rank_constant must be positive")

    scores: defaultdict[str, float] = defaultdict(float)
    source_ranks: defaultdict[str, dict[str, int]] = defaultdict(dict)

    for ranking in rankings:
        for hit in ranking:
            existing_rank = source_ranks[hit.case_id].get(hit.source)

            if existing_rank is None:
                scores[hit.case_id] += 1 / (rank_constant + hit.rank)
                source_ranks[hit.case_id][hit.source] = hit.rank
                continue

            if hit.rank < existing_rank:
                scores[hit.case_id] -= 1 / (rank_constant + existing_rank)
                scores[hit.case_id] += 1 / (rank_constant + hit.rank)
                source_ranks[hit.case_id][hit.source] = hit.rank

    fused = [
        FusedCandidate(
            case_id=case_id,
            rrf_score=score,
            source_ranks=source_ranks[case_id],
        )
        for case_id, score in scores.items()
    ]

    return sorted(
        fused,
        key=lambda item: (-item.rrf_score, item.case_id),
    )


class HybridRetriever:
    """Coordinates BM25, semantic retrieval and RRF."""

    def __init__(
        self,
        cases: Sequence[HistoricalCase],
        embedder: Embedder,
    ) -> None:
        if not cases:
            raise ValueError("HybridRetriever requires historical cases")

        self._cases = {case.case_id: case for case in cases}

        if len(self._cases) != len(cases):
            raise ValueError("Historical cases contain duplicate IDs")

        self._keyword = KeywordIndex(cases)
        self._semantic = SemanticIndex(cases, embedder)

    def _search_scope(
        self,
        query: str,
        candidate_ids: set[str],
        limit: int,
    ) -> list[FusedCandidate]:
        if not candidate_ids or limit < 1:
            return []

        candidate_limit = max(limit * 4, 10)

        keyword_hits = self._keyword.search(
            query=query,
            candidate_ids=candidate_ids,
            limit=candidate_limit,
        )
        semantic_hits = self._semantic.search(
            query=query,
            candidate_ids=candidate_ids,
            limit=candidate_limit,
        )

        return reciprocal_rank_fusion([keyword_hits, semantic_hits])[:limit]

    def search(
        self,
        query: str,
        equipment_type: str,
        equipment_family: str | None = None,
        limit: int = 5,
    ) -> EvidenceBundle:
        query = query.strip()
        equipment_type = equipment_type.strip()

        if not query:
            raise ValueError("query must not be blank")

        if not equipment_type:
            raise ValueError("equipment_type must not be blank")

        if limit < 1:
            raise ValueError("limit must be positive")

        if equipment_family is not None:
            equipment_family = equipment_family.strip() or None

        if equipment_family is None:
            matching_families = {
                case.equipment_family
                for case in self._cases.values()
                if case.equipment_type == equipment_type
            }

            if len(matching_families) == 1:
                equipment_family = matching_families.pop()

        exact_ids = {
            case.case_id for case in self._cases.values() if case.equipment_type == equipment_type
        }

        exact_results = self._search_scope(
            query=query,
            candidate_ids=exact_ids,
            limit=limit,
        )

        hits = [
            EvidenceHit(
                case=self._cases[result.case_id],
                rrf_score=result.rrf_score,
                source_ranks=result.source_ranks,
                match_scope="equipment_type",
            )
            for result in exact_results
        ]

        warnings: list[str] = []
        used_family_fallback = False
        remaining = limit - len(hits)

        if remaining > 0 and equipment_family:
            family_ids = {
                case.case_id
                for case in self._cases.values()
                if (case.equipment_family == equipment_family and case.case_id not in exact_ids)
            }

            family_results = self._search_scope(
                query=query,
                candidate_ids=family_ids,
                limit=remaining,
            )

            if family_results:
                used_family_fallback = True
                warnings.append(
                    "Some results use equipment-family history "
                    "because there were not enough type-specific cases."
                )

                hits.extend(
                    EvidenceHit(
                        case=self._cases[result.case_id],
                        rrf_score=result.rrf_score,
                        source_ranks=result.source_ranks,
                        match_scope="equipment_family",
                    )
                    for result in family_results
                )

        if not hits:
            warnings.append("No useful historical evidence was found.")

        return EvidenceBundle(
            query=query,
            equipment_type=equipment_type,
            equipment_family=equipment_family,
            hits=hits,
            used_family_fallback=used_family_fallback,
            warnings=warnings,
        )
