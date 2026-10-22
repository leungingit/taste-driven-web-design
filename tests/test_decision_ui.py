"""直接执行决策页的真实渲染函数，检查题目提示与 HTML 属性转义。"""
import json
from html.parser import HTMLParser
from pathlib import Path
import shutil
import subprocess
import unittest


class Inputs(HTMLParser):
    def __init__(self, html):
        super().__init__()
        self.fields = []
        self.feed(html)

    def handle_starttag(self, tag, attrs):
        if tag in ("input", "textarea"):
            self.fields.append(dict(attrs))


@unittest.skipUnless(shutil.which("node"), "需要 Node.js 执行网页渲染函数")
class DecisionUITests(unittest.TestCase):
    def test_hints_follow_real_options_and_escape_attributes(self):
        if not shutil.which("node"):
            self.skipTest("需要 Node.js 执行网页渲染函数")
        import sys
        sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
        import decide_server
        script = decide_server.PAGE.split("<script>", 1)[1].split("function canSubmit(q)", 1)[0]
        cases = [
            {"id": "visual", "type": "single", "options": [
                {"id": "editorial", "label": "旅行刊物"}, {"id": "map", "label": "现代制图"}]},
            {"id": "scope", "type": "single", "visual": False, "options": [
                {"id": "only", "label": "仅设计"}, {"id": "implement", "label": "设计并实施"}]},
            {"id": "custom", "type": "multi", "note_placeholder": '保留「现代制图」的标注，调整 "留白" <密度> & 间距', "options": []},
            {"id": "gate", "type": "gate", "note_placeholder": "不能覆盖必填规则", "options": []},
            {"id": "tune", "type": "tune", "playground_url": "about:blank"},
            {"id": "fallback", "type": "single", "note_placeholder": "  ", "options": []},
            {"id": "unsafe", "type": "single", "options": [
                {"id": "x", "label": '<img src=x onerror="alert(1)">'}, {"id": "y", "label": "正常名称"}]},
        ]
        code = 'const window={};\n' + script + '\nlet DATA={customizable:false};\n'
        code += 'console.log(JSON.stringify(' + json.dumps(cases) + '.map(decHTML)));'
        result = subprocess.run([shutil.which("node"), "--eval", code], check=True, capture_output=True, text=True)
        rendered = json.loads(result.stdout)
        fields = [Inputs(html).fields for html in rendered]
        notes = [next(f["placeholder"] for f in group if "data-note" in f) for group in fields]
        self.assertIn("旅行刊物", notes[0])
        self.assertIn("现代制图", notes[0])
        self.assertIn("原因", notes[1])
        self.assertEqual(notes[2], cases[2]["note_placeholder"])
        self.assertEqual(notes[3], "不通过时必填：要改什么")
        self.assertIn("参数", next(f["placeholder"] for f in fields[4] if "data-value" in f))
        self.assertIn("具体部分", notes[5])
        self.assertIn(cases[6]["options"][0]["label"], notes[6])
        self.assertNotIn("<img", rendered[6])
        self.assertNotIn("笔触", "".join(notes))
        self.assertNotIn("--color-bg", rendered[4])
        self.assertNotIn(".taste-design/media/inbox", "".join(rendered))
