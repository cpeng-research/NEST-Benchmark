"""Use the existing comparative evaluators with numbered workflow overlays."""

from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import hashlib
import importlib
import json
import math
from pathlib import Path
import re
import sys
from types import SimpleNamespace


STAGES = {
    "html_empty": ("0-html_template", ".html"),
    "json_empty": ("1-annotated_json", ".json"),
    "json_filled": ("2-filled_json-a", ".json"),
    "html_filled": ("3-filled_html-a", ".html"),
    "context": ("4-context-a", ".txt"),
    "placeholder_html": ("5-ph_html-a", ".html"),
    "meta": ("6-meta-a", ".json"),
}
AUXILIARY = {
    "html_second": ("7-html-b/data_{lang}", ".html"),
    "json_second": ("8-json-b/data_{lang}", ".json"),
    "png_empty": ("9-png-a/data_{lang}/empty", ".png"),
    "png_filled": ("9-png-a/data_{lang}/filled", ".png"),
}
TASKS = ("schema", "alignment", "infill")
CONDITIONS = ("empty", "filled")
SCORED = {"scored", "model_format_failure"}


def benchmark_root(explicit=None):
    candidates = [Path(explicit).resolve()] if explicit else Path(__file__).resolve().parents
    for root in candidates:
        if (root / "comparative_eval/config.py").is_file():
            return root
    raise ValueError("Cannot find comparative_eval/config.py; use --benchmark-root")


def load_core(root):
    existing = sys.modules.get("comparative_eval")
    if existing and (not getattr(existing, "__file__", None)
                     or Path(existing.__file__).resolve().parent != root / "comparative_eval"):
        raise ValueError("Another benchmark's comparative_eval is already imported")
    sys.path.insert(0, str(root))
    modules = {
        "config": "config", "prompts": "prompts", "schema": "eval_schema",
        "alignment": "eval_alignment", "infill": "eval_infill",
        "infill_metric": "metrics.infill", "jedi": "metrics.jedi_py",
        "cpp": "metrics.jedi_cpp", "text": "utils.openai_utils",
    }
    return SimpleNamespace(**{key: importlib.import_module("comparative_eval." + name)
                              for key, name in modules.items()})


def safe_language(value):
    if not re.fullmatch(r"[a-zA-Z][a-zA-Z0-9]*(?:[-_][a-zA-Z0-9]+)*", value):
        raise ValueError(f"Unsafe language: {value!r}")
    return value


def model_directory(model):
    value = model.replace("/", "_").replace("-", "_")
    if not value or value in {".", ".."} or not re.fullmatch(r"[A-Za-z0-9_.]+", value):
        raise ValueError("Model label must contain only letters, digits, '.', '_', '-', or '/'")
    return value


def digest(data):
    return hashlib.sha256(data).hexdigest()


def identity(job):
    return job["lang"], job["sample_id"], job["task"], job["condition"]


