"""Offline regression test for Overture places schema drift.

WHY THIS EXISTS: on 2026-09-23 Overture REMOVED the `categories` column.
archive_release.py asked for `categories.primary` unconditionally and the
monthly archive died with a BinderException, silently skipping a release that
S3 retains for only ~2 cycles. The detection below is the fix; these are the
three real schema shapes it has to survive, so the next rename is a red test
rather than a lost month.

Run: .venv/bin/python -m unittest discover -s pipeline/sources -p 'test_*.py'
No network, no DuckDB - detection is a pure function of a DESCRIBE result.
"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from pipeline.sources.archive_release import detect_category_expr

# Verbatim DESCRIBE output, captured from the real releases.
CATEGORIES_PRIMARY = {  # 2024-08-20-0 .. 2026-08-19.0
    "categories": 'STRUCT("primary" VARCHAR, alternate VARCHAR[])',
    "taxonomy": 'STRUCT("primary" VARCHAR, hierarchy VARCHAR[], alternates VARCHAR[])',
    "names": 'STRUCT("primary" VARCHAR)',
}
CATEGORIES_MAIN = {  # the 2024 alpha releases
    "categories": "STRUCT(main VARCHAR, alternate VARCHAR[])",
    "names": 'STRUCT("primary" VARCHAR)',
}
TAXONOMY_ONLY = {  # 2026-09-23.0 onward - `categories` is gone
    "taxonomy": 'STRUCT("primary" VARCHAR, hierarchy VARCHAR[], alternates VARCHAR[])',
    "names": 'STRUCT("primary" VARCHAR)',
}


class TestDetectCategoryExpr(unittest.TestCase):
    def test_alpha_releases_use_categories_main(self):
        self.assertEqual(detect_category_expr(CATEGORIES_MAIN), "categories.main")

    def test_stable_releases_use_categories_primary(self):
        self.assertEqual(detect_category_expr(CATEGORIES_PRIMARY), "categories.primary")

    def test_categories_wins_while_both_columns_exist(self):
        """August carried BOTH. Prefer `categories` so the 23 archived
        snapshots and any re-clip of them keep one vocabulary: taxonomy
        renames 31% of values (dentist -> dental_clinic, mosque ->
        muslim_place_of_worship), which would make snapshots incomparable."""
        self.assertIn("taxonomy", CATEGORIES_PRIMARY)
        self.assertEqual(detect_category_expr(CATEGORIES_PRIMARY), "categories.primary")

    def test_september_2026_falls_back_to_taxonomy(self):
        self.assertEqual(detect_category_expr(TAXONOMY_ONLY), "taxonomy.primary")

    def test_unknown_schema_raises_rather_than_guessing(self):
        """A silent wrong column would write a snapshot of nulls that looks
        like a successful archive. Fail loudly instead."""
        with self.assertRaises(RuntimeError):
            detect_category_expr({"names": 'STRUCT("primary" VARCHAR)'})


if __name__ == "__main__":
    unittest.main()
