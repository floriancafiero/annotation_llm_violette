#!/usr/bin/env python3
"""Evaluate model annotations against a small human ground truth.

The evaluator uses approximate character-name overlap to match predicted relations
to gold relations, then computes relation detection metrics and per-field accuracy.
"""

from __future__ import annotations

import argparse
import json
import re
import unicodedata
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Dict, Iterable, List, Tuple

FIELDS = ["relation_type", "explicitness", "centrality", "framing", "outcome"]


def read_jsonl(path: str | Path) -> Iterable[Dict[str, Any]]:
    with Path(path).open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                yield json.loads(line)


def normalize(text: str) -> str:
    text = unicodedata.normalize("NFKD", text)
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    text = text.lower()
    text = re.sub(r"[^a-z0-9]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def char_tokens(rel: Dict[str, Any]) -> set[str]:
    chars = rel.get("characters", []) or []
    tokens: set[str] = set()
    for name in chars:
        norm = normalize(str(name))
        if norm:
            tokens.add(norm)
            tokens.update(norm.split())
    return tokens


def jaccard(a: set[str], b: set[str]) -> float:
    if not a and not b:
        return 0.0
    return len(a & b) / len(a | b)


def relation_similarity(pred: Dict[str, Any], gold: Dict[str, Any]) -> float:
    score = jaccard(char_tokens(pred), char_tokens(gold))
    if pred.get("relation_type") == gold.get("relation_type"):
        score += 0.15
    return min(score, 1.0)


def greedy_match(preds: List[Dict[str, Any]], golds: List[Dict[str, Any]], threshold: float) -> List[Tuple[int, int, float]]:
    candidates: List[Tuple[float, int, int]] = []
    for i, pred in enumerate(preds):
        for j, gold in enumerate(golds):
            sim = relation_similarity(pred, gold)
            if sim >= threshold:
                candidates.append((sim, i, j))
    candidates.sort(reverse=True)
    used_pred: set[int] = set()
    used_gold: set[int] = set()
    matches: List[Tuple[int, int, float]] = []
    for sim, i, j in candidates:
        if i in used_pred or j in used_gold:
            continue
        used_pred.add(i)
        used_gold.add(j)
        matches.append((i, j, sim))
    return matches


def get_annotation_relations(record: Dict[str, Any]) -> List[Dict[str, Any]]:
    if "annotation" in record and isinstance(record["annotation"], dict):
        return record["annotation"].get("relations", []) or []
    return record.get("relations", []) or []


def load_gold(path: str | Path) -> Dict[str, List[Dict[str, Any]]]:
    out: Dict[str, List[Dict[str, Any]]] = {}
    for record in read_jsonl(path):
        out[str(record["novel_id"])] = get_annotation_relations(record)
    return out


def safe_div(num: float, den: float) -> float:
    return num / den if den else 0.0


def evaluate(predictions_path: str | Path, gold_path: str | Path, threshold: float) -> Dict[str, Any]:
    gold = load_gold(gold_path)
    by_model: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for record in read_jsonl(predictions_path):
        by_model[str(record.get("model", "unknown"))].append(record)

    summary: Dict[str, Any] = {"models": {}}

    for model, records in by_model.items():
        counts = Counter()
        field_correct = Counter()
        field_total = Counter()
        errors = Counter()
        examples = []

        for record in records:
            novel_id = str(record.get("novel_id"))
            gold_rels = gold.get(novel_id, [])
            pred_rels = get_annotation_relations(record) if record.get("ok", True) else []
            if record.get("parse_error"):
                errors["parse_error"] += 1
            if record.get("validation_error"):
                errors["validation_error"] += 1
            if record.get("runtime_error"):
                errors["runtime_error"] += 1

            matches = greedy_match(pred_rels, gold_rels, threshold)
            counts["predicted"] += len(pred_rels)
            counts["gold"] += len(gold_rels)
            counts["matched"] += len(matches)

            matched_pred = {i for i, _, _ in matches}
            matched_gold = {j for _, j, _ in matches}
            if len(examples) < 25:
                for i, pred in enumerate(pred_rels):
                    if i not in matched_pred:
                        examples.append({"novel_id": novel_id, "kind": "unmatched_prediction", "prediction": pred})
                for j, g in enumerate(gold_rels):
                    if j not in matched_gold:
                        examples.append({"novel_id": novel_id, "kind": "missed_gold", "gold": g})

            for pred_i, gold_j, sim in matches:
                pred = pred_rels[pred_i]
                g = gold_rels[gold_j]
                for field in FIELDS:
                    field_total[field] += 1
                    if pred.get(field) == g.get(field):
                        field_correct[field] += 1

        precision = safe_div(counts["matched"], counts["predicted"])
        recall = safe_div(counts["matched"], counts["gold"])
        f1 = safe_div(2 * precision * recall, precision + recall)
        summary["models"][model] = {
            "relation_detection": {
                "precision": precision,
                "recall": recall,
                "f1": f1,
                "predicted": counts["predicted"],
                "gold": counts["gold"],
                "matched": counts["matched"],
                "matching_threshold": threshold,
            },
            "field_accuracy_on_matched_relations": {
                field: safe_div(field_correct[field], field_total[field]) for field in FIELDS
            },
            "field_support": dict(field_total),
            "errors": dict(errors),
            "examples_for_manual_review": examples,
        }

    return summary


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--predictions", required=True)
    parser.add_argument("--gold", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--threshold", type=float, default=0.5)
    args = parser.parse_args()

    summary = evaluate(args.predictions, args.gold, args.threshold)
    Path(args.output).parent.mkdir(parents=True, exist_ok=True)
    Path(args.output).write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
