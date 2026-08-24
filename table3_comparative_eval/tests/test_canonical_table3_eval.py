from __future__ import annotations

import json

from table3_comparative_eval.canonical_table3_eval import prediction_status, summarize_pairs


def test_prediction_status_distinguishes_retryable_files(tmp_path):
    missing = tmp_path / "missing.json"
    assert prediction_status(missing) == ("missing", False)

    invalid = tmp_path / "invalid.json"
    invalid.write_text("{", encoding="utf-8")
    assert prediction_status(invalid) == ("invalid_json", False)

    empty = tmp_path / "empty.json"
    empty.write_text(json.dumps({"raw_response": "  "}), encoding="utf-8")
    assert prediction_status(empty) == ("empty_response", False)

    ready = tmp_path / "ready.json"
    ready.write_text(json.dumps({"raw_response": "{}"}), encoding="utf-8")
    assert prediction_status(ready) == ("ready", True)


def test_pair_summary_requires_both_conditions():
    rows = [
        {
            "model": "m",
            "task": "schema",
            "lang": "en",
            "condition": "empty",
            "sample_id": 1,
            "prediction_status": "ready",
        },
        {
            "model": "m",
            "task": "schema",
            "lang": "en",
            "condition": "filled",
            "sample_id": 1,
            "prediction_status": "missing",
        },
    ]

    summary = summarize_pairs(rows)[0]
    assert summary["eligible_count"] == 1
    assert summary["paired_ready_count"] == 0
    assert summary["template_only_count"] == 1
    assert summary["complete"] is False
