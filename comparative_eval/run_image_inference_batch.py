from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import time
from pathlib import Path
from typing import Any

if __package__ is None or __package__ == "":
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from comparative_eval.config import SUPPORTED_CONDITIONS, SUPPORTED_TASKS, TABLE3_ROOT
from comparative_eval.prompts import TABLE3_SYSTEM_PROMPT
from comparative_eval.run_image_inference import (
    ALL_CONDITIONS,
    ALL_LANGS,
    ALL_TASKS,
    LANGS,
    ImageJob,
    collect_jobs,
    image_data_url,
    response_usage,
    run_evaluators,
)
from comparative_eval.run_inference import optional_int, should_skip_prediction, write_prediction
from comparative_eval.utils.io_utils import ensure_dir, read_json, write_json
from comparative_eval.utils.openai_utils import create_client, extract_text


BATCH_ENDPOINTS = {
    "responses": "/v1/responses",
    "chat_completions": "/v1/chat/completions",
}
TERMINAL_BATCH_STATUSES = {"completed", "failed", "expired", "cancelled"}


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Prepare, submit, poll, and download OpenAI Batch API jobs for Table 3 "
            "image-based multimodal inference. Downloaded results are written to "
            "the normal comparative_eval/predictions tree."
        )
    )
    parser.add_argument("--mode", choices=["prepare", "submit", "poll", "download", "all"], default="submit")
    parser.add_argument("--task", default="all", choices=ALL_TASKS)
    parser.add_argument("--condition", default="both", choices=ALL_CONDITIONS)
    parser.add_argument("--lang", default="both", choices=ALL_LANGS)
    parser.add_argument("--api_model", "--api-model", dest="api_model", default="gpt-5.4-mini")
    parser.add_argument(
        "--prediction_model_name",
        "--prediction-model-name",
        dest="prediction_model_name",
        default=None,
        help="Directory/evaluation label. Defaults to '<api_model>-image'.",
    )
    parser.add_argument("--start_id", type=optional_int, default=None)
    parser.add_argument("--end_id", type=optional_int, default=None)
    parser.add_argument("--limit", type=int, default=0, help="Per task/condition/lang limit.")
    parser.add_argument("--overwrite", action="store_true")
    parser.add_argument(
        "--detail",
        choices=["low", "high", "auto", "original"],
        default="high",
        help="OpenAI image detail level.",
    )
    parser.add_argument(
        "--api_surface",
        "--api-surface",
        dest="api_surface",
        choices=sorted(BATCH_ENDPOINTS),
        default="responses",
        help="Batch API endpoint to use. Batch requests cannot auto-fallback across endpoints.",
    )
    parser.add_argument(
        "--max_output_tokens",
        "--max-output-tokens",
        dest="max_output_tokens",
        type=int,
        default=0,
        help="Optional output cap. 0 omits the parameter.",
    )
    parser.add_argument("--batch_dir", "--batch-dir", dest="batch_dir", default=str(TABLE3_ROOT / "batches"))
    parser.add_argument(
        "--batch_name",
        "--batch-name",
        dest="batch_name",
        default="",
        help="Base filename for JSONL shards and the manifest. Defaults to a timestamped name.",
    )
    parser.add_argument(
        "--manifest",
        default="",
        help="Existing or desired manifest path. Required for later poll/download runs unless --batch_id is used for poll.",
    )
    parser.add_argument("--batch_id", "--batch-id", dest="batch_id", default="", help="Poll a single batch without a manifest.")
    parser.add_argument("--wait", action="store_true", help="Poll until all submitted shards reach a terminal status.")
    parser.add_argument("--poll_interval", "--poll-interval", dest="poll_interval", type=float, default=60.0)
    parser.add_argument(
        "--max_jsonl_mb",
        "--max-jsonl-mb",
        dest="max_jsonl_mb",
        type=float,
        default=50.0,
        help="Maximum approximate JSONL shard size before starting another Batch input file.",
    )
    parser.add_argument("--dry_run", "--dry-run", dest="dry_run", action="store_true")
    parser.add_argument("--evaluate", action="store_true", help="Run existing Table 3 evaluators after downloading outputs.")
    parser.add_argument(
        "--schema_metric",
        "--schema-metric",
        dest="schema_metric",
        choices=["py_tree", "py_fast", "cpp"],
        default="py_tree",
    )
    parser.add_argument("--cpp_timeout", "--cpp-timeout", dest="cpp_timeout", type=float, default=10.0)
    parser.add_argument(
        "--resume_from_details",
        "--resume-from-details",
        dest="resume_from_details",
        action="store_true",
    )
    args = parser.parse_args()

    if args.max_output_tokens < 0:
        parser.error("--max_output_tokens cannot be negative.")
    if args.poll_interval <= 0:
        parser.error("--poll_interval must be positive.")
    if args.max_jsonl_mb <= 0:
        parser.error("--max_jsonl_mb must be positive.")

    prediction_model_name = args.prediction_model_name or f"{args.api_model}-image"
    manifest: dict[str, Any] | None = None
    manifest_path: Path | None = None

    if args.mode in {"prepare", "submit", "all"}:
        if args.mode in {"submit", "all"} and args.manifest and Path(args.manifest).exists():
            manifest_path = Path(args.manifest)
            manifest = read_json(manifest_path)
            print(f"Loaded existing manifest: {manifest_path}")
        else:
            manifest, manifest_path = prepare_batch_manifest(args, prediction_model_name)
        if args.mode == "prepare" or args.dry_run:
            return

    if args.mode in {"submit", "all"}:
        assert manifest is not None and manifest_path is not None
        if not manifest.get("jobs"):
            print("No pending jobs to submit.")
            return
        manifest = submit_batch_manifest(args, manifest, manifest_path)
        if args.mode == "submit":
            return

    if args.mode in {"poll", "download"}:
        manifest, manifest_path = load_manifest_for_status(args)

    assert manifest is not None
    assert manifest_path is not None or args.batch_id

    wait = args.wait or args.mode == "all"
    manifest = poll_batch_manifest(args, manifest, manifest_path, wait=wait)

    if args.mode == "poll":
        return

    if not any(shard.get("status") == "completed" for shard in manifest.get("shards", [])):
        print("No completed batch shards are ready to download.")
        return

    manifest = download_and_write_predictions(args, manifest, manifest_path)
    if args.evaluate:
        selected_tasks, selected_conditions, selected_langs = selections_from_manifest(manifest)
        run_evaluators(args, manifest["prediction_model_name"], selected_tasks, selected_conditions, selected_langs)


