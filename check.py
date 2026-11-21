#!/usr/bin/env python3
"""Validator and coverage reporter for JKSSB / JKPSC MCQ bank (data.json)."""

from __future__ import annotations

import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

VALID_DISTRICTS: tuple[str, ...] = (
    "Anantnag",
    "Bandipora",
    "Baramulla",
    "Budgam",
    "Ganderbal",
    "Kulgam",
    "Kupwara",
    "Pulwama",
    "Shopian",
    "Srinagar",
    "Doda",
    "Jammu",
    "Kathua",
    "Kishtwar",
    "Poonch",
    "Rajouri",
    "Ramban",
    "Riasi",
    "Samba",
    "Udhampur",
    "UT-Wide (All J&K)",
)

VALID_TYPES: set[str] = {"PYQ", "Trap", "Fact"}

REQUIRED_QUESTION_KEYS: set[str] = {
    "topic",
    "district",
    "month",
    "type",
    "question",
    "options",
    "answer",
    "explanation",
}


def normalize_text(text: str) -> str:
    """Normalize whitespace and punctuation for duplicate detection."""
    cleaned = re.sub(r"\s+", " ", text.strip().lower())
    return cleaned


def is_strict_int(value: Any) -> bool:
    """Return True for int values excluding booleans."""
    return isinstance(value, int) and not isinstance(value, bool)


