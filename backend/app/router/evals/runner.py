"""Scored eval runner for the router classifier (goal 5).

Measures the router against the labelled set in `cases.jsonl` and gates the goal
on a pass threshold — the router's quality is *measured, not asserted*.

Three modes (the same code; the split is what makes the cost-instrumented dynamic
workflow possible — see .claude/skills/eval-runner/SKILL.md):

  python -m app.router.evals.runner                  # run all cases inline (baseline)
  python -m app.router.evals.runner --shard 0/4 --out shard0.json   # one fan-out worker
  python -m app.router.evals.runner --aggregate 'shard*.json'       # combine + scorecard

`score()` is a PURE function over (cases, results) — unit-tested without any API
call. Only `classify_cases()` touches the network (the one runtime LLM).
"""

from __future__ import annotations

import argparse
import asyncio
import glob
import json
import os
from collections import defaultdict
from pathlib import Path

from app.router import config
from app.router.classifier import classify

_CASES = Path(__file__).with_name("cases.jsonl")
_CLASSES = ("task", "note", "event", "unknown")

# A fixture notes hierarchy injected for eval runs (goal 9): the classifier sees
# these leaf paths so `target_doc_path` proposals can be graded. Cases reference
# them via `doc_path_expect` ("" = the default Doc).
FIXTURE_DOC_PATHS = [
    "conversations/john/growth",
    "conversations/john/progression",
    "conversations/jane",
    "ideas",
    "reading",
]


def load_cases(path: Path = _CASES) -> list[dict]:
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def shard(cases: list[dict], spec: str) -> list[dict]:
    """`k/n` → the kth of n round-robin shards (so each shard mixes classes)."""
    k, n = (int(x) for x in spec.split("/"))
    return [c for i, c in enumerate(cases) if i % n == k]


async def classify_cases(cases: list[dict]) -> list[dict]:
    """Run the router over cases → per-case result rows (network: the runtime LLM).

    The fixture hierarchy (goal 9) is injected into every call so the classifier can
    propose a `target_doc_path`; non-hierarchy cases should still leave it null."""
    results = []
    for case in cases:
        c = await classify(case["text"], FIXTURE_DOC_PATHS)
        results.append(
            {
                "text": case["text"],
                "expected": case["destination"],
                "ambiguous": bool(case.get("ambiguous")),
                "predicted": c.destination,
                "confidence": c.confidence,
                "fields": c.fields.model_dump(),
                "case": case,  # carry the labels so --aggregate can grade fields
            }
        )
    return results


def _field_check(case: dict, fields: dict) -> bool | None:
    """Secondary grade: did key fields extract? None when the case has no field labels."""
    checks = []
    if "title_contains" in case:
        title = (fields.get("title") or "").lower()
        checks.append(case["title_contains"].lower() in title)
    if "target_list" in case:
        target = (fields.get("target_list") or "").lower()
        checks.append(case["target_list"].lower() == target)
    if case.get("expects_due"):
        checks.append(bool(fields.get("due_date")))
    if not checks:
        return None
    return all(checks)


def _doc_path_check(case: dict, fields: dict) -> bool | None:
    """Did the note route to the expected Doc path? None when unlabelled.

    `doc_path_expect` "" (or absent value) means the default Doc → predicted path
    must be null/empty. Case-insensitive exact match otherwise (goal 9)."""
    if "doc_path_expect" not in case:
        return None
    want = (case["doc_path_expect"] or "").strip().lower()
    got = (fields.get("target_doc_path") or "").strip().lower()
    return want == got


def _strip_check(case: dict, fields: dict) -> bool | None:
    """Prefix-stripping fidelity: note_text == raw minus prefix (goal 9). None when
    unlabelled. Compared verbatim after trimming surrounding whitespace only."""
    if "strip_expect" not in case:
        return None
    return (fields.get("note_text") or "").strip() == case["strip_expect"].strip()