def prepare_batch_manifest(args: argparse.Namespace, prediction_model_name: str) -> tuple[dict[str, Any], Path]:
    selected_tasks = SUPPORTED_TASKS if args.task == "all" else (args.task,)
    selected_conditions = SUPPORTED_CONDITIONS if args.condition == "both" else (args.condition,)
    selected_langs = LANGS if args.lang == "both" else (args.lang,)

    jobs = collect_jobs(
        tasks=selected_tasks,
        conditions=selected_conditions,
        langs=selected_langs,
        prediction_model_name=prediction_model_name,
        start_id=args.start_id,
        end_id=args.end_id,
        limit=args.limit,
        overwrite=args.overwrite,
        dry_run=args.dry_run,
    )
    print(
        f"batch api_model={args.api_model} prediction_model_name={prediction_model_name} "
        f"endpoint={BATCH_ENDPOINTS[args.api_surface]} jobs={len(jobs)}"
    )
    if args.dry_run:
        for job in jobs[:20]:
            print(job_custom_id(job), job.image_path, "->", job.out_file)
        if len(jobs) > 20:
            print(f"... {len(jobs) - 20} more jobs")
        return {}, Path(args.manifest) if args.manifest else Path()

    batch_dir = ensure_dir(Path(args.batch_dir))
    batch_name = safe_batch_name(args.batch_name) if args.batch_name.strip() else default_batch_name(args, prediction_model_name)
    manifest_path = Path(args.manifest) if args.manifest else batch_dir / f"{batch_name}.manifest.json"
    ensure_dir(manifest_path.parent)

    manifest: dict[str, Any] = {
        "version": 1,
        "created_at": now_string(),
        "api_model": args.api_model,
        "prediction_model_name": prediction_model_name,
        "api_surface": args.api_surface,
        "endpoint": BATCH_ENDPOINTS[args.api_surface],
        "image_detail": args.detail,
        "max_output_tokens": args.max_output_tokens,
        "task_arg": args.task,
        "condition_arg": args.condition,
        "lang_arg": args.lang,
        "selected_tasks": list(selected_tasks),
        "selected_conditions": list(selected_conditions),
        "selected_langs": list(selected_langs),
        "start_id": args.start_id,
        "end_id": args.end_id,
        "limit": args.limit,
        "overwrite": args.overwrite,
        "max_jsonl_mb": args.max_jsonl_mb,
        "manifest_path": str(manifest_path),
        "jobs": [],
        "shards": [],
    }
    write_jsonl_shards(args, manifest, jobs, batch_dir, batch_name)
    write_json(manifest_path, manifest)
    print(f"Prepared {len(manifest['jobs'])} requests in {len(manifest['shards'])} shard(s).")
    print(f"Manifest: {manifest_path}")
    for shard in manifest["shards"]:
        print(f"  shard {shard['index']}: {shard['request_count']} requests, {format_bytes(shard['bytes'])}, {shard['jsonl_path']}")
    return manifest, manifest_path


