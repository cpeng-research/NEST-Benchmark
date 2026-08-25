from comparative_eval.eval_infill import filter_evaluable_rows
from comparative_eval.metrics.infill import (
    LEGACY_MATCHER,
    SOURCE_FAITHFUL_MATCHER,
    SOURCE_FAITHFUL_V2_MATCHER,
    compare_infill,
    normalize_infill_text,
)


def table(*cells: str) -> str:
    return "<table><tr>" + "".join(f"<td>{cell}</td>" for cell in cells) + "</tr></table>"


def test_filter_evaluable_rows_removes_zero_target_tables() -> None:
    rows = [
        {"sample_id": "1", "total": "2"},
        {"sample_id": "2", "total": "0"},
        {"sample_id": "3", "total": ""},
    ]

    assert filter_evaluable_rows(rows) == [{"sample_id": "1", "total": "2"}]


def test_source_faithful_matcher_rejects_empty_and_short_fragments() -> None:
    gold = table("Name: Alice")
    placeholder = table("Name: [Name]")

    assert compare_infill(table(""), gold, placeholder) == (0, 1)
    assert compare_infill(table("A"), gold, placeholder) == (0, 1)
    assert compare_infill(table("Name: Ali"), gold, placeholder) == (0, 1)


def test_source_faithful_matcher_accepts_exact_value_with_surrounding_static_text() -> None:
    gold = table("Applicant Name: Alice (verified)")
    placeholder = table("Applicant Name: [Name] (verified)")

    assert compare_infill(gold, gold, placeholder) == (1, 1)


def test_source_faithful_matcher_rejects_extra_hallucinated_content() -> None:
    gold = table("Name: Alice")
    placeholder = table("Name: [Name]")

    assert compare_infill(table("Name: Alice Bob"), gold, placeholder) == (0, 1)


def test_source_faithful_matcher_scores_multi_value_cells_once_and_preserves_order() -> None:
    gold = table("Height: 180; Hair: Brown")
    placeholder = table("Height: [Height]; Hair: [Hair]")

    assert compare_infill(gold, gold, placeholder) == (1, 1)
    assert compare_infill(table("Height: Brown; Hair: 180"), gold, placeholder) == (0, 1)
    assert compare_infill(table("Height: 180"), gold, placeholder) == (0, 1)


def test_source_faithful_matcher_is_coordinate_anchored() -> None:
    gold = table("Other", "Name: Alice")
    placeholder = table("Other", "Name: [Name]")
    prediction = table("Name: Alice", "Name:")

    assert compare_infill(prediction, gold, placeholder) == (0, 1)


def test_source_faithful_matcher_normalizes_fixed_punctuation_and_unicode() -> None:
    gold = table("Code: ＡＢＣ-１２３")
    placeholder = table("Code: [Code]")
    prediction = table("Code: abc 123")

    assert normalize_infill_text("ＡＢＣ-１２３") == "abc123"
    assert compare_infill(prediction, gold, placeholder) == (1, 1)


def test_source_faithful_matcher_reads_input_value_attributes() -> None:
    gold = table('Name: <input type="text" value="Alice">')
    placeholder = table('Name: <input type="text" value="[Name]">')

    assert compare_infill(table('Name: <input type="text" value="Alice">'), gold, placeholder) == (1, 1)
    assert compare_infill(table('Name: <input type="text" value="Ali">'), gold, placeholder) == (0, 1)


def test_source_faithful_matcher_reads_checkbox_state() -> None:
    gold = table('Yes <input type="checkbox" checked> No <input type="checkbox">')
    placeholder = table('[Choice] Yes <input type="checkbox" checked> [Choice] No <input type="checkbox">')
    correct = table('Yes <input type="checkbox" checked> No <input type="checkbox">')
    swapped = table('Yes <input type="checkbox"> No <input type="checkbox" checked>')

    assert compare_infill(correct, gold, placeholder) == (1, 1)
    assert compare_infill(swapped, gold, placeholder) == (0, 1)


def test_unobservable_placeholder_is_excluded_from_source_faithful_v2() -> None:
    gold = table("Yes No")
    placeholder = table("[Choice] Yes [Choice] No")

    assert compare_infill(gold, gold, placeholder, matcher=SOURCE_FAITHFUL_V2_MATCHER) == (0, 0)


def test_source_faithful_v3_scores_all_top_level_tables() -> None:
    placeholder = table("First: [First]") + table("Second: [Second]")
    gold = table("First: A") + table("Second: B")
    correct = table("First: A") + table("Second: B")
    wrong_second = table("First: A") + table("Second: C")

    assert compare_infill(correct, gold, placeholder) == (2, 2)
    assert compare_infill(wrong_second, gold, placeholder) == (1, 2)
    assert compare_infill(
        correct,
        gold,
        placeholder,
        matcher=SOURCE_FAITHFUL_V2_MATCHER,
    ) == (1, 1)


def test_source_faithful_v3_keeps_later_table_coordinates_stable() -> None:
    placeholder = table("Ignored") + table("Name: [Name]")
    gold = table("Ignored") + table("Name: Alice")
    prediction = "<table><tr><td>Extra</td></tr><tr><td>Ignored</td></tr></table>" + table(
        "Name: Alice"
    )

    assert compare_infill(prediction, gold, placeholder) == (1, 1)


def test_source_faithful_v3_scores_supported_div_form_regions() -> None:
    placeholder = """
    <div class="form-container">
      <div class="row"><div class="col">Name: [Name]</div></div>
      <div class="row"><div class="col-half">Date: [Date]</div></div>
    </div>
    """
    gold = """
    <div class="form-container">
      <div class="row"><div class="col">Name: Alice</div></div>
      <div class="row"><div class="col-half">Date: 2026-08-22</div></div>
    </div>
    """
    wrong = """
    <div class="form-container">
      <div class="row"><div class="col">Name: Alice</div></div>
      <div class="row"><div class="col-half">Date: 2026-08-23</div></div>
    </div>
    """

    assert compare_infill(gold, gold, placeholder) == (2, 2)
    assert compare_infill(wrong, gold, placeholder) == (1, 2)
    assert compare_infill(
        gold,
        gold,
        placeholder,
        matcher=SOURCE_FAITHFUL_V2_MATCHER,
    ) == (0, 0)


def test_legacy_matcher_preserves_substring_false_positive_for_audit() -> None:
    gold = table("Name: Alice")
    placeholder = table("Name: [Name]")

    assert compare_infill(table("A"), gold, placeholder, matcher=LEGACY_MATCHER) == (1, 1)