def discover(roots, languages=None, start_id=None, end_id=None):
    """Check Stage 0-9 ID reservations; evaluate only identities present in 0-6."""
    samples = {}
    seen_languages = set()
    locations = {key: (stage + "/data_{lang}", suffix) for key, (stage, suffix) in STAGES.items()}
    locations.update(AUXILIARY)
    for lang in languages or ():
        safe_language(lang)
    for root in dict.fromkeys(Path(root).resolve() for root in roots):
        if root.name != "workflow" or not root.is_dir():
            raise ValueError(f"Expected an existing directory named workflow: {root}")
        langs = languages or sorted({path.name[5:] for stage in {v[0].split("/")[0] for v in locations.values()}
                                    for path in (root / stage).glob("data_*") if path.is_dir()})
        for lang in dict.fromkeys(langs):
            safe_language(lang)
            files = defaultdict(dict)
            for key, (directory, suffix) in locations.items():
                for path in sorted((root / directory.format(lang=lang)).glob("*")):
                    if path.suffix.lower() != suffix or not path.stem.isdecimal():
                        continue
                    number = int(path.stem)
                    if path.stem != str(number) or number < 1 or key in files[number]:
                        raise ValueError(f"Duplicate/noncanonical numeric ID: {path}")
                    files[number][key] = path
            if any(set(found) & STAGES.keys() for found in files.values()):
                seen_languages.add(lang)
            for number, found in sorted(files.items()):
                paths, hashes, errors = {}, {}, {}
                for key, (directory, suffix) in locations.items():
                    if key in AUXILIARY and key not in found:
                        continue
                    path = found.get(key, root / directory.format(lang=lang) / f"{number}{suffix}")
                    paths[key] = path
                    try:
                        hashes[key] = digest(path.read_bytes())
                    except OSError as exc:
                        hashes[key] = None
                        errors[key] = type(exc).__name__
                sample = {"lang": lang, "sample_id": number, "paths": paths,
                          "source_hashes": {key: hashes[key] for key in STAGES},
                          "source_issues": {key: error for key, error in errors.items() if key in STAGES},
                          "has_core": bool(set(found) & STAGES.keys()),
                          "auxiliary_hashes": {key: hashes[key] for key in AUXILIARY if key in hashes},
                          "auxiliary_issues": {key: error for key, error in errors.items() if key in AUXILIARY}}
                old = samples.get((lang, number))
                if old is not None:
                    if (old["has_core"] != sample["has_core"]
                            or old["source_hashes"] != sample["source_hashes"]
                            or old["source_issues"] != sample["source_issues"]):
                        raise ValueError(f"Conflicting workflow sample: {lang}/{number}")
                    old_aux, new_aux = old["auxiliary_hashes"], sample["auxiliary_hashes"]
                    if (any(old_aux[key] != new_aux[key] for key in old_aux.keys() & new_aux.keys())
                            or old["auxiliary_issues"] or sample["auxiliary_issues"]
                            or old_aux != new_aux and not all(sample["source_hashes"].values())):
                        raise ValueError(f"Conflicting auxiliary ID reservation: {lang}/{number}")
                    old_aux.update(new_aux)
                else:
                    samples[(lang, number)] = sample
    missing = set(languages or ()) - seen_languages
    if missing:
        raise ValueError("No numbered samples for requested language(s): " + ", ".join(sorted(missing)))
    return [samples[key] for key in sorted(samples) if samples[key]["has_core"]
            and (start_id is None or key[1] >= start_id) and (end_id is None or key[1] <= end_id)]


def read_source(sample, key):
    if key in sample["source_issues"]:
        raise ValueError(f"{key}: {sample['source_issues'][key]}")
    data = sample["paths"][key].read_bytes()
    if digest(data) != sample["source_hashes"][key]:
        raise ValueError(f"{key}: changed while reading")
    text = data.decode("utf-8").replace("\r\n", "\n").replace("\r", "\n")
    if not text.strip():
        raise ValueError(f"{key}: empty source")
    return text


def task_sources(core, sample, task, condition):
    html = read_source(sample, "html_" + condition)
    context, gold, expected, strategy = None, None, None, None
    if task == "schema":
        gold, status = core.schema.parse_schema_json(
            json.loads(read_source(sample, "json_" + condition)), source="gold")
        if gold is None:
            raise ValueError("Invalid gold schema: " + status)
        total = 1
    elif task == "alignment":
        expected = core.alignment.expand_meta(json.loads(read_source(sample, "meta")))
        gold = read_source(sample, "placeholder_html")
        strategy = core.alignment.choose_coordinate_strategy(gold, expected)
        expected = core.alignment.resolve_expected_names_from_gold(gold, expected, strategy)
        total = len(expected)
    else:
        context = read_source(sample, "context")
        gold = read_source(sample, "html_filled")
        placeholder = read_source(sample, "placeholder_html")
        expected = placeholder
        total = core.infill.count_expected_fill_slots(gold, placeholder, matcher="source_faithful_v3")
    return html, context, gold, expected, strategy, total


def prepare(core, samples, model, tasks, conditions, schema_metric):
    if "schema" in tasks and schema_metric not in {"py_tree", "cpp"}:
        raise ValueError("Select --schema-metric py_tree or cpp explicitly for schema")
    model_directory(model)
    jobs = []
    for sample in samples:
        for task in tasks:
            for condition in conditions:
                job = {"lang": sample["lang"], "sample_id": sample["sample_id"],
                       "model": model, "task": task, "condition": condition,
                       "schema_metric": schema_metric if task == "schema" else None,
                       "source_hashes": sample["source_hashes"],
                       "source_issues": sample["source_issues"], "messages": [], "target_count": None}
                try:
                    html, context, _, _, _, total = task_sources(core, sample, task, condition)
                    job["target_count"] = total
                    job["status"] = "ready" if total else "ineligible_no_targets"
                    if total:
                        fn = getattr(core.prompts, task + "_prompt")
                        prompt = fn(html, context, condition) if task == "infill" else fn(html, condition)
                        job["messages"] = [{"role": "system", "content": core.prompts.TABLE3_SYSTEM_PROMPT},
                                           {"role": "user", "content": prompt}]
                except (OSError, ValueError, TypeError, KeyError) as exc:
                    job.update(status="source_error", issue=str(exc))
                jobs.append(job)
    return {"model": model, "jobs": jobs}