def write_jsonl_shards(
    args: argparse.Namespace,
    manifest: dict[str, Any],
    jobs: list[ImageJob],
    batch_dir: Path,
    batch_name: str,
) -> None:
    max_bytes = int(args.max_jsonl_mb * 1024 * 1024)
    shard_index = -1
    shard_file = None
    shard_path: Path | None = None
    shard_bytes = 0
    shard_count = 0

    def open_next_shard() -> None:
        nonlocal shard_index, shard_file, shard_path, shard_bytes, shard_count
        if shard_file is not None:
            shard_file.close()
            manifest["shards"][-1]["bytes"] = shard_bytes
            manifest["shards"][-1]["request_count"] = shard_count
        shard_index += 1
        shard_path = batch_dir / f"{batch_name}.part{shard_index:03d}.jsonl"
        shard_file = shard_path.open("wb")
        shard_bytes = 0
        shard_count = 0
        manifest["shards"].append(
            {
                "index": shard_index,
                "jsonl_path": str(shard_path),
                "request_count": 0,
                "bytes": 0,
            }
        )

    for job in jobs:
        line = json.dumps(batch_request_line(args, job), ensure_ascii=False, separators=(",", ":")) + "\n"
        data = line.encode("utf-8")
        if shard_file is None:
            open_next_shard()
        elif shard_bytes > 0 and shard_bytes + len(data) > max_bytes:
            open_next_shard()
        assert shard_file is not None
        shard_file.write(data)
        shard_bytes += len(data)
        shard_count += 1
        manifest["jobs"].append(job_manifest_record(job, shard_index))

    if shard_file is not None:
        shard_file.close()
        manifest["shards"][-1]["bytes"] = shard_bytes
        manifest["shards"][-1]["request_count"] = shard_count


