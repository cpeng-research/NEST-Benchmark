from __future__ import annotations

from comparative_eval.config import ROOT, rendered_image_dir
from workflow.render_html_to_png import collect_tasks


def test_rendered_image_directories_share_one_condition_root() -> None:
    assert rendered_image_dir("empty", "en") == (
        ROOT / "workflow" / "9-png-a" / "data_en" / "empty"
    )
    assert rendered_image_dir("filled", "zh") == (
        ROOT / "workflow" / "9-png-a" / "data_zh" / "filled"
    )


def test_empty_template_source_uses_placeholder_fallback() -> None:
    tasks = collect_tasks("empty", ("en",), "189", "189", "force")

    assert len(tasks) == 1
    assert tasks[0].source == ROOT / "workflow" / "5-ph_html-a" / "data_en" / "189.html"
    assert tasks[0].strip_legacy_placeholders is True


def test_regular_template_source_does_not_use_fallback() -> None:
    tasks = collect_tasks("empty", ("en",), "77", "77", "force")

    assert len(tasks) == 1
    assert tasks[0].source == ROOT / "workflow" / "0-html_template" / "data_en" / "77.html"
    assert tasks[0].strip_legacy_placeholders is False
