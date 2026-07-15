# -*- coding: utf-8 -*-
import importlib.util
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))


def load(name):
    spec = importlib.util.spec_from_file_location(name, SCRIPTS / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class TableValidationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.utils = load("table_utils")

    def test_valid_multilevel_table(self):
        text = '''<div class="table-wrap"><table class="table-dense"><thead><tr><th rowspan="2"></th><th colspan="2">组</th></tr><tr><th>A</th><th>B</th></tr></thead><tbody><tr><td>x</td><td>1</td><td>2</td></tr></tbody></table></div>'''
        self.assertEqual(self.utils.validate_page_markdown(text), [])

    def test_malformed_table_rejected(self):
        text = '''<table><tbody><tr><td>x</td><td><td>1</td></tr></tbody></table>'''
        self.assertTrue(self.utils.validate_page_markdown(text))

    def test_gfm_column_mismatch(self):
        text = "| A | B |\n| --- | --- |\n| 1 |"
        self.assertTrue(self.utils.validate_page_markdown(text))

    def test_mixed_sort_key(self):
        values = ["cover.jpg", "10.jpg", "2.jpg"]
        self.assertEqual(sorted(values, key=self.utils.natural_path_key), ["2.jpg", "10.jpg", "cover.jpg"])


class TypesetTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.ts = load("typeset_book")

    def test_cleanup_does_not_delete_repeats(self):
        value = "哈哈哈 好好好学习 测试测试测试 人人人人"
        self.assertEqual(self.ts.cleanup_text(value), value)

    def test_preamble_and_generic_div_preserved(self):
        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            source = d / "book.md"
            split = d / "split"
            typed = d / "typed"
            output = d / "out.md"
            source.write_text(
                '---\ntitle: "T"\n---\n\n前言\n\n# 第一章\n\n<div class="note">说明</div>\n\n  正文。\n',
                encoding="utf-8",
            )
            files = self.ts.split_by_h1(source, split)
            self.ts.typeset_files(split, typed, files)
            self.ts.merge_final(typed, files, output)
            result = output.read_text(encoding="utf-8")
            self.assertIn('title: "T"', result)
            self.assertIn("前言", result)
            self.assertIn('<div class="note">说明</div>', result)
            self.assertIn("正文。", result)


class ContinuedTableTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.merge = load("merge_tables")

    def test_merge_gfm_continuation(self):
        a = "正文\n\n| A | B |\n| --- | --- |\n| 1 | 2 |"
        b = "| A | B |\n| --- | --- |\n| 3 | 4 |\n\n后文"
        pages, report = self.merge.merge_page_sequence([("1.md", a), ("2.md", b)])
        joined = "\n".join(x[1] for x in pages)
        self.assertEqual(joined.count("| A | B |"), 1)
        self.assertIn("| 3 | 4 |", joined)
        self.assertEqual(report[0]["kind"], "gfm")

    def test_merge_footnote_continuation(self):
        a = '正文<sup>【注释未完⬇️】</sup>'
        b = '<sup>⬆️续文。】</sup>\n\n后文'
        pages, report = self.merge.merge_page_sequence([('1.md', a), ('2.md', b)])
        joined = '\n'.join(x[1] for x in pages)
        self.assertNotIn('⬆️', joined)
        self.assertNotIn('⬇️', joined)
        self.assertIn('注释未完续文。', joined)
        self.assertTrue(any(item['kind'] == 'footnote' for item in report))

    def test_merge_html_continuation(self):
        head = '<thead><tr><th>A</th><th>B</th></tr></thead>'
        a = f'<div class="table-wrap"><table class="table-dense">{head}<tbody><tr><td>1</td><td>2</td></tr></tbody></table></div>'
        b = f'<div class="table-wrap"><table class="table-dense">{head}<tbody><tr><td>3</td><td>4</td></tr></tbody></table></div>'
        pages, report = self.merge.merge_page_sequence([("1.md", a), ("2.md", b)])
        joined = "\n".join(x[1] for x in pages)
        self.assertEqual(joined.count("<thead>"), 1)
        self.assertIn("<td>3</td>", joined)
        self.assertEqual(report[0]["kind"], "html")


if __name__ == "__main__":
    unittest.main()