def submit_batch_manifest(args: argparse.Namespace, manifest: dict[str, Any], manifest_path: Path) -> dict[str, Any]:
    client = create_client()
    for shard in manifest.get("shards", []):
        if shard.get("batch_id"):
            print(f"Shard {shard['index']} already submitted as {shard['batch_id']}; skipping.")
            continue
        jsonl_path = Path(shard["jsonl_path"])
        if not jsonl_path.exists():
            raise FileNotFoundError(f"Missing JSONL shard: {jsonl_path}")
        print(f"Uploading shard {shard['index']} ({shard['request_count']} requests, {format_bytes(jsonl_path.stat().st_size)})")
        try:
            input_file = upload_batch_file(client, jsonl_path, manifest["api_model"])
        except Exception as exc:
            shard.update(
                {
                    "upload_error": f"{exc.__class__.__name__}: {exc}",
                    "upload_error_at": now_string(),
                }
            )
            write_json(manifest_path, manifest)
            if is_request_too_large_error(exc):
                raise RuntimeError(
                    f"Batch shard {shard['index']} is too large for the current /v1/files endpoint "
                    f"({format_bytes(jsonl_path.stat().st_size)}). Re-run this command with a smaller "
                    "--max_jsonl_mb value, for example 50 or 25. The current failed manifest was "
                    f"updated at {manifest_path}."
                ) from exc
            if is_missing_model_name_error(exc):
                raise RuntimeError(
                    "The current OPENAI_BASE_URL rejected /v1/files uploads because it requires "
                    "a model name, even after retrying proxy-compatible model parameters. This "
                    "usually means the OpenAI-compatible proxy does not support the Files/Batch "
                    "API correctly. Use the official OpenAI API endpoint for batch submission, or ask the "
                    "proxy provider how to pass model names for /v1/files."
                ) from exc
            raise
        batch = client.batches.create(
            input_file_id=input_file.id,
            endpoint=manifest["endpoint"],
            completion_window="24h",
            metadata={
                "script": "table3_image_batch",
                "manifest": manifest_path.name[:64],
                "part": str(shard["index"]),
            },
        )
        shard.update(
            {
                "input_file_id": input_file.id,
                "batch_id": batch.id,
                "status": getattr(batch, "status", None),
                "submitted_at": now_string(),
            }
        )
        update_shard_from_batch(shard, batch)
        write_json(manifest_path, manifest)
        print(f"Submitted shard {shard['index']}: batch_id={batch.id} status={shard.get('status')}")
    manifest["updated_at"] = now_string()
    write_json(manifest_path, manifest)
    print(f"Updated manifest: {manifest_path}")
    return manifest


def upload_batch_file(client: Any, jsonl_path: Path, api_model: str) -> Any:
    try:
        with jsonl_path.open("rb") as f:
            return client.files.create(file=f, purpose="batch")
    except Exception as exc:
        if not is_missing_model_name_error(exc):
            raise
        print(
            "File upload endpoint requires a model field; retrying with "
            f"extra_body model={api_model}.",
            file=sys.stderr,
        )
    try:
        with jsonl_path.open("rb") as f:
            return client.files.create(file=f, purpose="batch", extra_body={"model": api_model})
    except Exception as exc:
        if not is_missing_model_name_error(exc):
            raise
        print(
            "File upload still requires a model field; retrying with "
            f"extra_query model={api_model}.",
            file=sys.stderr,
        )
    with jsonl_path.open("rb") as f:
        return client.files.create(file=f, purpose="batch", extra_query={"model": api_model})


def is_request_too_large_error(exc: Exception) -> bool:
    message = str(exc).lower()
    status_code = getattr(exc, "status_code", None)
    return status_code == 413 or "413" in message or "request entity too large" in message


def is_missing_model_name_error(exc: Exception) -> bool:
    message = str(exc).lower()
    status_code = getattr(exc, "status_code", None)
    return status_code == 400 and (
        "未指定模型名称" in str(exc)
        or "模型名称不能为空" in str(exc)
        or "model" in message and ("empty" in message or "required" in message or "missing" in message)
    )


