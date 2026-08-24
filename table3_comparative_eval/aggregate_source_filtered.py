from __future__ import annotations

import csv
import json
import re
from pathlib import Path
from urllib.parse import urlparse


ROOT = Path(__file__).resolve().parents[1]
DETAILS = ROOT / "table3_comparative_eval/results/details"
OUTPUT = ROOT / "table3_comparative_eval/results/source_filtered"

MODELS = (
    ("gpt_5", "GPT-5"),
    ("gpt_4o", "GPT-4o"),
    ("gpt_4o_mini", "GPT-4o-mini"),
    ("gpt_3.5_turbo", "GPT-3.5-turbo"),
    ("Llama_3.1_8B_Instruct", "Llama-3.1-8B-Instruct"),
    ("Qwen2.5_7B_Instruct", "Qwen2.5-7B-Instruct"),
    ("Gemma_2_9B_it", "Gemma-2-9B-it"),
    ("Mistral_7B_Instruct_v0.3", "Mistral-7B-Instruct-v0.3"),
)
PUBLIC_DOMAIN_SUFFIXES = (".gov", ".gov.hk", ".gov.uk", ".mil")
PUBLIC_INSTITUTION_DOMAINS = {
    "canada.ca",
    "coms-auth.hk",
    "cmchk.org.hk",
    "hongkongpost.hk",
    "ladhs.org",
    "procurement.gwu.edu",
    "utdallas.edu",
    "westonhousepractice.nhs.uk",
}


def manifest_path() -> Path:
    candidates = (
        ROOT / "data/source_provenance_manifest.csv",
        ROOT / "source_provenance_manifest_v1.csv",
    )
    for path in candidates:
        if path.exists():
            return path
    raise FileNotFoundError(f"No provenance manifest found in: {candidates}")


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def extract_domains(source: str) -> set[str]:
    domains: set[str] = set()
    for raw_url in re.findall(r"https?://[^;) |]+", source):
        domain = urlparse(raw_url).netloc.lower().removeprefix("www.")
        if domain:
            domains.add(domain)
    return domains


def is_public_institution_domain(domain: str) -> bool:
    return domain in PUBLIC_INSTITUTION_DOMAINS or any(
        domain.endswith(suffix) for suffix in PUBLIC_DOMAIN_SUFFIXES
    )


def candidate_rows() -> list[dict[str, str]]:
    selected = []
    for row in read_csv(manifest_path()):
        domains = extract_domains(row.get("source", ""))
        if domains and all(is_public_institution_domain(domain) for domain in domains):
            selected.append(row)
    return selected


def detail_path(task: str, condition: str, language: str, model: str) -> Path:
    metric_suffix = "_cpp" if task == "schema" else ""
    return DETAILS / f"{task}_{condition}_{language}_{model}{metric_suffix}.csv"


def load_details() -> dict[tuple[str, str, str, str], dict[int, dict[str, str]]]:
    loaded = {}
    for model, _label in MODELS:
        for task in ("schema", "alignment", "infill"):
            for condition in ("filled", "empty"):
                for language in ("en", "zh"):
                    rows = read_csv(detail_path(task, condition, language, model))
                    loaded[(model, task, condition, language)] = {
                        int(row["sample_id"]): row for row in rows
                    }
    return loaded


def split_language(row: dict[str, str]) -> str:
    return "zh" if row["language"] == "zh" else "en"


def common_rows(
    rows: list[dict[str, str]],
    details: dict[tuple[str, str, str, str], dict[int, dict[str, str]]],
) -> tuple[list[dict[str, str]], list[dict[str, object]]]:
    selected = []
    excluded = []
    for row in rows:
        sample_id = int(row["id"])
        language = split_language(row)
        missing = []
        for model, _label in MODELS:
            for task in ("schema", "alignment", "infill"):
                for condition in ("filled", "empty"):
                    if sample_id not in details[(model, task, condition, language)]:
                        missing.append(f"{model}:{task}:{condition}")
        if missing:
            excluded.append({"id": sample_id, "language": language, "missing": missing})
        else:
            selected.append(row)
    return selected, excluded


def score(
    rows: list[dict[str, str]],
    details: dict[tuple[str, str, str, str], dict[int, dict[str, str]]],
    model: str,
    task: str,
    condition: str,
) -> float:
    matched = [
        details[(model, task, condition, split_language(row))][int(row["id"])]
        for row in rows
    ]
    if task == "schema":
        return sum(float(row["similarity"]) for row in matched) / len(matched)
    correct = sum(int(row["correct"]) for row in matched)
    total = sum(int(row["total"]) for row in matched)
    return correct / total


def write_outputs(
    selected: list[dict[str, str]],
    excluded: list[dict[str, object]],
    details: dict[tuple[str, str, str, str], dict[int, dict[str, str]]],
) -> None:
    OUTPUT.mkdir(parents=True, exist_ok=True)
    result_rows = []
    for model, label in MODELS:
        result = {"model": label}
        for task in ("schema", "alignment", "infill"):
            filled = score(selected, details, model, task, "filled")
            template = score(selected, details, model, task, "empty")
            result[f"{task}_filled"] = filled
            result[f"{task}_template"] = template
            result[f"{task}_delta"] = template - filled
        result_rows.append(result)

    average = {"model": "Task Average"}
    for task in ("schema", "alignment", "infill"):
        for column in ("filled", "template", "delta"):
            key = f"{task}_{column}"
            average[key] = sum(row[key] for row in result_rows) / len(result_rows)

    fieldnames = list(result_rows[0])
    with (OUTPUT / "table3_source_filtered.csv").open(
        "w", encoding="utf-8", newline=""
    ) as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows([*result_rows, average])

    with (OUTPUT / "selected_templates.csv").open(
        "w", encoding="utf-8", newline=""
    ) as handle:
        writer = csv.DictWriter(handle, fieldnames=list(selected[0]))
        writer.writeheader()
        writer.writerows(selected)

    (OUTPUT / "summary.json").write_text(
        json.dumps(
            {
                "filter": "government and selected public-institutional source domains",
                "template_count": len(selected),
                "coverage_exclusions": excluded,
                "image_reference_rows_included": False,
                "metric_protocol": "EMNLP 2026 canonical",
                "rows": [*result_rows, average],
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )


def main() -> None:
    details = load_details()
    selected, excluded = common_rows(candidate_rows(), details)
    write_outputs(selected, excluded, details)
    print(f"Wrote {OUTPUT} for {len(selected)} templates ({len(excluded)} excluded).")


if __name__ == "__main__":
    main()