def prediction_path(root, job):
    return (Path(root) / f"{job['task']}_{job['condition']}" / job["lang"]
            / model_directory(job["model"]) / f"{job['sample_id']}.json")


def score(core, sample, job, raw, sources=None):
    _, _, gold, expected, strategy, total = sources or task_sources(core, sample, job["task"], job["condition"])
    raw = core.text.strip_thinking(raw) if isinstance(raw, str) else ""
    malformed = not raw.strip()
    detail = {}
    if job["task"] == "schema":
        pred, pred_status = core.schema.parse_schema_json(raw)
        malformed = malformed or pred is None
        if malformed:
            value = 0.0
        else:
            detail = (core.cpp.compare_json_similarity_cpp(pred, gold)
                      if job["schema_metric"] == "cpp"
                      else core.jedi.compare_json_similarity(pred, gold, mode="tree_edit"))
            if detail.get("timeout") or detail.get("distance") is None:
                raise RuntimeError("Schema backend did not return a distance")
            value = float(detail["similarity"])
        detail["pred_status"] = pred_status
        correct = None
    elif job["task"] == "alignment":
        breakdown = (core.alignment.zero_alignment_results(expected) if malformed
                     else core.alignment.compare_alignment(raw, expected, strategy)[0])
        correct = sum(item["correct"] for item in breakdown.values())
        total = sum(item["total"] for item in breakdown.values())
        value = correct / total
        detail = {"strategy": strategy, "by_type": breakdown}
    else:
        correct, total = ((0, total) if malformed else core.infill_metric.compare_infill(
            raw, gold, expected, matcher="source_faithful_v3"))
        value = correct / total
    if not math.isfinite(value) or not 0 <= value <= 1:
        raise RuntimeError("Metric returned an invalid score")
    return {"status": "model_format_failure" if malformed else "scored", "score": value,
            "correct": correct, "total": total, "details": detail}


def evidence_matches(evidence, job):
    keys = ("lang", "sample_id", "model", "task", "condition", "schema_metric",
            "source_hashes", "messages", "target_count", "status")
    return isinstance(evidence, dict) and all(key in evidence and evidence[key] == job[key] for key in keys)


def evaluate(core, samples, requests, prediction_root, prepared=None):
    by_sample = {(s["lang"], s["sample_id"]): s for s in samples}
    jobs = requests["jobs"]
    evidence = {}
    if prepared is not None:
        if not isinstance(prepared, dict) or not isinstance(prepared.get("jobs"), list):
            raise ValueError("--prepared must contain a jobs list")
        for job in prepared["jobs"]:
            key = identity(job)
            if key in evidence:
                raise ValueError("Duplicate job in --prepared")
            evidence[key] = job
        if set(evidence) != {identity(job) for job in jobs}:
            raise ValueError("--prepared job set differs; use the same language, ID, task and condition filters")
    for directory in {prediction_path(prediction_root, job).parent for job in jobs}:
        for path in directory.glob("*.json"):
            if path.stem.isdecimal() and path.stem != str(int(path.stem)):
                raise ValueError(f"Noncanonical prediction ID: {path}")
    rows = []
    for job in jobs:
        row = {key: job[key] for key in ("lang", "sample_id", "model", "task", "condition", "schema_metric")}
        row.update(score=None, correct=None, total=job["target_count"], status=job["status"],
                   source_hashes=job["source_hashes"])
        rows.append(row)
        if job["status"] != "ready":
            row["issue"] = job.get("issue", "No evaluable targets")
            continue
        path = prediction_path(prediction_root, job)
        if not path.exists():
            row["status"] = "not_run"
            continue
        try:
            record = json.loads(path.read_text(encoding="utf-8"))
        except (ValueError, UnicodeError):
            record = None
        except OSError as exc:
            row.update(status="prediction_error", issue=type(exc).__name__)
            continue
        record = record if isinstance(record, dict) else {}
        supplied = record.get("request", evidence.get(identity(job)))
        if not evidence_matches(supplied, job) or (identity(job) in evidence and not evidence_matches(evidence[identity(job)], job)):
            row.update(status="source_mismatch", issue="Missing or mismatched prepared request; no score assigned")
            continue
        if (any(key in record and record[key] != job[key]
                for key in ("model", "sample_id", "lang", "task", "condition"))
                or "sample_id" in record and type(record["sample_id"]) is not int):
            row.update(status="prediction_error", issue="Prediction identity mismatch")
            continue
        status = record.get("status", "completed")
        if status in {"not_run", "transport_error", "backend_error"}:
            row["status"] = status
            continue
        if status != "completed" or record.get("error"):
            row.update(status="prediction_error", issue="Unrecognized failure status")
            continue
        try:
            sample = by_sample[job["lang"], job["sample_id"]]
            sources = task_sources(core, sample, job["task"], job["condition"])
        except (OSError, ValueError, TypeError, KeyError) as exc:
            row.update(status="source_error", issue=str(exc))
            continue
        try:
            row.update(score(core, sample, job, record.get("raw_response"), sources))
        except Exception as exc:
            row.update(status="backend_error", issue=type(exc).__name__)
    return {"model": requests["model"], "rows": rows, "summary": summarize(rows)}