def load_manifest_for_status(args: argparse.Namespace) -> tuple[dict[str, Any], Path | None]:
    if args.manifest:
        path = Path(args.manifest)
        if not path.exists():
            raise FileNotFoundError(f"Manifest not found: {path}")
        return read_json(path), path
    if args.batch_id and args.mode == "poll":
        return {
            "version": 1,
            "created_at": now_string(),
            "api_model": args.api_model,
            "prediction_model_name": args.prediction_model_name or f"{args.api_model}-image",
            "api_surface": args.api_surface,
            "endpoint": BATCH_ENDPOINTS[args.api_surface],
            "jobs": [],
            "shards": [{"index": 0, "batch_id": args.batch_id}],
        }, None
    raise ValueError("--manifest is required for poll/download unless --batch_id is used with --mode poll.")


def poll_batch_manifest(
    args: argparse.Namespace,
    manifest: dict[str, Any],
    manifest_path: Path | None,
    wait: bool,
) -> dict[str, Any]:
    client = create_client()
    while True:
        terminal = True
        for shard in manifest.get("shards", []):
            batch_id = shard.get("batch_id")
            if not batch_id:
                terminal = False
                print(f"Shard {shard.get('index')} has not been submitted.")
                continue
            batch = client.batches.retrieve(batch_id)
            update_shard_from_batch(shard, batch)
            status = shard.get("status")
            terminal = terminal and status in TERMINAL_BATCH_STATUSES
            print(
                f"shard={shard.get('index')} batch_id={batch_id} status={status} "
                f"counts={shard.get('request_counts')}"
            )
        manifest["updated_at"] = now_string()
        if manifest_path is not None:
            write_json(manifest_path, manifest)
            print(f"Updated manifest: {manifest_path}")
        if terminal or not wait:
            return manifest
        time.sleep(args.poll_interval)


def download_and_write_predictions(
    args: argparse.Namespace,
    manifest: dict[str, Any],
    manifest_path: Path | None,
) -> dict[str, Any]:
    client = create_client()
    job_by_custom_id = {job["custom_id"]: job for job in manifest.get("jobs", [])}
    total_written = 0
    total_failed = 0
    total_skipped_existing = 0

    for shard in manifest.get("shards", []):
        if shard.get("status") != "completed":
            print(f"Skipping shard {shard.get('index')} with status={shard.get('status')}")
            continue
        output_file_id = shard.get("output_file_id")
        if not output_file_id:
            print(f"Skipping shard {shard.get('index')}: completed batch has no output_file_id")
            continue
        output_path = Path(shard.get("output_jsonl_path") or batch_output_path(manifest, shard, "output"))
        download_file_once(client, output_file_id, output_path)
        shard["output_jsonl_path"] = str(output_path)

        error_file_id = shard.get("error_file_id")
        if error_file_id:
            error_path = Path(shard.get("error_jsonl_path") or batch_output_path(manifest, shard, "error"))
            download_file_once(client, error_file_id, error_path)
            shard["error_jsonl_path"] = str(error_path)

        written, failed, skipped_existing = process_output_jsonl(args, manifest, output_path, job_by_custom_id)
        total_written += written
        total_failed += failed
        total_skipped_existing += skipped_existing
        shard["downloaded_at"] = now_string()
        shard["written_predictions"] = written
        shard["failed_results"] = failed
        shard["skipped_existing_predictions"] = skipped_existing

    manifest["downloaded_at"] = now_string()
    manifest["written_predictions"] = total_written
    manifest["failed_results"] = total_failed
    manifest["skipped_existing_predictions"] = total_skipped_existing
    if manifest_path is not None:
        write_json(manifest_path, manifest)
        print(f"Updated manifest: {manifest_path}")
    print(
        f"Batch output processed: written={total_written} "
        f"failed={total_failed} skipped_existing={total_skipped_existing}"
    )
    return manifest


