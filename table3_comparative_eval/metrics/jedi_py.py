from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from typing import Any

from table3_comparative_eval.utils.json_utils import normalize_json_text, parse_json_lenient


@dataclass(frozen=True)
class JsonTree:
    label: str
    children: tuple["JsonTree", ...] = ()

    @property
    def size(self) -> int:
        return 1 + sum(child.size for child in self.children)


def json_to_tree(obj: Any, sort_keys: bool = True, normalize_text: bool = True) -> JsonTree:
    if normalize_text:
        obj = normalize_json_text(obj)
    return _to_tree(obj, sort_keys=sort_keys)


def _to_tree(obj: Any, sort_keys: bool) -> JsonTree:
    if isinstance(obj, dict):
        items = sorted(obj.items(), key=lambda kv: str(kv[0])) if sort_keys else obj.items()
        children = tuple(JsonTree(f'"{str(key)}":', (_to_tree(value, sort_keys),)) for key, value in items)
        return JsonTree(r"{\{\}", children)
    if isinstance(obj, list):
        return JsonTree("[]", tuple(_to_tree(value, sort_keys) for value in obj))
    if isinstance(obj, str):
        return JsonTree(f'"{"".join(obj.split())}"')
    if obj is None:
        return JsonTree("null")
    return JsonTree(str(obj))


def tree_edit_distance(a: JsonTree, b: JsonTree) -> int:
    @lru_cache(maxsize=None)
    def dist(x: JsonTree, y: JsonTree) -> int:
        relabel = 0 if x.label == y.label else 1
        return relabel + children_distance(x.children, y.children)

    @lru_cache(maxsize=None)
    def children_distance(xs: tuple[JsonTree, ...], ys: tuple[JsonTree, ...]) -> int:
        n, m = len(xs), len(ys)
        dp = [[0] * (m + 1) for _ in range(n + 1)]
        for i in range(1, n + 1):
            dp[i][0] = dp[i - 1][0] + xs[i - 1].size
        for j in range(1, m + 1):
            dp[0][j] = dp[0][j - 1] + ys[j - 1].size
        for i in range(1, n + 1):
            for j in range(1, m + 1):
                dp[i][j] = min(
                    dp[i - 1][j] + xs[i - 1].size,
                    dp[i][j - 1] + ys[j - 1].size,
                    dp[i - 1][j - 1] + dist(xs[i - 1], ys[j - 1]),
                )
        return dp[n][m]

    return dist(a, b)


def fast_structural_distance(a: JsonTree, b: JsonTree) -> int:
    labels_a = _label_counts(a)
    labels_b = _label_counts(b)
    all_labels = set(labels_a) | set(labels_b)
    unmatched = sum(abs(labels_a.get(label, 0) - labels_b.get(label, 0)) for label in all_labels)
    root_penalty = 0 if a.label == b.label else 1
    return unmatched + root_penalty


def _label_counts(tree: JsonTree) -> dict[str, int]:
    counts: dict[str, int] = {}

    def walk(node: JsonTree) -> None:
        counts[node.label] = counts.get(node.label, 0) + 1
        for child in node.children:
            walk(child)

    walk(tree)
    return counts


def compare_json_similarity(
    pred: Any,
    gold: Any,
    *,
    mode: str = "tree_edit",
    sort_keys: bool = True,
    normalize_text: bool = True,
    denominator: str = "sum",
) -> dict[str, Any]:
    pred_obj, pred_status = parse_json_lenient(pred)
    gold_obj, gold_status = parse_json_lenient(gold)
    if pred_obj is None or gold_obj is None:
        return {
            "similarity": 0.0,
            "distance": None,
            "size_pred": 0,
            "size_gold": 0,
            "pred_status": pred_status,
            "gold_status": gold_status,
            "metric": f"jedi_py:{mode}",
        }

    pred_tree = json_to_tree(pred_obj, sort_keys=sort_keys, normalize_text=normalize_text)
    gold_tree = json_to_tree(gold_obj, sort_keys=sort_keys, normalize_text=normalize_text)
    if mode == "fast_structural":
        distance = fast_structural_distance(gold_tree, pred_tree)
    elif mode == "tree_edit":
        distance = tree_edit_distance(gold_tree, pred_tree)
    else:
        raise ValueError(f"Unsupported JEDI Python mode: {mode}")

    if denominator == "max":
        reference = max(gold_tree.size, pred_tree.size)
    else:
        reference = gold_tree.size + pred_tree.size
    similarity = 1.0 if reference == 0 else max(0.0, min(1.0, 1 - (distance / reference)))
    return {
        "similarity": similarity,
        "distance": distance,
        "size_pred": pred_tree.size,
        "size_gold": gold_tree.size,
        "pred_status": pred_status,
        "gold_status": gold_status,
        "metric": f"jedi_py:{mode}",
    }


def json_to_bracket_string(obj: Any, sort_keys: bool = True, normalize_text: bool = False) -> str:
    if normalize_text:
        obj = normalize_json_text(obj)
    if isinstance(obj, dict):
        items = sorted(obj.items(), key=lambda kv: str(kv[0])) if sort_keys else obj.items()
        parts = [r"{\{\}"]
        for key, value in items:
            escaped = str(key).replace("{", r"\{").replace("}", r"\}")
            parts.append('{"' + escaped + '":')
            parts.append(json_to_bracket_string(value, sort_keys=sort_keys, normalize_text=False))
            parts.append("}")
        parts.append("}")
        return "".join(parts)
    if isinstance(obj, list):
        return "{[]" + "".join(json_to_bracket_string(value, sort_keys=sort_keys, normalize_text=False) for value in obj) + "}"
    if isinstance(obj, str):
        escaped = "".join(obj.replace("{", r"\{").replace("}", r"\}").split())
        return '{"' + escaped + '"}'
    if obj is None:
        return "{null}"
    return "{" + str(obj) + "}"

