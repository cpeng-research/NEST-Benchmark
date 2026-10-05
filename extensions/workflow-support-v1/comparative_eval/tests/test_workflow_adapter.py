"""Offline checks against the original metrics, including unchanged real samples."""

from copy import deepcopy
import importlib.util
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch


SCRIPT = Path(__file__).resolve().parents[1] / "run_workflow.py"
SPEC = importlib.util.spec_from_file_location("workflow_adapter", SCRIPT)
adapter = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(adapter)
ROOT = adapter.benchmark_root()
CORE = adapter.load_core(ROOT)
LABEL = "Prénom 中文\u2028suite\u2029fin\u0085"
EMPTY = f'<table><tr><td>{LABEL}</td><td></td></tr></table>'
FILLED = f'<table><tr><td>{LABEL}</td><td>Zoé 测试</td></tr></table>'
PLACEHOLDER = f'<table><tr><td>{LABEL}</td><td>[{LABEL}]</td></tr></table>'
ALIGNMENT = f'<table><tr><td>{LABEL}</td><td><input name="{LABEL}" value="placeholder"></td></tr></table>'


class WorkflowAdapterTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.workflow = self.base / "overlay" / "workflow"
        self.predictions = self.base / "predictions"
        self.make_sample(self.workflow)

    def make_sample(self, root, lang="fr", number=1):
        contents = {
            "html_empty": EMPTY, "html_filled": FILLED,
            "json_empty": {LABEL: ""}, "json_filled": {LABEL: "Zoé 测试"},
            "context": "Veuillez écrire Zoé 测试.\r\nDeuxième ligne\u2028troisième.",
            "placeholder_html": PLACEHOLDER,
            "meta": [{"key": LABEL, "type": "SI", "label_info": {"row": 0, "col": 0},
                      "placeholder_offset": {"rows": 0, "cols": 1}}],
        }
        for key, value in contents.items():
            stage, suffix = adapter.STAGES[key]
            path = root / stage / f"data_{lang}" / f"{number}{suffix}"
            path.parent.mkdir(parents=True, exist_ok=True)
            text = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False)
            path.write_bytes(text.encode("utf-8"))

    def prepare(self, tasks=adapter.TASKS, conditions=adapter.CONDITIONS, metric="py_tree"):
        samples = adapter.discover([self.workflow])
        requests = adapter.prepare(CORE, samples, "test/model-1", tasks, conditions, metric)
        return samples, requests

    def envelope(self, job, raw, **extra):
        path = adapter.prediction_path(self.predictions, job)
        path.parent.mkdir(parents=True, exist_ok=True)
        record = {"sample_id": job["sample_id"], "model": job["model"], "raw_response": raw}
        record.update(extra)
        path.write_text(json.dumps(record, ensure_ascii=False), encoding="utf-8")
        return path

    def reference(self, sample, job):
        if job["task"] == "schema":
            return adapter.read_source(sample, "json_" + job["condition"])
        return ALIGNMENT if job["task"] == "alignment" else FILLED

    def test_prompt_parity_full_hashes_no_gold_leak(self):
        samples, requests = self.prepare()
        self.assertEqual(len(requests["jobs"]), 6)
        sample = samples[0]
        for job in requests["jobs"]:
            self.assertEqual(job["status"], "ready")
            html = adapter.read_source(sample, "html_" + job["condition"])
            prompt_fn = getattr(CORE.prompts, job["task"] + "_prompt")
            expected = (prompt_fn(html, adapter.read_source(sample, "context"), job["condition"])
                        if job["task"] == "infill" else prompt_fn(html, job["condition"]))
            self.assertEqual(job["messages"], [{"role": "system", "content": CORE.prompts.TABLE3_SYSTEM_PROMPT},
                                               {"role": "user", "content": expected}])
            self.assertEqual(len(job["source_hashes"]), 7)
            self.assertTrue(all(len(value) == 64 for value in job["source_hashes"].values()))
            if job["condition"] == "empty" and job["task"] != "infill":
                self.assertNotIn("Zoé", expected)

    def test_original_prediction_layout_and_unicode_roundtrip(self):
        samples, requests = self.prepare()
        for job in requests["jobs"]:
            path = self.envelope(job, self.reference(samples[0], job), request=job)
            self.assertEqual(path.relative_to(self.predictions).parts,
                             (job["task"] + "_" + job["condition"], "fr", "test_model_1", "1.json"))
            self.assertIn("\u2028", json.loads(path.read_text())["raw_response"])
        result = adapter.evaluate(CORE, samples, requests, self.predictions)
        self.assertEqual([row["score"] for row in result["rows"]], [1.0] * 6)
        self.assertTrue(all(group["complete"] for group in result["summary"]))

    def test_old_envelopes_with_prepared_evidence(self):
        samples, requests = self.prepare()
        for job in requests["jobs"]:
            self.envelope(job, self.reference(samples[0], job))
        result = adapter.evaluate(CORE, samples, requests, self.predictions, requests)
        self.assertEqual([row["status"] for row in result["rows"]], ["scored"] * 6)

    def test_missing_predictions_count_all_jobs(self):
        samples, requests = self.prepare()
        result = adapter.evaluate(CORE, samples, requests, self.predictions, requests)
        self.assertEqual(len(result["rows"]), 6)
        self.assertTrue(all(row["status"] == "not_run" and row["score"] is None for row in result["rows"]))
        self.assertEqual(sum(group["job_count"] for group in result["summary"]), 6)
        self.assertTrue(all(group["score"] is None for group in result["summary"]))

    def test_source_error_retains_other_conditions(self):
        samples, _ = self.prepare()
        samples[0]["paths"]["html_empty"].write_bytes(b"")
        _, requests = self.prepare()
        self.assertEqual([j["status"] for j in requests["jobs"]], ["source_error", "ready"] * 3)
        samples[0]["paths"]["html_empty"].unlink()
        _, requests = self.prepare()
        self.assertEqual(len(requests["jobs"]), 6)

    def test_no_silent_infill_skip(self):
        samples, _ = self.prepare()
        samples[0]["paths"]["context"].unlink()
        _, requests = self.prepare()
        self.assertEqual([j["status"] for j in requests["jobs"]], ["ready"] * 4 + ["source_error"] * 2)

    def test_empty_malformed_completed_zero_not_transport_zero(self):
        for raw in ("", None, 17):
            samples, requests = self.prepare()
            for job in requests["jobs"]:
                self.envelope(job, raw)
            result = adapter.evaluate(CORE, samples, requests, self.predictions, requests)
            self.assertTrue(all(row["status"] == "model_format_failure" and row["score"] == 0 for row in result["rows"]))
            self.assertTrue(all(row["total"] == 1 for row in result["rows"]))
        for status in ("transport_error", "backend_error", "not_run"):
            for job in requests["jobs"]:
                self.envelope(job, "", status=status)
            result = adapter.evaluate(CORE, samples, requests, self.predictions, requests)
            self.assertTrue(all(row["status"] == status and row["score"] is None for row in result["rows"]))

    def test_invalid_json_envelope_with_prepared_is_zero(self):
        samples, requests = self.prepare(("schema",), ("empty",))
        path = self.envelope(requests["jobs"][0], "")
        path.write_text("not json", encoding="utf-8")
        row = adapter.evaluate(CORE, samples, requests, self.predictions, requests)["rows"][0]
        self.assertEqual((row["status"], row["score"]), ("model_format_failure", 0.0))

    def test_requires_matching_evidence_including_non_prompt_gold(self):
        samples, requests = self.prepare(("schema",), ("empty",))
        self.envelope(requests["jobs"][0], self.reference(samples[0], requests["jobs"][0]))
        row = adapter.evaluate(CORE, samples, requests, self.predictions)["rows"][0]
        self.assertEqual(row["status"], "source_mismatch")
        samples[0]["paths"]["json_filled"].write_text('{"new": "gold"}', encoding="utf-8")
        samples2, changed = self.prepare(("schema",), ("empty",))
        row = adapter.evaluate(CORE, samples2, changed, self.predictions, requests)["rows"][0]
        self.assertEqual((row["status"], row["score"]), ("source_mismatch", None))

    def test_changed_prompt_or_backend_rejected(self):
        samples, requests = self.prepare(("schema",), ("empty",))
        for key, value in (("messages", []), ("schema_metric", "cpp")):
            changed = deepcopy(requests)
            changed["jobs"][0][key] = value
            self.envelope(requests["jobs"][0], '{}')
            row = adapter.evaluate(CORE, samples, requests, self.predictions, changed)["rows"][0]
            self.assertEqual(row["status"], "source_mismatch")

    def test_envelope_identity_rejected_even_with_correct_prepared(self):
        samples, requests = self.prepare(("schema",), ("empty",))
        for key, value in (("lang", "zh"), ("task", "infill"), ("condition", "filled"),
                           ("sample_id", 2), ("model", "another"), ("sample_id", True)):
            self.envelope(requests["jobs"][0], '{}', **{key: value})
            row = adapter.evaluate(CORE, samples, requests, self.predictions, requests)["rows"][0]
            self.assertEqual(row["status"], "prediction_error")

    def test_duplicate_prepared_and_wrong_job_sets_rejected(self):
        samples, requests = self.prepare()
        for jobs in (requests["jobs"] * 2, requests["jobs"][:-1]):
            with self.assertRaises(ValueError):
                adapter.evaluate(CORE, samples, requests, self.predictions, {"jobs": jobs})

    def test_exact_overlay_dedup_and_conflict(self):
        other = self.base / "merged" / "workflow"
        shutil.copytree(self.workflow, other)
        self.assertEqual(len(adapter.discover([self.workflow, other])), 1)
        (other / "1-annotated_json/data_fr/1.json").write_text('{}', encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "Conflicting"):
            adapter.discover([self.workflow, other])

    def test_does_not_assemble_incomplete_pieces_across_roots(self):
        other = self.base / "other" / "workflow"
        shutil.copytree(self.workflow, other)
        (self.workflow / "0-html_template/data_fr/1.html").unlink()
        (other / "1-annotated_json/data_fr/1.json").unlink()
        with self.assertRaisesRegex(ValueError, "Conflicting"):
            adapter.discover([self.workflow, other])

    def test_auxiliary_only_old_id_cannot_be_reused(self):
        for key, (directory, suffix) in adapter.AUXILIARY.items():
            with self.subTest(stage=key):
                other = self.base / key / "workflow"
                path = other / directory.format(lang="fr") / f"1{suffix}"
                path.parent.mkdir(parents=True)
                path.write_bytes(b"reserved earlier output")
                with self.assertRaisesRegex(ValueError, "Conflicting"):
                    adapter.discover([self.workflow, other])
                with self.assertRaisesRegex(ValueError, "Conflicting"):
                    adapter.discover([other, self.workflow])

    def test_duplicate_core_allows_one_sided_auxiliary_and_identical_merge(self):
        other = self.base / "merged" / "workflow"
        shutil.copytree(self.workflow, other)
        for key, (directory, suffix) in adapter.AUXILIARY.items():
            path = other / directory.format(lang="fr") / f"1{suffix}"
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(key.encode())
        samples = adapter.discover([self.workflow, other])
        self.assertEqual(len(samples), 1)
        self.assertEqual(len(samples[0]["auxiliary_hashes"]), 4)
        requests = adapter.prepare(CORE, samples, "test", adapter.TASKS, adapter.CONDITIONS, "py_tree")
        self.assertEqual(len(requests["jobs"]), 6)
        self.assertEqual(len(requests["jobs"][0]["source_hashes"]), 7)
        shutil.copytree(other, self.workflow, dirs_exist_ok=True)
        self.assertEqual(len(adapter.discover([self.workflow, other])), 1)
        (other / "9-png-a/data_fr/filled/1.png").write_bytes(b"conflict")
        with self.assertRaisesRegex(ValueError, "auxiliary"):
            adapter.discover([self.workflow, other])

    def test_auxiliary_only_unrelated_ids_are_not_evaluation_jobs(self):
        other = self.base / "auxiliary" / "workflow"
        path = other / "7-html-b/data_fr/2.html"
        path.parent.mkdir(parents=True)
        path.write_text("later stage", encoding="utf-8")
        samples = adapter.discover([self.workflow, other])
        self.assertEqual([(s["lang"], s["sample_id"]) for s in samples], [("fr", 1)])

    def test_partial_core_does_not_prove_auxiliary_merge_identity(self):
        (self.workflow / "1-annotated_json/data_fr/1.json").unlink()
        other = self.base / "partial" / "workflow"
        shutil.copytree(self.workflow, other)
        path = other / "7-html-b/data_fr/1.html"
        path.parent.mkdir(parents=True)
        path.write_text("later output", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "auxiliary"):
            adapter.discover([self.workflow, other])

    def test_numeric_aliases_and_case_collisions_rejected(self):
        original = self.workflow / "0-html_template/data_fr/1.html"
        alias = original.with_name("01.html")
        alias.write_bytes(original.read_bytes())
        with self.assertRaisesRegex(ValueError, "numeric ID"):
            adapter.discover([self.workflow])
        alias.unlink()
        real_glob = Path.glob

        def duplicate_glob(path, pattern):
            if path == original.parent.resolve():
                return iter([original, original.with_name("1.HTML")])
            return real_glob(path, pattern)

        # Also test distinct case aliases on case-insensitive host filesystems.
        with patch.object(Path, "glob", duplicate_glob):
            with self.assertRaisesRegex(ValueError, "numeric ID"):
                adapter.discover([self.workflow])

    def test_arbitrary_languages_and_missing_requested_language(self):
        self.make_sample(self.workflow, "pt-BR", 3)
        self.assertEqual([(s["lang"], s["sample_id"]) for s in adapter.discover([self.workflow])], [("fr", 1), ("pt-BR", 3)])
        self.assertEqual(len(adapter.discover([self.workflow], ["pt-BR"], 3, 3)), 1)
        with self.assertRaisesRegex(ValueError, "requested language"):
            adapter.discover([self.workflow], ["fr", "es"])
        with self.assertRaisesRegex(ValueError, "Unsafe"):
            adapter.discover([self.workflow], ["../fr"])

    def test_backend_errors_do_not_fallback_or_score_zero(self):
        samples, requests = self.prepare(("schema",), ("empty",), "cpp")
        self.envelope(requests["jobs"][0], '{}')
        for returned in ({"timeout": True, "distance": None, "similarity": 0}, {"distance": None, "similarity": 0}):
            with patch.object(CORE.cpp, "compare_json_similarity_cpp", return_value=returned):
                row = adapter.evaluate(CORE, samples, requests, self.predictions, requests)["rows"][0]
                self.assertEqual((row["status"], row["score"]), ("backend_error", None))
        with patch.object(CORE.cpp, "compare_json_similarity_cpp", side_effect=ValueError("backend")):
            row = adapter.evaluate(CORE, samples, requests, self.predictions, requests)["rows"][0]
            self.assertEqual(row["status"], "backend_error")

    def test_macro_micro_and_partial_counts(self):
        rows = []
        for task in adapter.TASKS:
            for correct, total in ((1, 1), (0, 9)):
                rows.append({"task": task, "lang": "fr", "condition": "empty", "schema_metric": "py_tree",
                             "status": "scored", "score": correct / total, "correct": correct, "total": total})
            rows.append({**rows[-1], "status": "not_run", "score": None, "correct": None})
        by_task = {item["task"]: item for item in adapter.summarize(rows)}
        self.assertEqual(by_task["schema"]["score"], .5)
        self.assertEqual(by_task["infill"]["score"], .1)
        self.assertEqual(by_task["alignment"]["score"], .1)
        self.assertTrue(all(item["job_count"] == 3 and not item["complete"] for item in by_task.values()))

    def test_exclusive_output_and_protected_paths(self):
        out = self.base / "output.json"
        adapter.write_output(out, {}, [ROOT, self.workflow])
        with self.assertRaises(FileExistsError):
            adapter.write_output(out, {}, [ROOT, self.workflow])
        with self.assertRaises(ValueError):
            adapter.write_output(self.workflow / "no.json", {}, [ROOT, self.workflow])
        with self.assertRaises(ValueError):
            adapter.write_output(ROOT / "no.json", {}, [ROOT, self.workflow])

    def test_cli_prepare_and_evaluate_offline(self):
        prepared = self.base / "prepared.json"
        common = [sys.executable, "-B", str(SCRIPT), "--benchmark-root", str(ROOT),
                  "--workflow-root", str(self.workflow), "--lang", "fr", "--task", "all",
                  "--condition", "both", "--model", "test/model-1", "--schema-metric", "py_tree"]
        command = common[:3] + ["prepare"] + common[3:] + ["--output", str(prepared)]
        run = subprocess.run(command, capture_output=True, text=True)
        self.assertEqual(run.returncode, 0, run.stderr)
        requests = json.loads(prepared.read_text())
        samples, _ = self.prepare()
        for job in requests["jobs"]:
            self.envelope(job, self.reference(samples[0], job))
        evaluated = self.base / "evaluated.json"
        run = subprocess.run(common[:3] + ["evaluate"] + common[3:] + ["--prediction-root", str(self.predictions),
                             "--prepared", str(prepared), "--output", str(evaluated)], capture_output=True, text=True)
        self.assertEqual(run.returncode, 0, run.stderr)
        self.assertEqual(len(json.loads(evaluated.read_text())["rows"]), 6)

    def test_real_en_zh_fr_unchanged_metric_parity(self):
        french = ROOT / "extensions/2026-09-balanced100-v0.1/workflow"
        self.assertTrue(french.is_dir(), "Numbered French extension must be available")
        samples = adapter.discover([ROOT / "workflow", french], ["en", "zh", "fr"], 14, 14)
        self.assertEqual(len(samples), 3)
        requests = adapter.prepare(CORE, samples, "reference", adapter.TASKS, adapter.CONDITIONS, "py_tree")
        lookup = {(s["lang"], s["sample_id"]): s for s in samples}
        for job in requests["jobs"]:
            sample = lookup[job["lang"], job["sample_id"]]
            _, _, gold, expected, strategy, total = adapter.task_sources(CORE, sample, job["task"], job["condition"])
            raw = json.dumps(gold, ensure_ascii=False) if job["task"] == "schema" else gold
            actual = adapter.score(CORE, sample, job, raw)
            if job["task"] == "schema":
                direct = CORE.jedi.compare_json_similarity(gold, gold, mode="tree_edit")["similarity"]
            elif job["task"] == "alignment":
                # A bracket-gold response is not a valid model input-placeholder response.
                # Compare exact old behavior; do not claim these probes are model results.
                expanded = CORE.alignment.expand_meta(json.loads(adapter.read_source(sample, "meta")))
                chosen = CORE.alignment.choose_coordinate_strategy(gold, expanded)
                resolved = CORE.alignment.resolve_expected_names_from_gold(gold, expanded, chosen)
                results, _ = CORE.alignment.compare_alignment(raw, resolved, chosen)
                direct = sum(v["correct"] for v in results.values()) / sum(v["total"] for v in results.values())
                self.assertEqual(expected, resolved)
            else:
                correct, count = CORE.infill_metric.compare_infill(raw, gold, expected, matcher="source_faithful_v3")
                direct = correct / count
            self.assertEqual(actual["score"], direct)
            self.assertEqual(actual["total"], total)
            if job["lang"] == "fr" and job["task"] != "schema":
                self.assertGreater(total, 0)


if __name__ == "__main__":
    unittest.main()