def process_output_jsonl(
    args: argparse.Namespace,
    manifest: dict[str, Any],
    output_path: Path,
    job_by_custom_id: dict[str, dict[str, Any]],
) -> tuple[int, int, int]:
    written = 0
    failed = 0
    skipped_existing = 0
    with output_path.open("r", encoding="utf-8") as f:
        for line_no, line in enumerate(f, start=1):
            if not line.strip():
                continue
            record = json.loads(line)
            custom_id = record.get("custom_id")
            job = job_by_custom_id.get(custom_id)
            if job is None:
                failed += 1
                print(f"{output_path}:{line_no}: unknown custom_id={custom_id}", file=sys.stderr)
                continue

            response = record.get("response") or {}
            line_error = record.get("error")
            status_code = response.get("status_code")
            body = response.get("body")
            if line_error or not isinstance(status_code, int) or status_code < 200 or status_code >= 300 or not body:
                failed += 1
                print(f"{custom_id} failed status={status_code} error={line_error or response.get('error')}", file=sys.stderr)
                continue

            text = extract_text(body).strip()
            if not text:
                failed += 1
                print(f"{custom_id} failed: empty response text", file=sys.stderr)
                continue

            out_file = Path(job["out_file"])
            if should_skip_prediction(out_file, args.overwrite):
                skipped_existing += 1
                continue

            write_prediction(
                out_file,
                {
                    "sample_id": job["sample_id"],
                    "model": manifest["prediction_model_name"],
                    "api_model": manifest["api_model"],
                    "backend": "openai_batch",
                    "api_surface": manifest["api_surface"],
                    "input_modality": "image",
                    "task": job["task"],
                    "condition": job["condition"],
                    "lang": job["lang"],
                    "image_path": job["image_path"],
                    "image_detail": manifest["image_detail"],
                    "raw_response": text,
                    "created_at": now_string(),
                    "attempts": 1,
                    "batch_id": record_batch_id(manifest, job),
                    "batch_custom_id": custom_id,
                    "batch_request_id": response.get("request_id"),
                    "batch_response_id": body.get("id") if isinstance(body, dict) else None,
                    "batch_status_code": status_code,
                    "usage": response_usage(body),
                },
            )
            written += 1
    return written, failed, skipped_existing


def batch_request_line(args: argparse.Namespace, job: ImageJob) -> dict[str, Any]:
    return {
        "custom_id": job_custom_id(job),
        "method": "POST",
        "url": BATCH_ENDPOINTS[args.api_surface],
        "body": request_body(args, job),
    }


def request_body(args: argparse.Namespace, job: ImageJob) -> dict[str, Any]:
    if args.api_surface == "responses":
        body: dict[str, Any] = {
            "model": args.api_model,
            "instructions": TABLE3_SYSTEM_PROMPT,
            "input": [
                {
                    "role": "user",
                    "content": [
                        {"type": "input_text", "text": job.prompt},
                        {
                            "type": "input_image",
                            "image_url": image_data_url(job.image_path),
                            "detail": args.detail,
                        },
                    ],
                }
            ],
        }
        if args.max_output_tokens:
            body["max_output_tokens"] = args.max_output_tokens
        return body

    body = {
        "model": args.api_model,
        "messages": [
            {"role": "system", "content": TABLE3_SYSTEM_PROMPT},
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": job.prompt},
                    {
                        "type": "image_url",
                        "image_url": {
                            "url": image_data_url(job.image_path),
                            "detail": args.detail,
                        },
                    },
                ],
            },
        ],
    }
    if args.max_output_tokens:
        body["max_completion_tokens"] = args.max_output_tokens
    return body


def job_manifest_record(job: ImageJob, shard_index: int) -> dict[str, Any]:
    return {
        "custom_id": job_custom_id(job),
        "shard_index": shard_index,
        "task": job.task,
        "condition": job.condition,
        "lang": job.lang,
        "sample_id": job.sample_id,
        "image_path": str(job.image_path),
        "out_file": str(job.out_file),
        "prompt_sha256": hashlib.sha256(job.prompt.encode("utf-8")).hexdigest(),
    }


