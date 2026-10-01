import json
from pathlib import Path

from pydantic import ValidationError

from diagnostic_assist.models import HistoricalCase


class CaseLoadError(ValueError):
    """Raised when the historical case file cannot be loaded safely."""


def load_cases(path: str | Path) -> list[HistoricalCase]:
    file_path = Path(path)

    try:
        payload = json.loads(file_path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise CaseLoadError(f"Case file not found: {file_path}") from exc
    except json.JSONDecodeError as exc:
        raise CaseLoadError(f"Case file is not valid JSON: {exc}") from exc

    if not isinstance(payload, list):
        raise CaseLoadError("The case file must contain a JSON array")

    cases: list[HistoricalCase] = []
    errors: list[str] = []

    for index, raw_case in enumerate(payload):
        try:
            cases.append(HistoricalCase.model_validate(raw_case))
        except ValidationError as exc:
            errors.append(f"Record {index}: {exc}")

    if errors:
        preview = "\n".join(errors[:5])
        raise CaseLoadError(f"{len(errors)} case records failed validation:\n{preview}")

    case_ids = [case.case_id for case in cases]

    if len(case_ids) != len(set(case_ids)):
        raise CaseLoadError("The case file contains duplicate case IDs")

    return cases
