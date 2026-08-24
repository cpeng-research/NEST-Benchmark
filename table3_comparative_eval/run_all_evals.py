from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

if __package__ is None or __package__ == "":
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from table3_comparative_eval.config import SUPPORTED_CONDITIONS, SUPPORTED_MODELS, SUPPORTED_TASKS
from table3_comparative_eval.metrics.infill import SOURCE_FAITHFUL_MATCHER, SUPPORTED_INFILL_MATCHERS


def main() -> None:
    parser = argparse.ArgumentParser(description="Run all Table 3 evaluators for existing predictions.")
    parser.add_argument("--lang", default="en", choices=["en", "zh"])
    parser.add_argument("--models", nargs="*", default=list(SUPPORTED_MODELS))
    parser.add_argument("--schema_metric", choices=["py_tree", "py_fast", "cpp"], default="py_tree")
    parser.add_argument(
        "--infill_matcher",
        "--infill-matcher",
        choices=SUPPORTED_INFILL_MATCHERS,
        default=SOURCE_FAITHFUL_MATCHER,
    )
    args = parser.parse_args()

    scripts = {
        "schema": "table3_comparative_eval/eval_schema.py",
        "alignment": "table3_comparative_eval/eval_alignment.py",
        "infill": "table3_comparative_eval/eval_infill.py",
    }
    for model in args.models:
        for task in SUPPORTED_TASKS:
            for condition in SUPPORTED_CONDITIONS:
                cmd = [
                    sys.executable,
                    scripts[task],
                    "--condition",
                    condition,
                    "--model",
                    model,
                    "--lang",
                    args.lang,
                ]
                if task == "schema":
                    cmd += ["--metric", args.schema_metric]
                elif task == "infill":
                    cmd += ["--matcher", args.infill_matcher]
                print(" ".join(cmd))
                subprocess.run(cmd, check=True)
    subprocess.run([
        sys.executable,
        "table3_comparative_eval/aggregate_table3.py",
        "--lang",
        args.lang,
        "--schema_metric",
        args.schema_metric,
        "--infill_matcher",
        args.infill_matcher,
        "--models",
        *args.models,
    ], check=True)


if __name__ == "__main__":
    main()
