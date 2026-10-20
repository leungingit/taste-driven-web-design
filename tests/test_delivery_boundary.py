"""交付边界回归：使用临时工程验证决策、回顾、写入拦截与阶段门禁。"""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))
import delivery as DL
import decide_server
import gate
import paths as P
import waitlib
from rules import validate_question


class DeliveryBoundaryTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="taste-delivery-")
        self.addCleanup(self.tmp.cleanup)
        self.project = Path(self.tmp.name)
        self.root = self.project / P.DIRNAME
        self.source = self.project / "src/main.js"
        self.source.parent.mkdir()
        self.source.write_text("原有且可能尚未提交的代码", encoding="utf-8")
        self.cli("gate.py", "init", "--channel", "inline")

    def cli(self, script, *args, event=None, phase=None):
        env = os.environ.copy()
        env.pop("TASTE_DESIGN_PHASE", None)
        if phase:
            env["TASTE_DESIGN_PHASE"] = phase
        return subprocess.run([sys.executable, str(SCRIPTS / script), *args], cwd=self.project,
                              env=env, text=True, capture_output=True, timeout=10,
                              input=json.dumps(event) if event else None)

    def write(self, rel, value):
        path = self.root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(value, ensure_ascii=False) if isinstance(value, (dict, list)) else value,
                        encoding="utf-8")

    def question(self):
        return {"id": "交付边界", "stage": 0, "type": "single", "role": "delivery-boundary",
                "visual": False, "title": "本期是否修改当前工程实现？",
                "context": "选择交付边界后再制作方案。", "options": [
                    {"id": "design-only", "label": "仅设计系统与工作原型"},
                    {"id": "design-and-implement", "label": "设计并修改工程实现"}]}

    def prepare(self, mode="design-only", answer=True):
        self.write(P.SCOPE, {"mode": "new", "product_type": "site", "scope": "sample-then-rollout",
                            "layout_freedom": "rearrange", "track": "full", "pages": ["首页", "详情"],
                            "asset_types": [], "references": [], "source_dirs": ["src"],
                            "user_customizable": False, "delivery_mode": mode})
        self.write(f"{P.DECISIONS}/交付边界/question.json", self.question())
        self.write(f"{P.DECISIONS}/范围/question.json", {"id": "范围", "stage": 0, "role": "scope",
                                                       "type": "gate", "title": "验收范围", "context": "确认范围"})
        self.cli("gate.py", "record", "范围", "--choice", "approve", "--quote", "确认范围")
        if answer:
            result = self.cli("gate.py", "record", "交付边界", "--choice", mode, "--quote", "按所选边界交付")
            self.assertEqual(result.returncode, 0, result.stderr)
        answers = waitlib.new_answers(str(self.root))
        waitlib.deliver(str(self.root), answers)
        for a in answers:
            waitlib.ack_answer(str(self.root), a["id"], a["ts"])

    def enter_stage(self, stage=2, mode="design-only"):
        self.prepare(mode)
        result = self.cli("gate.py", "pass", "0")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        st = gate.load_state(str(self.root))
        st.update(stage=stage, passed=list(range(stage)))
        gate.save_state(str(self.root), st)

    def guard(self, path, phase=None):
        return self.cli("stage_guard.py", event={"cwd": str(self.project), "tool_input": {
            "file_path": str(path)}}, phase=phase)

    def documentation(self, choice="update"):
        self.write(f"{P.DECISIONS}/文档同步/question.json", {
            "id": "文档同步", "stage": 9, "type": "single", "role": "documentation-sync", "visual": False,
            "title": "是否同步项目文档？", "options": [{"id": "update", "label": "更新"}, {"id": "defer", "label": "暂不更新"}]})
        result = self.cli("gate.py", "record", "文档同步", "--choice", choice, "--quote", "按所选方式处理文档")
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_scope_requires_user_boundary_and_matching_answer(self):
        self.prepare(answer=False)
        result = self.cli("gate.py", "pass", "0")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("delivery-boundary", result.stdout)
        self.cli("gate.py", "record", "交付边界", "--choice", "design-and-implement", "--quote", "同时实现")
        self.assertTrue(any("一致" in p for p in DL.check(str(self.root), gate.load_state(str(self.root)),
                        gate.load_scope(str(self.root)), gate.decisions(str(self.root)))))

    def test_boundary_question_is_nonvisual_single_choice_only(self):
        self.assertEqual(validate_question(self.question()), [])
        for changes in ({"stage": 1}, {"type": "multi"}, {"visual": True},
                        {"allow_setting": True}, {"options": [{"id": "A"}, {"id": "B"}]}):
            with self.subTest(changes=changes):
                self.assertTrue(validate_question({**self.question(), **changes}))

    def test_agent_cannot_choose_boundary_even_when_unattended(self):
        self.prepare()
        st = gate.load_state(str(self.root))
        st["mode"] = "unattended"
        gate.save_state(str(self.root), st)
        path = self.root / P.DECISIONS / "交付边界/answer.json"
        answer = json.loads(path.read_text())
        answer["answered_by"] = "agent"
        path.write_text(json.dumps(answer))
        self.assertNotEqual(self.cli("gate.py", "pass", "0").returncode, 0)

    def test_both_modes_pass_scope_and_seal_choice(self):
        for mode in sorted(DL.MODES):
            with self.subTest(mode=mode):
                self.prepare(mode)
                result = self.cli("gate.py", "pass", "0")
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                st = gate.load_state(str(self.root))
                self.assertEqual(st["delivery_boundary"]["mode"], mode)
                self.assertIn(7, st["sequence"])
                st.update(stage=0, passed=[])
                gate.save_state(str(self.root), st)
                for did in ("范围", "交付边界"):
                    (self.root / P.DECISIONS / did / "answer.json").unlink()

    def test_review_and_static_export_include_boundary_choice(self):
        self.prepare()
        history = waitlib.view(str(self.root))["history"]
        item = next(d for d in history if d.get("role") == "delivery-boundary")
        self.assertEqual(item["_answer"]["choice"], ["design-only"])
        summary = (self.root / P.SUMMARY / "交付边界.md").read_text()
        self.assertIn("仅设计系统与工作原型", summary)
        result = self.cli("decide_server.py", "export")
        self.assertEqual(result.returncode, 0, result.stderr)
        html = (self.root / P.EXPORT / "index.html").read_text()
        self.assertIn("delivery-boundary", html)
        self.assertIn("仅设计系统与工作原型", html)

    def test_fingerprints_detect_edit_add_delete_and_permission_changes(self):
        self.enter_stage()
        original = self.source.read_bytes()
        mutations = [lambda: self.source.write_text("修改实现"),
                     lambda: (self.project / "new-config.json").write_text("{}"),
                     self.source.unlink, lambda: self.source.chmod(0o755)]
        for mutate in mutations:
            with self.subTest(mutation=mutate):
                mutate()
                for command in ("check", "pass"):
                    result = self.cli("gate.py", command, "2")
                    self.assertNotEqual(result.returncode, 0)
                    self.assertIn("工程实现变动", result.stdout + result.stderr)
                self.source.write_bytes(original)
                self.source.chmod(0o644)
                (self.project / "new-config.json").unlink(missing_ok=True)
        self.assertEqual(self.cli("gate.py", "check", "2").returncode, 0)

    def test_guard_allows_prototype_and_link_docs_but_blocks_product_files(self):
        self.enter_stage(4)
        self.assertEqual(self.guard(self.root / "work/proto/v001.html").returncode, 0)
        for path in (self.source, self.project / "package.json", self.project / "public/logo.svg",
                     self.root / DL.BASELINE, self.project / "AGENTS.md", self.project / "docs/design-system.md"):
            self.assertEqual(self.guard(path).returncode, 2)
        self.documentation()
        for path in (self.project / "AGENTS.md", self.project / "docs/design-system.md"):
            self.assertEqual(self.guard(path).returncode, 0)
        (self.project / "docs").mkdir()
        (self.project / "docs/design-system.md").write_text("关联设计系统")
        self.assertEqual(self.cli("gate.py", "check", "4").returncode, 0)

    def test_implementation_mode_allows_source_changes(self):
        self.enter_stage(mode="design-and-implement")
        self.assertEqual(self.guard(self.source).returncode, 0)
        self.source.write_text("实现新设计")
        self.assertEqual(self.cli("gate.py", "check", "2").returncode, 0)

    def test_scope_rewrite_cannot_silently_expand_permission(self):
        self.enter_stage()
        sc = gate.load_scope(str(self.root))
        sc["delivery_mode"] = "design-and-implement"
        self.write(P.SCOPE, sc)
        self.assertEqual(self.guard(self.source).returncode, 2)
        self.assertNotEqual(self.cli("gate.py", "check", "2").returncode, 0)
        self.assertTrue(any("rollback 0" in p for p in gate.blockers(str(self.root), gate.load_state(str(self.root)), 2)))

    def test_missing_baseline_and_completed_project_still_fail_closed(self):
        self.enter_stage(9)
        st = gate.load_state(str(self.root))
        st["passed"] = st["sequence"]
        gate.save_state(str(self.root), st)
        self.source.write_text("完成后越界修改")
        flow = gate.workflow_next(str(self.root))
        self.assertFalse(flow["completed"])
        self.assertEqual(flow["action"], "repair")
        (self.root / DL.BASELINE).unlink()
        self.assertNotEqual(self.cli("gate.py", "check", "9").returncode, 0)
        self.assertFalse((self.root / DL.BASELINE).exists())

    def test_design_rollout_requires_real_prototypes(self):
        self.enter_stage(7)
        self.write("work/rollout/pages.json", [{"name": name, "status": "done"} for name in ("首页", "详情")])
        st = gate.load_state(str(self.root))
        probs = gate.blockers(str(self.root), st, 7)
        self.assertTrue(any("prototype" in p for p in probs))
        self.write("work/proto/v001.html", "工作原型")
        self.write("work/rollout/pages.json", [{"name": name, "status": "done", "prototype": "work/proto/v001.html"}
                                              for name in ("首页", "详情")])
        self.assertFalse(any("prototype" in p for p in gate.blockers(str(self.root), st, 7)))

    def test_document_sync_is_optional_and_defer_does_not_grant_write(self):
        self.enter_stage(9)
        for rel in ("work/handoff/DESIGN.md", "work/handoff/HANDOFF.md", f"{P.BRIEF}/brief.md", f"{P.BRIEF}/traits.md"):
            self.write(rel, "仅设计交付\n当前工程尚未实施\n验证：查看工作原型\n同步至闸门：9\n")
        self.write(f"{P.DECISIONS}/最终验收/question.json", {
            "id": "最终验收", "stage": 9, "type": "gate", "title": "验收设计系统", "context": "设计已完成"})
        self.cli("gate.py", "record", "最终验收", "--choice", "approve", "--quote", "设计验收通过")
        answers = waitlib.new_answers(str(self.root))
        waitlib.deliver(str(self.root), answers)
        for a in answers:
            waitlib.ack_answer(str(self.root), a["id"], a["ts"])
        result = self.cli("gate.py", "pass", "9")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertTrue(gate.workflow_next(str(self.root))["completed"])
        self.assertFalse((self.project / "docs/design-system.md").exists())
        st = gate.load_state(str(self.root))
        st["channel"] = "web"
        gate.save_state(str(self.root), st)
        self.documentation("defer")
        self.assertEqual(self.guard(self.project / "docs/design-system.md").returncode, 2)
        history = waitlib.view(str(self.root))["history"]
        self.assertEqual(next(d for d in history if d.get("role") == "documentation-sync")["_answer"]["choice"], ["defer"])

    def test_unapproved_doc_change_fails_fingerprint_check(self):
        self.enter_stage(9)
        (self.project / "docs").mkdir()
        (self.project / "docs/design-system.md").write_text("未获授权自动修改")
        result = self.cli("gate.py", "check", "9")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("docs/design-system.md", result.stderr)

    def test_web_boundary_rejects_free_text_and_keeps_user_note(self):
        self.prepare(answer=False)
        store = decide_server.Store(str(self.root), 99)
        status, _ = store.answer("交付边界", {"choice": [], "other": "替我决定"})
        self.assertEqual(status, 400)
        self.assertFalse((self.root / P.DECISIONS / "交付边界/answer.json").exists())
        status, _ = store.answer("交付边界", {"choice": ["design-only"], "note": "最后建议是否关联项目文档"})
        self.assertEqual(status, 200)
        answer = json.loads((self.root / P.DECISIONS / "交付边界/answer.json").read_text())
        self.assertEqual(answer["note"], "最后建议是否关联项目文档")

    def test_symlinks_cannot_disguise_engineering_writes(self):
        self.enter_stage(4)
        (self.root / "work/proto/link").symlink_to(self.source.parent, target_is_directory=True)
        self.assertEqual(self.guard(self.root / "work/proto/link/main.js").returncode, 2)
        self.documentation()
        (self.project / "docs").symlink_to(self.source.parent, target_is_directory=True)
        self.assertEqual(self.guard(self.project / "docs/design-system.md").returncode, 2)

    def test_scope_rollback_can_change_mode_after_explicit_new_answer(self):
        self.enter_stage()
        self.cli("gate.py", "rollback", "0", "--reason", "用户要求同时实施")
        sc = gate.load_scope(str(self.root))
        sc["delivery_mode"] = "design-and-implement"
        self.write(P.SCOPE, sc)
        self.cli("gate.py", "record", "交付边界", "--choice", "design-and-implement", "--quote", "改为同时实施")
        self.cli("gate.py", "record", "范围", "--choice", "approve", "--quote", "确认新范围")
        answers = waitlib.new_answers(str(self.root))
        waitlib.deliver(str(self.root), answers)
        for a in answers:
            waitlib.ack_answer(str(self.root), a["id"], a["ts"])
        result = self.cli("gate.py", "pass", "0")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(self.guard(self.source).returncode, 0)
        old = next(d for d in decide_server.Store(str(self.root), 99).view()["history"] if d.get("role") == "delivery-boundary")
        self.assertEqual(old["_superseded"][0]["choice"], ["design-only"])

    def test_skip_cannot_bypass_boundary_check(self):
        self.enter_stage(5)
        st = gate.load_state(str(self.root))
        st["optional"] = [5]
        gate.save_state(str(self.root), st)
        self.source.write_text("越界实现变更")
        result = self.cli("gate.py", "skip", "5", "--reason", "跳过令牌调节")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("工程实现变动", result.stderr)

    def test_multiple_phases_require_explicit_selection_and_keep_separate_permissions(self):
        multi = tempfile.TemporaryDirectory(prefix="taste-delivery-phases-")
        self.addCleanup(multi.cleanup)
        self.project = Path(multi.name)
        self.root = self.project / P.DIRNAME
        self.source = self.project / "src/main.js"
        self.source.parent.mkdir()
        self.source.write_text("已有产品")
        self.assertEqual(self.cli("gate.py", "init", "--phase", "P1").returncode, 0)
        self.assertEqual(self.cli("gate.py", "init", "--phase", "P2").returncode, 0)
        container = self.root
        for pid, mode in (("P1", "design-only"), ("P2", "design-and-implement")):
            self.root = container / P.PHASES / pid
            self.write(P.SCOPE, {"delivery_mode": mode})
            self.write(f"{P.DECISIONS}/交付边界/question.json", self.question())
            self.write(f"{P.DECISIONS}/交付边界/answer.json", {
                "id": "交付边界", "choice": [mode], "answered_by": "user", "via": "web", "ts": "本期答案"})
            st = gate.load_state(str(self.root))
            st.update(stage=2, passed=[0, 1], delivery_boundary=DL.decision(gate.decisions(str(self.root))))
            gate.save_state(str(self.root), st)
        self.assertEqual(self.guard(self.source, phase="P1").returncode, 2)
        self.assertEqual(self.guard(self.source, phase="P2").returncode, 0)
        self.assertEqual(self.guard(self.source).returncode, 2)
        self.assertEqual(self.guard(container / "shared/design-system/tokens.css", phase="P1").returncode, 0)

    def test_rollback_invalidates_boundary_answer_and_keeps_review_history(self):
        self.enter_stage()
        before = (self.root / DL.BASELINE).read_bytes()
        result = self.cli("gate.py", "rollback", "0", "--reason", "重新确认交付边界")
        self.assertEqual(result.returncode, 0, result.stderr)
        folder = self.root / P.DECISIONS / "交付边界"
        self.assertFalse((folder / "answer.json").exists())
        self.assertEqual(len(list(folder.glob("answer.superseded-*.json"))), 1)
        self.assertEqual((self.root / DL.BASELINE).read_bytes(), before)


if __name__ == "__main__":
    unittest.main()
