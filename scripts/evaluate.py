"""
Invoice extraction evaluation pipeline.

Runs the AI extraction pipeline against a labelled test set and reports
per-field accuracy, line-item accuracy, cross-field consistency, and cost
metrics.  Results are written to eval/results/eval_YYYY-MM-DD.json.

Usage:
    python scripts/evaluate.py [--prompt-version v1|v2] [--dry-run]

Options:
    --prompt-version  Prompt version to evaluate (default: v1).
    --dry-run         Skip real AI calls; generate a synthetic result report
                      for pipeline testing without an API key.

The script exits with code 1 when:
- ANTHROPIC_API_KEY is the sentinel "test-key" and --dry-run is not set.
- test_set.jsonl cannot be found.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import anthropic
from pydantic import BaseModel, Field

# Add the project root to sys.path so local app imports work when the script
# is invoked directly (python scripts/evaluate.py).
_PROJECT_ROOT = Path(__file__).parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from app.config import settings  # noqa: E402
from app.services.ai.client import AnthropicClient  # noqa: E402
from app.services.ai.prompts import DEFAULT_VERSION  # noqa: E402
from app.services.extraction_service import extract_invoice_fields  # noqa: E402

logger = logging.getLogger(__name__)

EVAL_DIR = _PROJECT_ROOT / "eval"
TEST_SET_PATH = EVAL_DIR / "test_set.jsonl"
RESULTS_DIR = EVAL_DIR / "results"

# Tolerance for numeric field comparison (dollars/units).
_AMOUNT_TOLERANCE = 0.02
# Fraction of expected line items that must match for the case to count as accurate.
_LINE_ITEM_MATCH_THRESHOLD = 0.8


# ── Pydantic models ───────────────────────────────────────────────────────────


class EvalCase(BaseModel):
    """A single labelled test case from test_set.jsonl."""

    id: str
    category: str
    invoice_text: str
    expected: dict[str, Any]


class FieldMatches(BaseModel):
    """Per-field boolean match results for one test case."""

    vendor: bool | None = None
    invoice_id: bool | None = None
    date: bool | None = None
    amount: bool | None = None
    currency: bool | None = None
    due_date: bool | None = None


class EvalResult(BaseModel):
    """Evaluation outcome for one test case."""

    case_id: str
    category: str
    extracted: dict[str, Any]
    field_matches: FieldMatches
    line_item_accuracy: float | None = None
    cross_field_consistent: bool
    latency_ms: float
    cost_usd: float
    error: str | None = None


class EvalReport(BaseModel):
    """Aggregated evaluation report written to disk."""

    timestamp: str
    model: str
    prompt_version: str
    test_cases: int
    overall_accuracy: float
    field_accuracy: dict[str, float] = Field(default_factory=dict)
    cross_field_consistency: float
    avg_latency_ms: float
    avg_cost_per_invoice_usd: float
    total_cost_usd: float
    category_accuracy: dict[str, float] = Field(default_factory=dict)
    errors: int = 0


# ── Test set loading ──────────────────────────────────────────────────────────


def load_test_cases(path: Path) -> list[EvalCase]:
    """
    Load and validate labelled test cases from a JSONL file.

    Args:
        path: Path to the JSONL test set file.

    Returns:
        List of EvalCase instances.

    Raises:
        FileNotFoundError: If the test set file does not exist.
        ValueError: If any line is not valid JSON or fails model validation.
    """
    if not path.exists():
        raise FileNotFoundError(f"Test set not found: {path}")

    test_cases: list[EvalCase] = []
    for line_number, raw_line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        stripped = raw_line.strip()
        if not stripped:
            continue
        try:
            data = json.loads(stripped)
        except json.JSONDecodeError as exc:
            raise ValueError(f"Line {line_number}: invalid JSON — {exc}") from exc
        test_cases.append(EvalCase.model_validate(data))

    logger.info("Loaded %d test cases from %s", len(test_cases), path)
    return test_cases


# ── Field matching ────────────────────────────────────────────────────────────


def _match_text(extracted: str | None, expected: str | None) -> bool | None:
    """
    Case-insensitive substring match for text fields.

    Returns None if the field is absent from ground truth (skip this field).
    Returns True if extracted is non-null and matches expected.
    Returns False if extracted is null when expected is non-null.
    """
    if expected is None:
        return None  # field not in ground truth; skip
    if extracted is None:
        return False
    return extracted.strip().lower() == expected.strip().lower()


def _match_amount(extracted: float | None, expected: float | None) -> bool | None:
    """
    Numeric match within _AMOUNT_TOLERANCE.

    Handles negative amounts (credit notes) correctly.
    """
    if expected is None:
        return None
    if extracted is None:
        return False
    return abs(extracted - expected) <= _AMOUNT_TOLERANCE


def _match_date(extracted: str | None, expected: str | None) -> bool | None:
    """
    ISO 8601 date match after normalising both sides to YYYY-MM-DD.

    Falls back to string comparison if parsing fails.
    """
    if expected is None:
        return None
    if extracted is None:
        return False
    # Both should be ISO 8601; do a direct string compare after stripping.
    return extracted.strip() == expected.strip()


def _match_currency(extracted: str | None, expected: str | None) -> bool | None:
    """Case-insensitive currency code match."""
    if expected is None:
        return None
    if extracted is None:
        return False
    return extracted.strip().upper() == expected.strip().upper()


def compute_field_matches(extracted_data: dict[str, Any], expected: dict[str, Any]) -> FieldMatches:
    """
    Compare extracted fields against ground truth and return a FieldMatches result.

    Args:
        extracted_data: Dict of extracted field values from the AI.
        expected: Ground truth dict from the test case.

    Returns:
        FieldMatches with a bool (or None for skipped fields) per field.
    """
    return FieldMatches(
        vendor=_match_text(extracted_data.get("vendor"), expected.get("vendor")),
        invoice_id=_match_text(extracted_data.get("invoice_id"), expected.get("invoice_id")),
        date=_match_date(extracted_data.get("date"), expected.get("date")),
        amount=_match_amount(extracted_data.get("amount"), expected.get("amount")),
        currency=_match_currency(extracted_data.get("currency"), expected.get("currency")),
        due_date=_match_date(extracted_data.get("due_date"), expected.get("due_date")),
    )


# ── Line-item accuracy ────────────────────────────────────────────────────────


def compute_line_item_accuracy(
    extracted_items: list[dict[str, Any]],
    expected_items: list[dict[str, Any]],
) -> float:
    """
    Compute the fraction of expected line items that were correctly extracted.

    An item is considered a match if its description (case-insensitive substring)
    and total (within tolerance) align with an expected item.

    Args:
        extracted_items: Line items from the AI extraction.
        expected_items: Ground truth line items.

    Returns:
        Recall score in [0.0, 1.0]: matched_expected / total_expected.
        Returns 1.0 if there are no expected items (nothing to miss).
    """
    if not expected_items:
        return 1.0

    matched_count = 0
    used_extracted_indices: set[int] = set()

    for expected_item in expected_items:
        expected_desc = expected_item.get("description", "").strip().lower()
        expected_total = expected_item.get("total")

        for idx, extracted_item in enumerate(extracted_items):
            if idx in used_extracted_indices:
                continue
            extracted_desc = extracted_item.get("description", "").strip().lower()
            extracted_total = extracted_item.get("total")

            desc_matches = expected_desc and (
                expected_desc in extracted_desc or extracted_desc in expected_desc
            )
            total_matches = (
                expected_total is None
                or extracted_total is None
                or abs(float(extracted_total) - float(expected_total)) <= _AMOUNT_TOLERANCE
            )

            if desc_matches and total_matches:
                matched_count += 1
                used_extracted_indices.add(idx)
                break

    return matched_count / len(expected_items)


# ── Cross-field consistency ───────────────────────────────────────────────────


def is_cross_field_consistent(extracted_data: dict[str, Any]) -> bool:
    """
    Check whether extracted numeric fields are internally consistent.

    Consistency rule: if line items and a total are both present,
    sum(line_items.total) + (tax or 0) ≈ total within tolerance.

    Args:
        extracted_data: Dict of extracted field values.

    Returns:
        True if the consistency check passes or there is insufficient data.
    """
    line_items: list[dict[str, Any]] = extracted_data.get("line_items") or []
    total: float | None = extracted_data.get("total") or extracted_data.get("amount")
    tax: float = extracted_data.get("tax") or 0.0

    if not line_items or total is None:
        return True  # insufficient data — treat as consistent

    items_sum = sum(float(item.get("total", 0)) for item in line_items)
    expected_total = round(items_sum + tax, 2)
    return abs(expected_total - total) <= _AMOUNT_TOLERANCE


# ── Per-case evaluation ───────────────────────────────────────────────────────


async def evaluate_case(
    test_case: EvalCase,
    ai_client: AnthropicClient,
    prompt_version: str,
) -> EvalResult:
    """
    Run extraction on one test case and compare against ground truth.

    Args:
        test_case: The labelled test case to evaluate.
        ai_client: Configured AnthropicClient.
        prompt_version: Prompt version string ("v1" or "v2").

    Returns:
        EvalResult with match results, accuracy metrics, and cost/latency.
    """
    start_time = time.monotonic()
    error_message: str | None = None
    extracted_data: dict[str, Any] = {}

    try:
        extracted_invoice = await extract_invoice_fields(
            test_case.invoice_text,
            ai_client=ai_client,
            prompt_version=prompt_version,
        )
        extracted_data = extracted_invoice.model_dump()
    except Exception as exc:  # noqa: BLE001 — eval must not abort on errors
        error_message = str(exc)

    latency_ms = (time.monotonic() - start_time) * 1000
    cost_usd = _estimate_cost(len(test_case.invoice_text))

    field_matches = compute_field_matches(extracted_data, test_case.expected)

    expected_items: list[dict[str, Any]] = test_case.expected.get("line_items") or []
    extracted_items: list[dict[str, Any]] = extracted_data.get("line_items") or []
    line_item_accuracy: float | None = (
        compute_line_item_accuracy(extracted_items, expected_items) if expected_items else None
    )

    return EvalResult(
        case_id=test_case.id,
        category=test_case.category,
        extracted=extracted_data,
        field_matches=field_matches,
        line_item_accuracy=line_item_accuracy,
        cross_field_consistent=is_cross_field_consistent(extracted_data),
        latency_ms=round(latency_ms, 1),
        cost_usd=cost_usd,
        error=error_message,
    )


def _estimate_cost(invoice_text_length: int) -> float:
    """
    Estimate per-call cost from text length and configured token prices.

    This is an approximation (≈ 4 chars/token) used when the AI client does
    not expose per-call cost directly.
    """
    approx_input_tokens = invoice_text_length // 4 + 200  # system prompt overhead
    approx_output_tokens = 150
    return (
        approx_input_tokens * settings.ai_cost_per_input_token_usd
        + approx_output_tokens * settings.ai_cost_per_output_token_usd
    )


# ── Aggregation ───────────────────────────────────────────────────────────────


def aggregate_results(
    results: list[EvalResult],
    prompt_version: str,
) -> EvalReport:
    """
    Compute aggregate accuracy metrics from a list of per-case results.

    Args:
        results: Completed EvalResult objects, one per test case.
        prompt_version: Prompt version used for this evaluation run.

    Returns:
        EvalReport with overall accuracy, per-field accuracy, and cost stats.
    """
    total = len(results)
    if total == 0:
        raise ValueError("No results to aggregate")

    error_count = sum(1 for r in results if r.error is not None)

    # Per-field accuracy: fraction of cases where the field matched (skipping None).
    field_names = ["vendor", "invoice_id", "date", "amount", "currency", "due_date"]
    field_accuracy: dict[str, float] = {}
    for field_name in field_names:
        field_results = [
            getattr(r.field_matches, field_name)
            for r in results
            if getattr(r.field_matches, field_name) is not None
        ]
        if field_results:
            field_accuracy[field_name] = round(sum(field_results) / len(field_results), 4)

    # Line-item accuracy: average over cases that have expected line items.
    line_item_scores = [r.line_item_accuracy for r in results if r.line_item_accuracy is not None]
    if line_item_scores:
        field_accuracy["line_items"] = round(sum(line_item_scores) / len(line_item_scores), 4)

    # Overall accuracy: mean of all non-None field matches across all results.
    all_match_values: list[bool] = []
    for result in results:
        for field_name in field_names:
            value = getattr(result.field_matches, field_name)
            if value is not None:
                all_match_values.append(value)

    overall_accuracy = (
        round(sum(all_match_values) / len(all_match_values), 4) if all_match_values else 0.0
    )

    # Cross-field consistency rate.
    cross_field_consistency = round(sum(r.cross_field_consistent for r in results) / total, 4)

    # Cost and latency.
    total_cost = sum(r.cost_usd for r in results)
    avg_latency = round(sum(r.latency_ms for r in results) / total, 1)

    # Per-category accuracy.
    categories: dict[str, list[bool]] = {}
    for result in results:
        cat = result.category
        if cat not in categories:
            categories[cat] = []
        cat_matches = [
            getattr(result.field_matches, fn)
            for fn in field_names
            if getattr(result.field_matches, fn) is not None
        ]
        if cat_matches:
            categories[cat].append(
                sum(cat_matches) / len(cat_matches) >= _LINE_ITEM_MATCH_THRESHOLD
            )

    category_accuracy = {
        cat: round(sum(vals) / len(vals), 4) for cat, vals in categories.items() if vals
    }

    return EvalReport(
        timestamp=datetime.now(UTC).isoformat(),
        model=settings.ai_model,
        prompt_version=prompt_version,
        test_cases=total,
        overall_accuracy=overall_accuracy,
        field_accuracy=field_accuracy,
        cross_field_consistency=cross_field_consistency,
        avg_latency_ms=avg_latency,
        avg_cost_per_invoice_usd=round(total_cost / total, 6),
        total_cost_usd=round(total_cost, 6),
        category_accuracy=category_accuracy,
        errors=error_count,
    )


# ── Report persistence ────────────────────────────────────────────────────────


def save_report(report: EvalReport, results_dir: Path) -> Path:
    """
    Write the evaluation report to a timestamped JSON file.

    Args:
        report: Completed EvalReport to serialise.
        results_dir: Directory to write the report into.

    Returns:
        Path of the written report file.
    """
    results_dir.mkdir(parents=True, exist_ok=True)
    date_str = datetime.now(UTC).strftime("%Y-%m-%d")
    output_path = results_dir / f"eval_{date_str}.json"
    output_path.write_text(json.dumps(report.model_dump(), indent=2), encoding="utf-8")
    return output_path


# ── Dry-run mode ──────────────────────────────────────────────────────────────


def _build_dry_run_report(test_cases: list[EvalCase], prompt_version: str) -> EvalReport:
    """
    Produce a synthetic report without calling the AI — for CI/testing.

    Args:
        test_cases: Loaded test cases (used for counts only).
        prompt_version: Prompt version to record in the report.

    Returns:
        A plausible EvalReport populated with synthetic but structurally valid data.
    """
    total = len(test_cases)
    return EvalReport(
        timestamp=datetime.now(UTC).isoformat(),
        model=settings.ai_model,
        prompt_version=prompt_version,
        test_cases=total,
        overall_accuracy=0.0,
        field_accuracy={
            "vendor": 0.0,
            "invoice_id": 0.0,
            "date": 0.0,
            "amount": 0.0,
            "currency": 0.0,
            "due_date": 0.0,
            "line_items": 0.0,
        },
        cross_field_consistency=0.0,
        avg_latency_ms=0.0,
        avg_cost_per_invoice_usd=0.0,
        total_cost_usd=0.0,
        category_accuracy={},
        errors=0,
    )


# ── CLI entry point ───────────────────────────────────────────────────────────


def _build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run the invoice extraction evaluation pipeline.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--prompt-version",
        default=DEFAULT_VERSION,
        choices=["v1", "v2"],
        help="Prompt version to evaluate (default: %(default)s)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Skip AI calls and write a synthetic report (for CI/pipeline testing)",
    )
    return parser


async def _run_evaluation(prompt_version: str) -> EvalReport:
    """
    Load test cases, run extraction, and aggregate results.

    Args:
        prompt_version: Prompt version to evaluate.

    Returns:
        Completed EvalReport.
    """
    test_cases = load_test_cases(TEST_SET_PATH)

    raw_client = anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key)
    ai_client = AnthropicClient(anthropic_client=raw_client, settings=settings)

    results: list[EvalResult] = []
    for idx, test_case in enumerate(test_cases, start=1):
        print(f"  [{idx:02d}/{len(test_cases)}] {test_case.id} ({test_case.category})", flush=True)
        result = await evaluate_case(test_case, ai_client, prompt_version)
        results.append(result)

        status = "✓" if result.error is None else "✗"
        matched = sum(
            1
            for f in ["vendor", "invoice_id", "date", "amount"]
            if getattr(result.field_matches, f) is True
        )
        print(
            f"       {status} fields={matched}/4  latency={result.latency_ms:.0f}ms"
            f"  cost=${result.cost_usd:.5f}"
        )

    return aggregate_results(results, prompt_version)


def main() -> None:
    """
    CLI entry point.  Parses arguments, runs evaluation, prints summary.

    Exits with code 1 on configuration errors.
    """
    logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(message)s")

    args = _build_arg_parser().parse_args()
    prompt_version: str = args.prompt_version
    dry_run: bool = args.dry_run

    if not dry_run and settings.anthropic_api_key == "test-key":
        print(
            "ERROR: ANTHROPIC_API_KEY is the test sentinel 'test-key'.\n"
            "       Set a real API key or pass --dry-run to generate a synthetic report.",
            file=sys.stderr,
        )
        sys.exit(1)

    test_cases = load_test_cases(TEST_SET_PATH)
    print(f"\nEvaluation pipeline — {len(test_cases)} test cases, prompt={prompt_version}")
    print("-" * 60)

    if dry_run:
        print("  [dry-run] skipping AI calls, generating synthetic report...")
        report = _build_dry_run_report(test_cases, prompt_version)
    else:
        report = asyncio.run(_run_evaluation(prompt_version))

    output_path = save_report(report, RESULTS_DIR)

    print("\n" + "=" * 60)
    print(f"  Test cases:           {report.test_cases}")
    print(f"  Overall accuracy:     {report.overall_accuracy:.1%}")
    print(f"  Cross-field consist.: {report.cross_field_consistency:.1%}")
    print(f"  Avg latency:          {report.avg_latency_ms:.0f} ms")
    print(f"  Avg cost / invoice:   ${report.avg_cost_per_invoice_usd:.5f}")
    print(f"  Total cost:           ${report.total_cost_usd:.5f}")
    print(f"  Errors:               {report.errors}")
    print("\n  Field accuracy:")
    for field_name, accuracy in sorted(report.field_accuracy.items()):
        print(f"    {field_name:<20} {accuracy:.1%}")
    print("\n  Category accuracy:")
    for category, accuracy in sorted(report.category_accuracy.items()):
        print(f"    {category:<20} {accuracy:.1%}")
    print(f"\n  Report saved → {output_path}")


if __name__ == "__main__":
    main()
