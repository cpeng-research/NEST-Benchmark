#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Compute structural statistics over NEST metadata files.

The script counts SI/GI/SO/GO/LI cells, assigns each table to a
complexity level, and writes a JSON summary used for Table 2.

Expected metadata format:
{
    "key": "FieldName",
    "label_info": {"row": int, "col": int},
    "placeholder_offset": {"rows": int, "cols": int} or [{"rows": int, "cols": int}, ...],
    "type": "SI" | "GI" | "LI" | "GO" | "SO",
    "is_object_type": bool,
    "is_non_pure_text": bool
}

Usage:
1. Analyze both languages:
   python table2_structural_statistics.py

2. Analyze English data only:
   python table2_structural_statistics.py --lang en

3. Analyze Chinese data only:
   python table2_structural_statistics.py --lang zh

4. Write to a custom output file:
   python table2_structural_statistics.py --output statistics_result.json
"""

import json
import os
import glob
import argparse
from typing import Dict, Any, List
from datetime import datetime


def get_table_level(meta_items: List[Dict[str, Any]]) -> str:
    """
    Return the table complexity level implied by the atomic cell types.
    
    Level 1: Flat Table (SI only)
    Level 2: Hierarchical Table (contains GI)
    Level 3: Composite Form (contains LI/SO/GO)
    """
    if not meta_items:
        return "Level 1"
    
    types = set()
    for item in meta_items:
        item_type = item.get("type", "")
        if item_type:
            types.add(item_type)
    
    if any(t in types for t in ["LI", "SO", "GO"]):
        return "Level 3"
    
    if "GI" in types:
        return "Level 2"
    
    return "Level 1"


def count_placeholders(meta_item: Dict[str, Any]) -> int:
    """
    Return the number of placeholder values represented by one metadata item.

    placeholder_offset may be a single offset object or a list of offset
    objects. A list contributes one placeholder per element.
    """
    placeholder_offset = meta_item.get("placeholder_offset")
    
    if isinstance(placeholder_offset, list):
        return len(placeholder_offset)
    elif isinstance(placeholder_offset, dict):
        return 1
    
    return 1


def analyze_table(meta_items: List[Dict[str, Any]]) -> Dict[str, int]:
    """
    Count atomic cell types for one table metadata file.
    """
    counts = {
        "SI": 0,
        "GI": 0,
        "SO": 0,
        "GO": 0,
        "LI": 0,
    }
    
    for item in meta_items:
        item_type = item.get("type", "")
        
        if item_type in counts:
            num_placeholders = count_placeholders(item)
            counts[item_type] += num_placeholders
    
    return counts


def load_meta_files(directory: str) -> List[List[Dict[str, Any]]]:
    """
    Load all JSON metadata files from a directory.

    Each outer list element represents one table's metadata list.
    """
    if not os.path.exists(directory):
        print(f"Warning: Directory not found: {directory}")
        return []
    
    json_files = glob.glob(os.path.join(directory, "*.json"))
    json_files = [f for f in json_files if not os.path.basename(f).startswith('.')]
    json_files.sort()
    
    all_tables = []
    for filepath in json_files:
        try:
            with open(filepath, 'r', encoding='utf-8') as f:
                data = json.load(f)
                if isinstance(data, list):
                    all_tables.append(data)
                else:
                    print(f"Warning: Unexpected format in {filepath}")
        except (json.JSONDecodeError, IOError) as e:
            print(f"Warning: Failed to load {filepath}: {e}")
    
    return all_tables


def parse_args():
    """Parse command-line arguments"""
    parser = argparse.ArgumentParser(
        description="Summarize cell-type distributions by table level under workflow/6-meta-a/data_{lang}/*.json"
    )
    parser.add_argument(
        "--lang",
        choices=["en", "zh"],
        nargs="+",
        default=["en", "zh"],
        help="Language(s) to analyze: 'en' for English, 'zh' for Chinese, or both (default: both)",
    )
    parser.add_argument(
        "--output",
        type=str,
        default="table_statistics_result.json",
        help="Output file path for statistics result (default: table_statistics_result.json)",
    )
    return parser.parse_args()


def save_statistics_to_file(stats_data: Dict, output_file: str):
    """
    Write the statistics report to disk with a generation timestamp.
    """
    stats_data["generated_at"] = datetime.now().isoformat()
    
    with open(output_file, 'w', encoding='utf-8') as f:
        json.dump(stats_data, f, ensure_ascii=False, indent=2)
    
    print(f"\nStatistics saved to: {output_file}")


def main():
    args = parse_args()
    
    result_data = {
        "summary": {},
        "language_details": {},
        "level_distribution": {},
        "type_distribution": {}
    }
    
    overall_level_stats = {
        "Level 1": {"tables": 0, "cells": 0, "SI": 0, "GI": 0, "SO": 0, "GO": 0, "LI": 0},
        "Level 2": {"tables": 0, "cells": 0, "SI": 0, "GI": 0, "SO": 0, "GO": 0, "LI": 0},
        "Level 3": {"tables": 0, "cells": 0, "SI": 0, "GI": 0, "SO": 0, "GO": 0, "LI": 0}
    }
    
    total_tables_all_langs = 0
    
    for lang in args.lang:
        lang_upper = lang.upper()
        print(f"\n{'='*80}")
        print(f"Analyzing {lang_upper} data...")
        print(f"{'='*80}")

        level_stats = {
            "Level 1": {"tables": 0, "cells": 0, "SI": 0, "GI": 0, "SO": 0, "GO": 0, "LI": 0},
            "Level 2": {"tables": 0, "cells": 0, "SI": 0, "GI": 0, "SO": 0, "GO": 0, "LI": 0},
            "Level 3": {"tables": 0, "cells": 0, "SI": 0, "GI": 0, "SO": 0, "GO": 0, "LI": 0}
        }
        
        meta_dir = f"workflow/6-meta-a/data_{lang}"
        print(f"Loading metadata from: {meta_dir}")
        all_tables = load_meta_files(meta_dir)
        
        if not all_tables:
            print(f"No metadata files found for {lang_upper} language.")
            continue
        
        print(f"Loaded {len(all_tables)} tables")
        
        for table_idx, meta_items in enumerate(all_tables):
            level = get_table_level(meta_items)
            level_stats[level]["tables"] += 1
            
            type_counts = analyze_table(meta_items)
            
            for type_key, count in type_counts.items():
                level_stats[level][type_key] += count
            
            total_cells = sum(type_counts.values())
            level_stats[level]["cells"] += total_cells
        
        lang_tables = sum(level_stats[l]["tables"] for l in level_stats)
        lang_cells = sum(level_stats[l]["cells"] for l in level_stats)
        
        lang_stats = {}
        for level in ["Level 1", "Level 2", "Level 3"]:
            stats = level_stats[level]
            if stats["tables"] > 0:
                pct = (stats["tables"] / lang_tables * 100) if lang_tables > 0 else 0
                lang_stats[level] = {
                    "tables": stats["tables"],
                    "tables_percentage": round(pct, 2),
                    "total_cells": stats["cells"],
                    "SI": stats["SI"],
                    "GI": stats["GI"],
                    "SO": stats["SO"],
                    "GO": stats["GO"],
                    "LI": stats["LI"]
                }
        
        result_data["language_details"][lang_upper] = {
            "total_tables": lang_tables,
            "total_cells": lang_cells,
            "level_distribution": lang_stats
        }
        
        print(f"\n--- {lang_upper} Statistics ---")
        for level in ["Level 1", "Level 2", "Level 3"]:
            stats = level_stats[level]
            if stats["tables"] > 0:
                pct = (stats["tables"] / lang_tables * 100) if lang_tables > 0 else 0
                print(f"\n{level}:")
                print(f"  Tables: {stats['tables']} ({pct:.1f}%)")
                print(f"  Total Cells: {stats['cells']:,}")
                print(f"  SI (Simple Index): {stats['SI']}")
                print(f"  GI (Group Index): {stats['GI']}")
                print(f"  SO (Simple Object): {stats['SO']}")
                print(f"  GO (Group Object): {stats['GO']}")
                print(f"  LI (List Items): {stats['LI']}")
        
        total_tables_all_langs += lang_tables
        for level in ["Level 1", "Level 2", "Level 3"]:
            for key, value in level_stats[level].items():
                overall_level_stats[level][key] += value
    
    total_tables = 0
    total_cells = 0
    total_type_counts = {"SI": 0, "GI": 0, "SO": 0, "GO": 0, "LI": 0}
    
    for level in ["Level 1", "Level 2", "Level 3"]:
        stats = overall_level_stats[level]
        total_tables += stats["tables"]
        total_cells += stats["cells"]
        
        for type_key in total_type_counts:
            total_type_counts[type_key] += stats[type_key]
    
    if len(args.lang) > 1:
        print(f"\n\n{'='*80}")
        print("OVERALL STATISTICS (All Languages)")
        print(f"{'='*80}")
    
    result_data["summary"] = {
        "total_tables": total_tables,
        "total_cells": total_cells,
        "languages_analyzed": args.lang,
        "type_counts": total_type_counts,
        "type_percentages": {}
    }
    
    if total_cells > 0:
        for type_key in ["SI", "GI", "SO", "GO", "LI"]:
            count = total_type_counts[type_key]
            pct = round((count / total_cells * 100), 2)
            result_data["summary"]["type_percentages"][type_key] = pct
    
    result_data["level_distribution"] = {}
    for level in ["Level 1", "Level 2", "Level 3"]:
        stats = overall_level_stats[level]
        pct = round((stats["tables"] / total_tables * 100), 2) if total_tables > 0 else 0
        result_data["level_distribution"][level] = {
            "tables": stats["tables"],
            "tables_percentage": pct,
            "total_cells": stats["cells"],
            "SI": stats["SI"],
            "GI": stats["GI"],
            "SO": stats["SO"],
            "GO": stats["GO"],
            "LI": stats["LI"]
        }
    
    print(f"\n{'='*80}")
    print("TOTAL SUMMARY:")
    print(f"{'='*80}")
    print(f"  Total Tables: {total_tables} (100%)")
    print(f"  Total Cells: {total_cells:,}")
    
    if total_cells > 0:
        for type_key in ["SI", "GI", "SO", "GO", "LI"]:
            count = total_type_counts[type_key]
            pct = (count / total_cells * 100)
            print(f"  {type_key}: {count} ({pct:.1f}%)")
    
    print("=" * 80)
    
    print(f"\n{'='*80}")
    print("LaTeX Table Data:")
    print(f"{'='*80}")
    
    latex_data = []
    for level_name, level_key in [("Level 1 (Flat T.)", "Level 1"),
                                    ("Level 2 (Hierarchical T.)", "Level 2"),
                                    ("Level 3 (Composite F.)", "Level 3")]:
        stats = overall_level_stats[level_key]
        pct = (stats["tables"] / total_tables * 100) if total_tables > 0 else 0
        
        latex_line = f"{level_name} & {stats['tables']} ({pct:.1f}\\%) & {stats['cells']:,} & " \
                     f"{stats['SI']} & {stats['GI']} & {stats['SO']} & {stats['GO']} & {stats['LI']} \\\\"
        print(latex_line)
        latex_data.append(latex_line)
    
    print("\\hline")
    
    total_line = f"\\textbf{{Total}} & \\textbf{{{total_tables} (100\\%)}} & \\textbf{{{total_cells:,}}} & " \
                 f"\\textbf{{{total_type_counts['SI']}}} & \\textbf{{{total_type_counts['GI']}}} & " \
                 f"\\textbf{{{total_type_counts['SO']}}} & \\textbf{{{total_type_counts['GO']}}} & " \
                 f"\\textbf{{{total_type_counts['LI']}}} \\\\"
    print(total_line)
    latex_data.append(total_line)
    
    if total_cells > 0:
        si_pct = (total_type_counts['SI']/total_cells*100)
        gi_pct = (total_type_counts['GI']/total_cells*100)
        so_pct = (total_type_counts['SO']/total_cells*100)
        go_pct = (total_type_counts['GO']/total_cells*100)
        li_pct = (total_type_counts['LI']/total_cells*100)
        
        pct_line = f"\\textbf{{Cell Type Dist.}} & & & " \
                   f"({si_pct:.1f}\\%) & ({gi_pct:.1f}\\%) & ({so_pct:.1f}\\%) & ({go_pct:.1f}\\%) & ({li_pct:.1f}\\%) \\\\"
        print(pct_line)
        latex_data.append(pct_line)
    
    print("=" * 80)
    
    result_data["latex_table_data"] = latex_data
    
    save_statistics_to_file(result_data, args.output)
    
    return result_data, total_tables, total_cells, total_type_counts


if __name__ == "__main__":
    main()
