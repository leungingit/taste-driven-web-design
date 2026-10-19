"""多期入口与恢复输出回归；只使用临时项目和虚构数据。"""
import json
import os
import shutil
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))
import gate
import paths as P
from stages import validate_phase_scope
import waitlib


class PhaseRegressionTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="taste-phase-regression-")
        self.addCleanup(self.tmp.cleanup)
        self.project = Path(self.tmp.name)
        self.container = self.project / P.DIRNAME

    def cli(self, script, *args, cwd=None, event=None, ok=True):
        env = os.environ.copy()
        env.pop("TASTE_DESIGN_PHASE", None)
        result = subprocess.run([sys.executable, str(SCRIPTS / script), *args],
                                cwd=cwd or self.project, env=env, text=True,
                                input=json.dumps(event) if event is not None else None,
                                capture_output=True, timeout=10)
        if ok:
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        return result

    def init_multi(self):
        self.cli("gate.py", "init", "--phase", "P1")
        self.cli("gate.py", "phase", "add", "P2", "--parent", "P1")
        return self.container / P.PHASES / "P1", self.container / P.PHASES / "P2"

    def test_init_phase_works_before_and_after_subcommand(self):
        self.cli("gate.py", "--phase", "P1", "init")
        self.cli("gate.py", "init", "--phase", "P2", "--parent", "P1")
        for pid in ("P1", "P2"):
            root = self.container / P.PHASES / pid
            self.assertEqual(gate.load_state(str(root))["phase"], pid)
        self.assertFalse((self.container / P.STATE).exists())

    def test_init_does_not_select_an_existing_phase(self):
        self.cli("gate.py", "init", "--phase", "P1")
        self.cli("gate.py", "init", "--phase", "P2")
        self.assertTrue((self.container / P.PHASES / "P2" / P.STATE).is_file())

    def test_project_and_phase_directory_select_same_explicit_phase(self):
        p1, p2 = self.init_multi()
        for root in (self.project, self.container, p1):
            payload = json.loads(self.cli("gate.py", "--root", str(root), "--phase", "P2",
                                          "context", "--json", "--compact").stdout)
            self.assertEqual(Path(payload["root"]).resolve(), p2.resolve())
        self.assertEqual(Path(P.find_root_phase(str(p1 / "work"), "P2")).resolve(), p2.resolve())
        self.assertEqual(Path(P.resolve_root(str(p1), "P2")).resolve(), p2.resolve())

    def test_phase_cwd_is_resolved_without_guessing_other_phases(self):
        p1, _ = self.init_multi()
        payload = json.loads(self.cli("gate.py", "context", "--json", "--compact", cwd=p1 / "work").stdout)
        self.assertEqual(payload["phase"], "P1")

    def test_other_cli_entries_honor_explicit_phase_over_root(self):
        p1, p2 = self.init_multi()
        self.cli("decide_server.py", "--root", str(p1), "--phase", "P2", "export")
        self.assertTrue((p2 / P.EXPORT / "index.html").is_file())
        self.assertFalse((p1 / P.EXPORT / "index.html").exists())
        self.cli("summary.py", "--root", str(self.project), "--phase", "P2", "rebuild")

    def test_environment_phase_also_applies_to_init(self):
        env = {**os.environ, "TASTE_DESIGN_PHASE": "P1"}
        result = subprocess.run([sys.executable, str(SCRIPTS / "gate.py"), "init"], cwd=self.project,
                                env=env, text=True, capture_output=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertTrue((self.container / P.PHASES / "P1" / P.STATE).is_file())

    def test_single_phase_guard_still_blocks_state_and_future_artifacts(self):
        self.cli("gate.py", "init")
        for rel in (P.STATE, "work/proto/v1.html", P.DECISIONS + "/D1/answer.json"):
            result = self.cli("stage_guard.py", event={"tool_input": {
                "file_path": str(self.container / rel)}}, ok=False)
            self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
        result = self.cli("stage_guard.py", event={"tool_input": {
            "file_path": str(self.project / "src/main.py")}})
        self.assertEqual(result.stdout, "")

    def test_wait_hook_outside_design_project_allows_stop(self):
        result = self.cli("wait_hook.py", "--max", "0", event={"cwd": str(self.project)})
        self.assertNotEqual(json.loads(result.stdout or "{}").get("decision"), "block")

    def test_context_does_not_recreate_cache_after_clone(self):
        self.cli("gate.py", "init")
        shutil.rmtree(self.container / "cache")
        self.cli("gate.py", "context", "--json", "--compact")
        self.assertFalse((self.container / "cache").exists())

    def test_phase_snapshot_reads_project_source_directory(self):
        p1, p2 = self.init_multi()
        src = self.project / "src"
        src.mkdir()
        (src / "main.css").write_text("/* 测试源码 */")
        for root in (p1, p2):
            (root / P.SCOPE).write_text(json.dumps({"source_dirs": ["src"]}))
            self.assertEqual(gate.snapshot(str(root), 0), ["src"])
            self.assertEqual((root / P.SNAPSHOTS / "gate-0/src/main.css").read_text(), "/* 测试源码 */")

    def test_invalid_phase_does_not_register_or_create_container(self):
        with self.assertRaises(ValueError):
            P.add_phase_record(str(self.container), "../invalid", "错误期")
        self.assertFalse(self.container.exists())

    def test_invalid_inheritance_does_not_register_phase(self):
        self.cli("gate.py", "init", "--phase", "P1")
        before = (self.container / P.PROJECT).read_bytes()
        for rel in ("../outside", "/absolute", "shared/..", "shared/../../outside", ".."):
            with self.subTest(rel=rel), self.assertRaises(ValueError):
                P.add_phase_record(str(self.container), "P2", "二期", inherits=[rel])
            self.assertEqual((self.container / P.PROJECT).read_bytes(), before)
        outside = self.project / "outside"
        outside.mkdir()
        (self.container / "shared/link").symlink_to(outside, target_is_directory=True)
        with self.assertRaises(ValueError):
            P.add_phase_record(str(self.container), "P2", "二期", inherits=["shared/link"])

    def test_scope_inheritance_must_match_metadata_including_empty_lists(self):
        base = {"phase_relation": "extend", "inherit_mode": "shared", "start_stage": 3}
        for inherits in ([], "shared/brand.md", ["../outside"]):
            with self.subTest(inherits=inherits):
                errs = validate_phase_scope({**base, "inherits": inherits}, {"inherits": ["shared/brand.md"]})
                self.assertTrue(errs)
        self.assertTrue(validate_phase_scope({**base, "inherits": ["phases/P1/record/brief/brief.md"]},
                                            {"inherits": ["phases/P1/record/brief/brief.md"]}))
        self.assertTrue(validate_phase_scope({**base, "inherits": ["shared/brand.md"], "start_stage": True},
                                            {"inherits": ["shared/brand.md"]}))

    def test_compact_inheritance_is_paginated_and_read_only(self):
        inherits = [f"shared/item-{i:03}.md" for i in range(30)]
        args = [arg for rel in inherits for arg in ("--inherit", rel)]
        self.cli("gate.py", "init", "--phase", "P1", *args)
        root = self.container / P.PHASES / "P1"
        before = {p: p.read_bytes() for p in self.container.rglob("*") if p.is_file()}
        payload = json.loads(self.cli("gate.py", "context", "--json", "--compact").stdout)
        self.assertEqual(len(payload["inherited"]), 5)
        self.assertEqual(payload["pagination"]["inherited"], {"total": 30, "next_offset": 5})
        page = json.loads(self.cli("gate.py", "context", "--json", "--section", "inherited",
                                   "--offset", "5", "--limit", "20").stdout)
        self.assertEqual(len(page["items"]), 20)
        self.assertEqual(page["next_offset"], 25)
        self.assertEqual({p: p.read_bytes() for p in self.container.rglob("*") if p.is_file()}, before)
        self.assertFalse(waitlib.delivered(str(root)))

    def test_next_json_outputs_long_note_only_once_without_losing_values(self):
        self.cli("gate.py", "init")
        root = self.container
        decision = root / P.DECISIONS / "D1"
        decision.mkdir()
        (decision / "question.json").write_text(json.dumps({"id": "D1", "stage": 0, "type": "gate",
                                                           "title": "确认范围", "context": "确认范围"}))
        note = "完整保留的用户要求" * 1000
        answer = {"id": "D1", "choice": ["approve"], "note": note, "value": {"间距": 0},
                  "ts": "2026-10-19T10:00:00+08:00", "answered_by": "user", "via": "web"}
        (decision / "answer.json").write_text(json.dumps(answer))
        result = self.cli("gate.py", "next", "--json")
        self.assertEqual(json.loads(result.stdout)["new"], [answer])
        self.assertEqual(result.stdout.count(note), 1)
        self.assertEqual(waitlib.delivered(str(root)), {"D1": answer["ts"]})
        self.assertEqual(waitlib.acked(str(root)), {})

    def test_scope_pass_enters_first_stage_remaining_in_track(self):
        self.cli("gate.py", "init")
        scope = {"phase_relation": "extend", "start_stage": 2, "layout_freedom": "keep", "track": "full"}
        (self.container / P.SCOPE).write_text(json.dumps(scope))
        with mock.patch.object(gate, "workflow_next", return_value={"status": "gate-ready", "blockers": []}):
            gate.cmd_pass(type("Args", (), {"root": str(self.container), "stage": 0})())
        state = gate.load_state(str(self.container))
        self.assertEqual(state["stage"], state["sequence"][1])
        self.assertIn(state["stage"], state["sequence"])

    def test_scope_next_and_pass_agree_on_incremental_track(self):
        self.cli("gate.py", "init", "--phase", "P1")
        root = self.container / P.PHASES / "P1"
        scope = {"mode": "new", "product_type": "site", "scope": "single", "layout_freedom": "keep",
                 "track": "fast", "user_customizable": False, "pages": ["首页"], "source_dirs": [],
                 "references": [], "asset_types": [], "phase_relation": "independent",
                 "inherit_mode": "none", "inherits": [], "start_stage": 3}
        (root / P.SCOPE).write_text(json.dumps(scope))
        decision = root / P.DECISIONS / "范围"
        decision.mkdir()
        (decision / "question.json").write_text(json.dumps({"id": "范围", "stage": 0, "type": "gate",
                                                           "role": "scope", "title": "本期范围", "context": "确认起点"}))
        answer = {"id": "范围", "choice": ["approve"], "answered_by": "user", "via": "web", "ts": "T1"}
        (decision / "answer.json").write_text(json.dumps(answer))
        self.cli("gate.py", "next", "--json")
        self.cli("decide_server.py", "ack", "范围", "--ts", "T1")
        flow = json.loads(self.cli("gate.py", "next", "--json").stdout)
        self.assertEqual(flow["status"], "gate-ready")
        self.assertIn("随后 gate.py check 3", flow["next"])
        self.cli("gate.py", "pass", "0")
        state = gate.load_state(str(root))
        self.assertEqual(state["stage"], 3)
        self.assertEqual(state["passed"], [0])


if __name__ == "__main__":
    unittest.main()
