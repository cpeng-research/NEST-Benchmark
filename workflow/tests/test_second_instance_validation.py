import asyncio
import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]


def load_module(name: str, relative_path: str):
    spec = importlib.util.spec_from_file_location(name, PROJECT_ROOT / relative_path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


step4 = load_module("step4_validation", "workflow/4-context-a/step4_gen_context.py")
step7 = load_module("step7_validation", "workflow/7-html-b/step7_gen_html_b.py")
step8 = load_module("step8_validation", "workflow/8-json-b/step8_gen_json_b.py")


class SecondInstanceValidationTests(unittest.TestCase):
    def test_context_worker_reports_failure(self):
        class Progress:
            def update(self, _count):
                return None

        async def fail_generation(**_kwargs):
            raise RuntimeError("expected failure")

        with tempfile.TemporaryDirectory() as temp_dir:
            input_path = Path(temp_dir) / "input.html"
            output_path = Path(temp_dir) / "output.txt"
            input_path.write_text("<table><tr><td>value</td></tr></table>", encoding="utf-8")
            original = step4.generate_context
            step4.generate_context = fail_generation
            try:
                result = asyncio.run(
                    step4.process_single_file(
                        item_data={
                            "id": 1,
                            "input_path": str(input_path),
                            "output_path": str(output_path),
                        },
                        client=None,
                        model="test",
                        temperature=0.0,
                        semaphore=asyncio.Semaphore(1),
                        max_retries=1,
                        progress=Progress(),
                    )
                )
            finally:
                step4.generate_context = original

            self.assertFalse(result)
            self.assertFalse(output_path.exists())

    def test_non_table_form_allows_values_and_selections_to_change(self):
        source = '<html><body><div class="field"><input id="x">Alpha</div></body></html>'
        generated = '<html><body><div class="field"><input id="x" checked>Beta</div></body></html>'
        self.assertEqual(step7.validate_generated_html(source, generated), (True, ""))

    def test_non_table_form_rejects_dom_changes(self):
        source = '<html><body><div class="field">Alpha</div></body></html>'
        generated = '<html><body><section class="field">Beta</section></body></html>'
        valid, reason = step7.validate_generated_html(source, generated)
        self.assertFalse(valid)
        self.assertEqual(reason, "document structure changed")

    def test_multiselect_value_may_change_length(self):
        template = {"field": {"select": ["A", "B"], "value": []}}
        output = {"field": {"select": ["A", "B"], "value": ["A"]}}
        self.assertEqual(step8.structure_matches(template, output), (True, ""))

    def test_repeated_rows_still_require_equal_length(self):
        template = {"rows": [{"name": ""}, {"name": ""}]}
        output = {"rows": [{"name": "one"}]}
        valid, reason = step8.structure_matches(template, output)
        self.assertFalse(valid)
        self.assertIn("expected list length 2", reason)


if __name__ == "__main__":
    unittest.main()
