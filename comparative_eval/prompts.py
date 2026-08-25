from __future__ import annotations


TABLE3_SYSTEM_PROMPT = "You are a precise table and JSON conversion assistant."


def schema_prompt(html: str, condition: str) -> str:
    source = "filled HTML table" if condition == "filled" else "empty HTML table template"
    value_rule = (
        "Preserve filled values when they are present."
        if condition == "filled"
        else "Use empty strings for fillable values."
    )
    return f"""Convert the following {source} into a concise hierarchical JSON object.

Rules:
1. Keep the original language of all labels.
2. Preserve the table's field hierarchy and repeated structures.
3. Convert selectable fields to objects with "select" and "value" when possible.
4. {value_rule}
5. Return only valid JSON, without markdown fences or explanations.

HTML:
{html}
"""


def alignment_prompt(html: str, condition: str) -> str:
    source = "filled HTML form" if condition == "filled" else "empty HTML form template"
    return f"""Identify all fillable positions in the following {source}.

Return the complete HTML using the reference placeholder format. At every position that should contain user-provided data, insert an HTML input placeholder:
<input type="text" name="FieldName" value="placeholder">

Rules:
1. Keep the original table structure, text, styling, rows, and cells.
2. Do not invent field names; use the most local label text from the table as the input name.
3. For plain text fields, replace the fillable blank/value with <input type="text" name="FieldName" value="placeholder">.
4. For repeated rows, add 1-based indices to the name when needed, for example name="Item1" and name="Item2".
5. For checkbox, radio, or other selectable groups, use the same field name for every option in the group. If the option is already an <input type="checkbox"> or <input type="radio">, add name="FieldName" and value="placeholder" to that input. If the selectable mark is plain text such as ( ), [ ], or a check mark, insert a nearby <input type="text" name="FieldName" value="placeholder">.
6. Do not output square-bracket placeholders such as [Name]. The output must use HTML input placeholders with name="..." and value="placeholder".
7. Return only the final HTML, without markdown fences or explanations.

HTML:
{html}
"""


def infill_prompt(html: str, context: str, condition: str) -> str:
    if condition == "filled":
        task = "check, correct, and complete this already filled HTML table"
    else:
        task = "fill this empty HTML table template"
    return f"""Use the relevant information to {task}.

Rules:
1. Keep the original HTML structure and styling.
2. Fill all fields supported by the relevant information.
3. Preserve checkbox/radio/selectable markup and set the selected option where appropriate.
4. Return only the final HTML, without markdown fences or explanations.

Relevant information:
{context}

HTML:
{html}
"""