def score(results: list[dict], threshold: float = config.CONFIDENCE_THRESHOLD) -> dict:
    """Pure scoring over per-case result rows. Computes destination accuracy
    (overall + clear-only), per-class P/R, confusion matrix, calibration, key-field
    extraction, and the gate-critical task false-positive count."""
    n = len(results)
    correct = sum(r["predicted"] == r["expected"] for r in results)
    clear = [r for r in results if not r["ambiguous"]]
    clear_correct = sum(r["predicted"] == r["expected"] for r in clear)

    # Confusion matrix + per-class P/R.
    confusion: dict[str, dict[str, int]] = {a: defaultdict(int) for a in _CLASSES}
    tp = defaultdict(int)
    fp = defaultdict(int)
    fn = defaultdict(int)
    for r in results:
        a, p = r["expected"], r["predicted"]
        confusion[a][p] += 1
        if a == p:
            tp[a] += 1
        else:
            fp[p] += 1
            fn[a] += 1
    per_class = {}
    for cls in _CLASSES:
        prec = tp[cls] / (tp[cls] + fp[cls]) if (tp[cls] + fp[cls]) else None
        rec = tp[cls] / (tp[cls] + fn[cls]) if (tp[cls] + fn[cls]) else None
        per_class[cls] = {
            "precision": prec,
            "recall": rec,
            "support": sum(1 for r in results if r["expected"] == cls),
        }

    # Calibration: confidence on correct vs incorrect, and whether ambiguous cases
    # stayed below threshold (so they'd land in review, not auto-write).
    conf_correct = [r["confidence"] for r in results if r["predicted"] == r["expected"]]
    conf_wrong = [r["confidence"] for r in results if r["predicted"] != r["expected"]]
    ambiguous = [r for r in results if r["ambiguous"]]
    ambiguous_below = sum(1 for r in ambiguous if r["confidence"] < threshold)

    # Gate-critical: a non-task predicted task with confidence ≥ threshold would
    # auto-CREATE a wrong Google task. Likewise an ambiguous case auto-acted on.
    task_false_positives = sum(
        1
        for r in results
        if r["expected"] != "task"
        and r["predicted"] == "task"
        and r["confidence"] >= threshold
    )
    ambiguous_auto_written = sum(
        1
        for r in ambiguous
        if r["predicted"] in ("task", "note") and r["confidence"] >= threshold
    )

    # Field-extraction (secondary).
    field_results = [
        _field_check(r["case"], r["fields"]) for r in results if "case" in r
    ]
    field_graded = [x for x in field_results if x is not None]

    # Doc-path routing (goal 9): graded on the CLEAR hierarchy subset only.
    doc_path_graded = [
        _doc_path_check(r["case"], r["fields"])
        for r in results
        if "case" in r and not r["ambiguous"]
    ]
    doc_path_graded = [x for x in doc_path_graded if x is not None]
    doc_path_accuracy = (
        (sum(doc_path_graded) / len(doc_path_graded)) if doc_path_graded else None
    )

    # Prefix-stripping fidelity (goal 9): note_text == raw minus prefix (spot metric).
    strip_graded = [
        _strip_check(r["case"], r["fields"])
        for r in results
        if "case" in r and not r["ambiguous"]
    ]
    strip_graded = [x for x in strip_graded if x is not None]

    clear_accuracy = (clear_correct / len(clear)) if clear else None
    passed = (
        clear_accuracy is not None
        and clear_accuracy >= 0.90
        and task_false_positives == 0
        and ambiguous_auto_written == 0
        # Doc-path threshold: ≥ 0.9 when the hierarchy subset is present.
        and (doc_path_accuracy is None or doc_path_accuracy >= 0.90)
    )

    return {
        "n": n,
        "destination_accuracy": round(correct / n, 3) if n else None,
        "clear_accuracy": round(clear_accuracy, 3)
        if clear_accuracy is not None
        else None,
        "per_class": per_class,
        "confusion": {a: dict(confusion[a]) for a in _CLASSES},
        "calibration": {
            "mean_conf_correct": round(sum(conf_correct) / len(conf_correct), 3)
            if conf_correct
            else None,
            "mean_conf_incorrect": round(sum(conf_wrong) / len(conf_wrong), 3)
            if conf_wrong
            else None,
            "ambiguous_below_threshold": f"{ambiguous_below}/{len(ambiguous)}",
        },
        "field_extraction": f"{sum(field_graded)}/{len(field_graded)}",
        "doc_path_accuracy": round(doc_path_accuracy, 3)
        if doc_path_accuracy is not None
        else None,
        "doc_path_graded": f"{sum(doc_path_graded)}/{len(doc_path_graded)}",
        "prefix_strip_fidelity": f"{sum(strip_graded)}/{len(strip_graded)}",
        "task_false_positives": task_false_positives,
        "ambiguous_auto_written": ambiguous_auto_written,
        "threshold": threshold,
        "passed": passed,
    }


def _print_scorecard(card: dict) -> None:
    print(json.dumps(card, indent=2))
    print("\nGATE:", "PASS ✅" if card["passed"] else "FAIL ❌")


async def _amain() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--shard", help="k/n round-robin shard (one fan-out worker)")
    ap.add_argument("--out", help="write per-case results JSON (for --aggregate)")
    ap.add_argument("--aggregate", help="glob of result files to combine + score")
    args = ap.parse_args()

    if args.aggregate:
        results: list[dict] = []
        for f in sorted(glob.glob(args.aggregate)):
            results.extend(json.loads(Path(f).read_text()))
        card = score(results)
        _print_scorecard(card)
        return 0 if card["passed"] else 1

    cases = load_cases()
    if args.shard:
        cases = shard(cases, args.shard)
    results = await classify_cases(cases)

    if args.out:
        Path(args.out).write_text(json.dumps(results, indent=2))
        print(f"wrote {len(results)} results → {args.out}")
        return 0

    card = score(results)
    _print_scorecard(card)
    return 0 if card["passed"] else 1


def main() -> None:
    raise SystemExit(asyncio.run(_amain()))


if __name__ == "__main__":
    if not os.environ.get("ANTHROPIC_API_KEY"):
        print(
            "WARNING: ANTHROPIC_API_KEY not set — classification will route to 'unknown'."
        )
    main()