def job_custom_id(job: ImageJob) -> str:
    return f"{job.task}__{job.condition}__{job.lang}__{job.sample_id}"


def update_shard_from_batch(shard: dict[str, Any], batch: Any) -> None:
    plain = object_to_plain(batch)
    for key in (
        "id",
        "status",
        "created_at",
        "in_progress_at",
        "expires_at",
        "finalizing_at",
        "completed_at",
        "failed_at",
        "expired_at",
        "cancelled_at",
        "output_file_id",
        "error_file_id",
        "request_counts",
        "errors",
    ):
        if key in plain and plain[key] is not None:
            target_key = "batch_id" if key == "id" else key
            shard[target_key] = plain[key]


def object_to_plain(value: Any) -> Any:
    if hasattr(value, "model_dump"):
        return value.model_dump()
    if hasattr(value, "dict"):
        return value.dict()
    if isinstance(value, dict):
        return value
    return {
        key: getattr(value, key)
        for key in dir(value)
        if not key.startswith("_") and not callable(getattr(value, key, None))
    }


def download_file_once(client: Any, file_id: str, path: Path) -> None:
    if path.exists() and path.stat().st_size > 0:
        print(f"Using existing downloaded file: {path}")
        return
    ensure_dir(path.parent)
    content = client.files.content(file_id)
    if hasattr(content, "write_to_file"):
        content.write_to_file(str(path))
    else:
        path.write_bytes(binary_response_bytes(content))
    print(f"Downloaded {file_id} -> {path}")


def binary_response_bytes(content: Any) -> bytes:
    if isinstance(content, bytes):
        return content
    if hasattr(content, "read"):
        return content.read()
    data = getattr(content, "content", None)
    if isinstance(data, bytes):
        return data
    if isinstance(data, str):
        return data.encode("utf-8")
    return bytes(content)


def batch_output_path(manifest: dict[str, Any], shard: dict[str, Any], kind: str) -> Path:
    manifest_path = Path(manifest.get("manifest_path") or TABLE3_ROOT / "batches" / "batch.manifest.json")
    stem = manifest_path.name.removesuffix(".manifest.json")
    suffix = "output" if kind == "output" else "error"
    return manifest_path.parent / f"{stem}.part{int(shard['index']):03d}.{suffix}.jsonl"


def selections_from_manifest(manifest: dict[str, Any]) -> tuple[tuple[str, ...], tuple[str, ...], tuple[str, ...]]:
    return (
        tuple(manifest.get("selected_tasks") or SUPPORTED_TASKS),
        tuple(manifest.get("selected_conditions") or SUPPORTED_CONDITIONS),
        tuple(manifest.get("selected_langs") or LANGS),
    )


def record_batch_id(manifest: dict[str, Any], job: dict[str, Any]) -> str | None:
    shard_index = job.get("shard_index")
    for shard in manifest.get("shards", []):
        if shard.get("index") == shard_index:
            return shard.get("batch_id")
    return None


def default_batch_name(args: argparse.Namespace, prediction_model_name: str) -> str:
    parts = [
        "table3_image",
        safe_batch_name(args.api_model),
        safe_batch_name(prediction_model_name),
        args.task,
        args.condition,
        args.lang,
        time.strftime("%Y%m%d_%H%M%S"),
    ]
    return "_".join(part for part in parts if part)


def safe_batch_name(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.=+-]+", "_", value.strip()).strip("_") or "batch"


def format_bytes(size: int) -> str:
    units = ("B", "KB", "MB", "GB")
    value = float(size)
    for unit in units:
        if value < 1024 or unit == units[-1]:
            return f"{value:.1f}{unit}" if unit != "B" else f"{int(value)}B"
        value /= 1024
    return f"{size}B"


def now_string() -> str:
    return time.strftime("%Y-%m-%d %H:%M:%S")


if __name__ == "__main__":
    main()