def summarize(rows):
    groups = defaultdict(list)
    for row in rows:
        groups[row["task"], row["lang"], row["condition"]].append(row)
    summary = []
    for (task, lang, condition), items in sorted(groups.items()):
        valid = [row for row in items if row["status"] in SCORED]
        correct = sum(row["correct"] for row in valid) if task != "schema" else None
        total = sum(row["total"] for row in valid)
        value = (sum(row["score"] for row in valid) / len(valid) if task == "schema"
                 else correct / total) if valid else None
        summary.append({"task": task, "lang": lang, "condition": condition,
                        "metric": (items[0]["schema_metric"] if task == "schema" else
                                   "source_faithful_v3" if task == "infill" else "meta_target_cell_input_name_accuracy"),
                        "aggregation": "table_macro" if task == "schema" else "target_micro",
                        "job_count": len(items), "scored_count": len(valid),
                        "counts": dict(Counter(row["status"] for row in items)),
                        "complete": len(valid) == len(items), "score": value,
                        "correct": correct, "total": total})
    return summary


def write_output(path, data, protected):
    path = Path(path).resolve()
    protected = [Path(root).resolve() for root in protected]
    if any(path == root or path.is_relative_to(root) for root in protected):
        raise ValueError("Output must be outside benchmark, workflow and prediction directories")
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8") as handle:
        json.dump(data, handle, ensure_ascii=False, indent=2, allow_nan=False)
        handle.write("\n")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["prepare", "evaluate"])
    parser.add_argument("--benchmark-root", type=Path)
    parser.add_argument("--workflow-root", type=Path, action="append")
    parser.add_argument("--lang", action="append", help="Repeat for multiple languages; default: discover data_* directories")
    parser.add_argument("--task", choices=[*TASKS, "all"], default="all")
    parser.add_argument("--condition", choices=[*CONDITIONS, "both"], default="both")
    parser.add_argument("--start_id", "--start-id", type=int)
    parser.add_argument("--end_id", "--end-id", type=int)
    parser.add_argument("--model", required=True)
    parser.add_argument("--schema-metric", choices=["py_tree", "cpp"])
    parser.add_argument("--prediction-root", type=Path)
    parser.add_argument("--prepared", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        root = benchmark_root(args.benchmark_root)
        roots = args.workflow_root or [root / "workflow"]
        if args.start_id is not None and args.end_id is not None and args.start_id > args.end_id:
            raise ValueError("start_id exceeds end_id")
        core = load_core(root)
        samples = discover(roots, args.lang, args.start_id, args.end_id)
        if not samples:
            raise ValueError("No numbered samples found for the requested selection")
        tasks = TASKS if args.task == "all" else (args.task,)
        conditions = CONDITIONS if args.condition == "both" else (args.condition,)
        requests = prepare(core, samples, args.model, tasks, conditions, args.schema_metric)
        if args.action == "evaluate":
            if not args.prediction_root:
                raise ValueError("evaluate requires --prediction-root")
            prepared = json.loads(args.prepared.read_text(encoding="utf-8")) if args.prepared else None
            result = evaluate(core, samples, requests, args.prediction_root, prepared)
            complete = all(row["status"] in SCORED for row in result["rows"])
        else:
            if args.prepared or args.prediction_root:
                raise ValueError("--prepared and --prediction-root apply only to evaluate")
            result = requests
            complete = all(job["status"] == "ready" for job in requests["jobs"])
        protected = [root, *(Path(path).resolve() for path in roots)]
        if args.prediction_root:
            protected.append(args.prediction_root.resolve())
        write_output(args.output, result, protected)
        print(f"Wrote {args.output}; jobs={len(requests['jobs'])}; complete={complete}")
        return 0 if complete else 1
    except (OSError, ValueError, TypeError, KeyError) as exc:
        parser.error(str(exc))


if __name__ == "__main__":
    raise SystemExit(main())