def is_non_empty_str(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def validate_bank(data: Any) -> tuple[list[str], list[str]]:
    """Validate top-level structure and every question entry.

    Returns (errors, warnings). Errors block deployment; warnings flag hygiene issues.
    """
    errors: list[str] = []
    warnings: list[str] = []

    if not isinstance(data, dict):
        return ["Top-level JSON must be an object/dict."], warnings

    for key in ("topics", "months", "questions"):
        if key not in data:
            errors.append(f"Missing required top-level key: '{key}'.")

    topics = data.get("topics")
    months = data.get("months")
    questions = data.get("questions")

    topic_set: set[str] = set()
    if isinstance(topics, list):
        for idx, t in enumerate(topics):
            if not is_non_empty_str(t):
                errors.append(f"topics[{idx}] must be a non-empty string.")
            elif t in topic_set:
                warnings.append(f"Duplicate topic heading in 'topics': '{t}'.")
            else:
                topic_set.add(t.strip())
    elif "topics" in data:
        errors.append("'topics' must be a list of strings.")

    month_set: set[str] = set()
    if isinstance(months, list):
        for idx, m in enumerate(months):
            if not is_non_empty_str(m):
                errors.append(f"months[{idx}] must be a non-empty string.")
            elif m in month_set:
                warnings.append(f"Duplicate month heading in 'months': '{m}'.")
            else:
                month_set.add(m.strip())
    elif "months" in data:
        errors.append("'months' must be a list of strings.")

    if not isinstance(questions, list):
        if "questions" in data:
            errors.append("'questions' must be a list of question objects.")
        return errors, warnings

    seen_questions: dict[str, int] = {}
    valid_district_set = set(VALID_DISTRICTS)

    for idx, q in enumerate(questions):
        prefix = f"questions[{idx}]"
        if not isinstance(q, dict):
            errors.append(f"{prefix} must be an object/dict.")
            continue

        missing_keys = REQUIRED_QUESTION_KEYS - set(q.keys())
        extra_keys = set(q.keys()) - REQUIRED_QUESTION_KEYS
        if missing_keys:
            errors.append(f"{prefix} missing keys: {sorted(missing_keys)}.")
        if extra_keys:
            warnings.append(f"{prefix} has unexpected keys: {sorted(extra_keys)}.")

        # Topic check
        topic = q.get("topic")
        if not is_non_empty_str(topic):
            errors.append(f"{prefix}.topic must be a non-empty string.")
        elif topic_set and topic not in topic_set:
            warnings.append(f"{prefix}.topic '{topic}' is not listed in top-level 'topics'.")

        # District check
        district = q.get("district")
        if not is_non_empty_str(district):
            errors.append(f"{prefix}.district must be a non-empty string.")
        elif district not in valid_district_set:
            errors.append(
                f"{prefix}.district '{district}' is invalid. Must be one of the 20 J&K districts "
                f"or 'UT-Wide (All J&K)'."
            )

        # Month check ("" allowed for static GK)
        month = q.get("month")
        if not isinstance(month, str):
            errors.append(f"{prefix}.month must be a string (use '' for static GK).")
        elif month.strip() and month_set and month not in month_set:
            warnings.append(
                f"{prefix}.month '{month}' is not listed in top-level 'months'."
            )

        # Type check
        q_type = q.get("type")
        if not is_non_empty_str(q_type) or q_type not in VALID_TYPES:
            errors.append(
                f"{prefix}.type '{q_type}' must be one of {sorted(VALID_TYPES)}."
            )

        # Question text + duplicate check
        q_text = q.get("question")
        if not is_non_empty_str(q_text):
            errors.append(f"{prefix}.question must be a non-empty string.")
        else:
            norm = normalize_text(q_text)
            if norm in seen_questions:
                first_idx = seen_questions[norm]
                errors.append(
                    f"{prefix}.question is a duplicate of questions[{first_idx}]: "
                    f"\"{q_text.strip()[:70]}\""
                )
            else:
                seen_questions[norm] = idx

        # Options check (4 non-empty strings)
        options = q.get("options")
        if not isinstance(options, list) or len(options) != 4:
            errors.append(f"{prefix}.options must be a list of exactly 4 strings.")
        else:
            norm_opts: list[str] = []
            for opt_idx, opt in enumerate(options):
                if not is_non_empty_str(opt):
                    errors.append(f"{prefix}.options[{opt_idx}] must be a non-empty string.")
                else:
                    norm_opts.append(normalize_text(opt))
            if len(norm_opts) == 4 and len(set(norm_opts)) < 4:
                warnings.append(f"{prefix}.options contains duplicate choices.")

        # Answer check (0-indexed integer 0..3)
        answer = q.get("answer")
        if not is_strict_int(answer) or answer not in (0, 1, 2, 3):
            errors.append(
                f"{prefix}.answer '{answer}' must be an integer between 0 and 3."
            )

        # Explanation check
        explanation = q.get("explanation")
        if not is_non_empty_str(explanation):
            errors.append(f"{prefix}.explanation must be a non-empty string.")

    return errors, warnings


def print_coverage(data: dict[str, Any]) -> None:
    """Print coverage summary across topics, districts, months, and question types."""
    questions: list[dict[str, Any]] = data.get("questions", [])
    topics: list[str] = data.get("topics", [])
    months: list[str] = data.get("months", [])

    topic_counts: Counter[str] = Counter()
    district_counts: Counter[str] = Counter()
    month_counts: Counter[str] = Counter()
    type_counts: Counter[str] = Counter()
    by_topic_type: dict[str, Counter[str]] = defaultdict(Counter)

    for q in questions:
        if not isinstance(q, dict):
            continue
        t = q.get("topic", "<missing>")
        d = q.get("district", "<missing>")
        m = q.get("month", "")
        qt = q.get("type", "<missing>")

        topic_counts[t] += 1
        district_counts[d] += 1
        month_counts["[Static GK]" if m == "" else m] += 1
        type_counts[qt] += 1
        by_topic_type[t][qt] += 1

    print("\n" + "=" * 60)
    print(f"MCQ BANK COVERAGE SUMMARY  |  Total Questions: {len(questions)}")
    print("=" * 60)

    print("\n--- By Question Type ---")
    for qt in ("PYQ", "Trap", "Fact"):
        print(f"  {qt:<10}: {type_counts.get(qt, 0)}")
    for qt, cnt in type_counts.items():
        if qt not in {"PYQ", "Trap", "Fact"}:
            print(f"  {qt:<10}: {cnt}")

    print("\n--- By Topic (Syllabus Order + Extra) ---")
    ordered_topics = list(dict.fromkeys(list(topics) + list(topic_counts.keys())))
    for t in ordered_topics:
        cnt = topic_counts.get(t, 0)
        breakdown = by_topic_type[t]
        detail = f"(PYQ: {breakdown['PYQ']}, Trap: {breakdown['Trap']}, Fact: {breakdown['Fact']})"
        print(f"  {t:<32}: {cnt:>4}  {detail}")

    print("\n--- By District (20 Districts + UT-Wide) ---")
    for d in VALID_DISTRICTS:
        print(f"  {d:<24}: {district_counts.get(d, 0):>4}")
    for d, cnt in district_counts.items():
        if d not in VALID_DISTRICTS:
            print(f"  {d:<24}: {cnt:>4}  [INVALID]")

    print("\n--- By Month ---")
    print(f"  {'[Static GK]':<20}: {month_counts.get('[Static GK]', 0):>4}")
    ordered_months = list(dict.fromkeys(list(months) + [k for k in month_counts if k != "[Static GK]"]))
    for m in ordered_months:
        if m != "[Static GK]":
            print(f"  {m:<20}: {month_counts.get(m, 0):>4}")


def main() -> int:
    target = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("data.json")

    if not target.exists():
        print(f"Error: '{target}' not found.")
        return 1

    try:
        raw_text = target.read_text(encoding="utf-8")
        data = json.loads(raw_text)
    except json.JSONDecodeError as exc:
        print(f"JSON syntax error in '{target}': {exc}")
        return 1

    errors, warnings = validate_bank(data)

    if warnings:
        print(f"\nWarnings ({len(warnings)}):")
        for w in warnings:
            print(f"  [WARN] {w}")

    if errors:
        print(f"\nValidation FAILED with {len(errors)} error(s):")
        for e in errors:
            print(f"  [ERR]  {e}")
    else:
        print(f"\nValidation PASSED for '{target}' with 0 errors.")

    if isinstance(data, dict) and isinstance(data.get("questions"), list):
        print_coverage(data)

    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())