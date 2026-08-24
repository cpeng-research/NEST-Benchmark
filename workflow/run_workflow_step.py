from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]

STEP_SCRIPTS = {
    "02-filled-json-a": "workflow/2-filled_json-a/step2_fill_json.py",
    "03-filled-html-a": "workflow/3-filled_html-a/step3_fill_html.py",
    "04-context-a": "workflow/4-context-a/step4_gen_context.py",
    "05-placeholder-html-a": "workflow/5-ph_html-a/step5_gen_ph_html.py",
    "06-meta-a": "workflow/6-meta-a/step6_gen_meta.py",
    "07-html-b": "workflow/7-html-b/step7_gen_html_b.py",
    "08-json-b": "workflow/8-json-b/step8_gen_json_b.py",
    "09-png-a": "workflow/render_html_to_png.py",
}

RENDER_STEPS = {"09-png-a"}
MODEL_STEPS = set(STEP_SCRIPTS) - RENDER_STEPS
WORKER_STEPS = {"04-context-a", "07-html-b", "08-json-b", "09-png-a"}
FORCE_STEPS = {"07-html-b", "08-json-b"}


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run one reproduction-package workflow step with an optional ID range."
    )
    parser.add_argument("--step", required=True, choices=STEP_SCRIPTS)
    parser.add_argument("--lang", default="en", choices=["en", "zh", "both"])
    parser.add_argument("--start_id", default="", help="Optional start ID. Empty means no lower bound.")
    parser.add_argument("--end_id", default="", help="Optional end ID. Empty means no upper bound.")
    parser.add_argument("--model", default="", help="Optional model for steps that support --model.")
    parser.add_argument("--workers", default="", help="Optional worker/concurrency count for supported steps.")
    parser.add_argument(
        "--update-mode",
        default="check",
        choices=["check", "missing-only", "force"],
        help="check=default update checks; missing-only=skip update checks; force=reprocess where supported.",
    )
    args = parser.parse_args()

    script = PROJECT_ROOT / STEP_SCRIPTS[args.step]
    cmd = [sys.executable, str(script)]

    if args.lang != "both":
        cmd += ["--lang", args.lang]
    add_optional_int(cmd, "--start_id", args.start_id)
    add_optional_int(cmd, "--end_id", args.end_id)

    if args.step in RENDER_STEPS:
        cmd += ["--update-mode", args.update_mode]
    elif args.update_mode == "missing-only":
        cmd.append("--no-check-updates")
    elif args.update_mode == "force" and args.step in FORCE_STEPS:
        cmd.append("--force")

    model = args.model.strip()
    if model and model != "script-default" and args.step in MODEL_STEPS:
        cmd += ["--model", model]
    if args.workers.strip() and args.step in WORKER_STEPS:
        if args.step == "04-context-a":
            worker_arg = "--max-concurrency"
        elif args.step in RENDER_STEPS:
            worker_arg = "--workers"
        else:
            worker_arg = "--max-workers"
        add_optional_int(cmd, worker_arg, args.workers)

    if args.step == "09-png-a":
        for preset in ("empty", "filled"):
            report = f"workflow/9-png-a/render_audit_{preset}.json"
            render_cmd = [
                *cmd,
                "--preset",
                preset,
                "--crop-to-content",
                "--audit-report",
                report,
                "--fail-on-audit",
            ]
            print("Executing:", " ".join(render_cmd), flush=True)
            result = subprocess.run(render_cmd, cwd=PROJECT_ROOT)
            if result.returncode:
                raise SystemExit(result.returncode)
        return

    print("Executing:", " ".join(cmd), flush=True)
    raise SystemExit(subprocess.run(cmd, cwd=PROJECT_ROOT).returncode)


def add_optional_int(cmd: list[str], flag: str, value: str) -> None:
    value = value.strip()
    if not value:
        return
    try:
        int(value)
    except ValueError as exc:
        raise SystemExit(f"{flag} must be an integer, got: {value}") from exc
    cmd += [flag, value]


if __name__ == "__main__":
    main()
