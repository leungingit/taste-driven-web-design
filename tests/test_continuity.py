"""持续执行回归：真实临时项目、命令行和回环 HTTP，不访问宿主配置。"""
import contextlib
import itertools
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import time
import unittest
import urllib.error
import urllib.parse
import urllib.request
from http.server import ThreadingHTTPServer
from unittest import mock


SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))
import decide_server
import gate
import paths as P
import waitlib


class ContinuityTests(unittest.TestCase):
    """每例独立初始化，只有故障注入使用替身。"""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="taste-continuity-")
        self.addCleanup(self.tmp.cleanup)
        self.project = Path(self.tmp.name)
        self.root = self.project / P.DIRNAME
        self.cli("gate.py", "init")
        self.state(stage=2, passed=[0, 1], sequence=[0, 1, 2, 4, 9])
        self.write(P.SCOPE, {"mode": "new", "product_type": "site", "scope": "single",
                            "layout_freedom": "rearrange", "track": "full", "pages": ["首页"],
                            "asset_types": [], "references": [], "source_dirs": [],
                            "user_customizable": False})

    def write(self, rel, value):
        path = self.root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        text = json.dumps(value, ensure_ascii=False) if isinstance(value, (dict, list)) else value
        path.write_text(text, encoding="utf-8")
        return path

    def state(self, **changes):
        st = gate.load_state(str(self.root))
        st.update(changes)
        gate.save_state(str(self.root), st)

    def cli(self, script, *args, ok=True):
        result = subprocess.run([sys.executable, str(SCRIPTS / script), "--root", str(self.root), *args],
                                cwd=self.project, text=True, capture_output=True, timeout=10)
        if ok:
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        return result

    def question(self, did="验收", stage=2, answered=False, choice="approve", role=None):
        q = {"id": did, "stage": stage, "type": "gate", "title": "请验收当前阶段", "context": "检查产物后验收"}
        if role:
            q["role"] = role
        self.write(f"{P.DECISIONS}/{did}/question.json", q)
        if answered:
            self.answer(did, choice=choice)
        return q

    def answer(self, did="验收", choice="approve", ts="2026-10-19T10:00:00+08:00"):
        a = {"id": did, "choice": [choice], "answered_by": "user", "via": "web", "ts": ts,
             "note": "需要修正间距" if choice == "revise" else ""}
        self.write(f"{P.DECISIONS}/{did}/answer.json", a)
        return a

    def artifacts(self, stage):
        for rel in (f"{P.BRIEF}/brief.md", f"{P.BRIEF}/traits.md"):
            self.write(rel, f"版本：1\n同步至闸门：{stage}\n")
        if stage == 2:
            self.write("work/wireframe/index.html", "<html lang='zh-CN'><body>灰模</body></html>")
        elif stage == 4:
            self.write("work/assets/spec.md", "# 资产规范\n本项目没有独立图片资产。\n")
            self.write("work/proto/v1.html", "<html lang='zh-CN'><body>原型</body></html>")
        elif stage == 9:
            self.write("work/handoff/DESIGN.md", "# 设计交付\n")
            self.write("work/handoff/HANDOFF.md", "# 交付\n验证：打开首页检查结果。\n")

    @contextlib.contextmanager
    def server(self):
        store = decide_server.Store(str(self.root), 99)
        srv = ThreadingHTTPServer(("127.0.0.1", 0), decide_server.make_handler(store))
        thread = threading.Thread(target=srv.serve_forever, daemon=True)
        self.write(f"{P.RUNTIME}/.server.json", {"port": srv.server_port, "pid": os.getpid()})
        thread.start()
        try:
            yield f"http://127.0.0.1:{srv.server_port}"
        finally:
            srv.shutdown()
            srv.server_close()
            thread.join(timeout=3)

    def post(self, base, endpoint, body=None):
        req = urllib.request.Request(base + urllib.parse.quote(endpoint, safe="/"), json.dumps(body or {}).encode(),
                                     {"Content-Type": "application/json"}, method="POST")
        try:
            response = urllib.request.urlopen(req, timeout=3)
        except urllib.error.HTTPError as error:
            response = error
        with response:
            return response.status, response.read().decode()

    def hook(self, maximum=0):
        result = subprocess.run([sys.executable, str(SCRIPTS / "wait_hook.py"), "--max", str(maximum), "--idle", "0"],
                                input=json.dumps({"cwd": str(self.project)}), cwd=self.project,
                                text=True, capture_output=True, timeout=5)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        return json.loads(result.stdout) if result.stdout.strip() else {}

    def test_cli_next_reports_work_and_pending_decision(self):
        """没有待答决策时继续制作，创建决策后进入等待状态。"""
        payload = json.loads(self.cli("gate.py", "next", "--json").stdout)
        required = {"status", "action", "stage", "next", "blockers", "new", "open", "queued", "gate_ready", "completed"}
        self.assertTrue(required <= payload.keys())
        self.assertEqual(payload["status"], "working")
        self.question()
        payload = gate.workflow_next(str(self.root))
        self.assertEqual(payload["status"], "waiting")
        self.assertEqual(payload["open"], ["验收"])

    def test_context_is_read_only_and_stale_progress_cannot_advance_stage(self):
        """独立进程恢复以真实状态为准，不把工作记录或索引当作落实凭据。"""
        self.question(answered=True)
        self.write(P.PROGRESS, "# 当前工作记录\n对应阶段：9\n全部完成，可以交付并确认所有答案。\n")
        before = {p.relative_to(self.root): p.read_bytes() for p in self.root.rglob("*") if p.is_file()}
        payload = json.loads(self.cli("gate.py", "context", "--json").stdout)
        self.assertEqual(payload["flow"]["stage"], 2)
        self.assertEqual(payload["flow"]["status"], "processing")
        self.assertEqual(payload["passed"], [0, 1])
        self.assertEqual(payload["unacked"], [{"id": "验收", "ts": "2026-10-19T10:00:00+08:00"}])
        after = {p.relative_to(self.root): p.read_bytes() for p in self.root.rglob("*") if p.is_file()}
        self.assertEqual(after, before)
        refused = self.cli("decide_server.py", "ack", "验收", "--ts", payload["unacked"][0]["ts"], ok=False)
        self.assertNotEqual(refused.returncode, 0)
        self.assertFalse((self.root / P.RUNTIME / ".agent-acked.json").exists())

    def test_context_locates_missing_records_and_merged_stage_without_history_text(self):
        """缺失记录可定位，合并阶段可恢复，历史通过索引按需回查。"""
        (self.root / P.PROGRESS).unlink()
        self.state(stage=1, sequence=[0, 1, 2, 4, 9], passed=[0], merged={3: 1})
        for did, stage in (("当前", 1), ("合并", 3), ("历史", 0), ("未来", 4)):
            self.question(did, stage, answered=True)
        self.write(f"{P.SUMMARY}/README.md", "只在按需读取时出现的历史全文")
        result = self.cli("gate.py", "context", "--json")
        payload = json.loads(result.stdout)
        self.assertEqual({d["id"] for d in payload["decisions"]}, {"当前", "合并"})
        self.assertEqual({Path(p).name for p in payload["stage_guides"]}, {"stage-1.md", "stage-3.md"})
        records = {x["path"]: x["exists"] for x in payload["records"]}
        self.assertFalse(records[str(self.root / P.PROGRESS)])
        self.assertFalse(records[str(self.root / P.NOTES)])
        self.assertEqual(payload["history_index"], str(self.root / P.SUMMARY / "README.md"))
        self.assertNotIn("只在按需读取时出现的历史全文", result.stdout)
        for decision in payload["decisions"]:
            self.assertTrue(Path(decision["question"]).is_file())
            self.assertTrue(Path(decision["answer"]).is_file())

    def test_partial_application_survives_recovery_and_new_answer_version(self):
        """部分落实后换进程，完整要求仍可重交，新版本不能被旧确认吞掉。"""
        self.question(answered=True)
        first = json.loads(self.cli("gate.py", "next", "--json").stdout)["new"][0]
        self.write("work/wireframe/index.html", "<p>已完成标题排版，背景图尚未替换</p>")
        self.write(P.PROGRESS, f"当前任务：修改灰模\n已完成：标题排版\n下一步：替换背景图\n答案版本：{first['ts']}\n")
        updated = self.answer(ts="2026-10-19T10:02:00+08:00")
        updated.update(note="保留标题排版，替换背景图并关闭自动轮播", value="轮播间隔=0")
        self.write(f"{P.DECISIONS}/验收/answer.json", updated)
        self.write(P.NOTES, "N001：自动轮播；已被 N002 替代\nN002：关闭自动轮播；用户已明确；替代 N001\n")
        index = json.loads(self.cli("gate.py", "context", "--json").stdout)
        self.assertEqual(index["unacked"], [{"id": "验收", "ts": updated["ts"]}])
        refused = self.cli("decide_server.py", "ack", "验收", "--ts", first["ts"], ok=False)
        self.assertNotEqual(refused.returncode, 0)
        replay = json.loads(self.cli("gate.py", "next", "--json").stdout)
        self.assertEqual(replay["new"], [updated])
        self.assertIn("N002", (self.root / P.NOTES).read_text(encoding="utf-8"))
        self.assertEqual(json.loads(self.cli("gate.py", "next", "--json").stdout)["new"], [updated])
        self.write("work/wireframe/index.html", "<p>标题排版保留；背景图已替换；自动轮播已关闭</p>")
        self.cli("decide_server.py", "ack", "验收", "--ts", updated["ts"])
        self.assertEqual(json.loads(self.cli("gate.py", "context", "--json").stdout)["unacked"], [])
        self.assertEqual(gate.load_state(str(self.root))["stage"], 2)

    def test_reinitializing_keeps_existing_progress(self):
        """初始化生成工作记录，重入时不能覆盖已经写下的工作位置。"""
        self.assertIn("尚未完成与下一步", (self.root / P.PROGRESS).read_text(encoding="utf-8"))
        self.write(P.PROGRESS, "当前工作：保留已经核对的进度\n")
        self.cli("gate.py", "init")
        self.assertEqual((self.root / P.PROGRESS).read_text(encoding="utf-8"), "当前工作：保留已经核对的进度\n")
        self.assertEqual(gate.load_state(str(self.root))["stage"], 2)

    def test_invalid_layout_check_keeps_all_entry_points_available(self):
        """阶段产物格式错误时要求修复，网页、状态命令和续跑 hook 均保持可用。"""
        self.state(stage=3, sequence=[0, 1, 2, 3, 4, 9], passed=[0, 1, 2])
        self.write("work/variants/variants.html", '<html lang="zh-CN"><div data-intensity="大胆">方案</div></html>')
        self.write("work/variants/layout-check.json", '{"variants": 未完成的校验结果')
        payload = json.loads(self.cli("gate.py", "next", "--json").stdout)
        self.assertEqual(payload["status"], "working")
        self.assertEqual(payload["action"], "repair")
        self.assertIn("JSONDecodeError", json.dumps(payload, ensure_ascii=False))
        with self.server() as base:
            with urllib.request.urlopen(base + "/api/state", timeout=3) as response:
                self.assertEqual(response.status, 200)
                state = json.load(response)
        self.assertEqual(state["flow"]["action"], "repair")
        self.assertEqual(self.hook().get("decision"), "block")
        result = self.cli("gate.py", "status")
        self.assertNotIn("Traceback", result.stdout + result.stderr)
        self.assertIn("修复", result.stdout)

    def test_malformed_question_does_not_pollute_json_output(self):
        """损坏题目的诊断不得混入结构化输出，也不能被当作流程已完成。"""
        self.write(f"{P.DECISIONS}/损坏题目/question.json", '{"stage": 2, "type": 未完成')
        result = self.cli("gate.py", "next", "--json")
        payload = json.loads(result.stdout)
        self.assertNotEqual(payload["status"], "completed")
        self.assertFalse(payload["completed"])
        self.assertIn("损坏题目", json.dumps(payload["blockers"], ensure_ascii=False))
        self.assertIn("question.json", result.stderr)

    def test_running_cli_wait_receives_http_answer_and_replays_until_ack(self):
        """观察真实等待心跳后提交网页答案，进程交付完整结果并等待明确确认。"""
        self.artifacts(2)
        self.question()
        marker = self.root / P.RUNTIME / ".agent-waiting"
        with self.server() as base:
            process = subprocess.Popen([sys.executable, str(SCRIPTS / "decide_server.py"), "--root", str(self.root),
                                        "wait", "--chunk", "10", "--idle", "0"],
                                       cwd=self.project, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            try:
                deadline = time.monotonic() + 5
                while True:
                    heartbeat = waitlib.load_json(str(marker), {}) or {}
                    if heartbeat.get("pid") == process.pid and process.poll() is None:
                        break
                    if process.poll() is not None:
                        output, error = process.communicate()
                        self.fail("等待进程在心跳前退出：" + output + error)
                    if time.monotonic() >= deadline:
                        self.fail("等待进程未在期限内写入心跳")
                    time.sleep(0.01)
                self.assertEqual(self.post(base, "/api/answer/验收", {
                    "choice": ["approve"], "note": "标题间距已确认，可以继续"})[0], 200)
                output, error = process.communicate(timeout=5)
                self.assertEqual(process.returncode, 0, output + error)
            finally:
                if process.poll() is None:
                    process.terminate()
                    process.communicate(timeout=3)
        machine_line = next(line for line in output.splitlines() if line.startswith("RESULT "))
        payload = json.loads(machine_line[7:])
        self.assertEqual(payload["status"], "answered")
        persisted = waitlib.load_json(str(self.root / P.DECISIONS / "验收" / "answer.json"))
        self.assertEqual(payload["new"], [persisted])
        self.assertEqual(persisted["note"], "标题间距已确认，可以继续")
        replay = json.loads(self.cli("gate.py", "next", "--json").stdout)
        self.assertEqual(replay["status"], "processing")
        self.assertEqual(replay["new"], [persisted])
        self.cli("decide_server.py", "ack", "验收", "--ts", persisted["ts"])
        self.assertEqual(gate.workflow_next(str(self.root))["status"], "gate-ready")
        self.cli("gate.py", "pass", "2")
        self.assertEqual(gate.load_state(str(self.root))["stage"], 4)

    def test_current_and_merged_answers_only(self):
        """历史阶段和未来阶段答案不进入当前阶段的待落实队列。"""
        self.state(merged={3: 2})
        for did, stage in (("当前", 2), ("合并", 3), ("历史", 1), ("未来", 4)):
            self.question(did, stage, answered=True)
        self.assertEqual({a["id"] for a in waitlib.new_answers(str(self.root))}, {"当前", "合并"})

    def test_http_answer_repeats_until_exact_ack(self):
        """网页提交后可重复交付，只有精确确认已交付版本才移出队列。"""
        self.question()
        with self.server() as base:
            self.assertTrue(waitlib.server_alive(str(self.root)))
            self.assertEqual(self.post(base, "/api/answer/验收", {"choice": ["approve"]})[0], 200)
        answers = waitlib.new_answers(str(self.root))
        self.assertEqual(len(answers), 1)
        self.assertEqual(gate.workflow_next(str(self.root))["status"], "processing")
        with self.assertRaises(ValueError):
            waitlib.ack_answer(str(self.root), "验收", answers[0]["ts"])
        first = waitlib.deliver(str(self.root), answers)
        second = waitlib.deliver(str(self.root), waitlib.new_answers(str(self.root)))
        self.assertEqual(first["new"], second["new"])
        with self.assertRaises(ValueError):
            waitlib.ack_answer(str(self.root), "验收", "旧版本")
        waitlib.ack_answer(str(self.root), "验收", answers[0]["ts"])
        self.assertEqual(waitlib.new_answers(str(self.root)), [])

    def test_summary_failure_preserves_undelivered_answer(self):
        """摘要生成失败时保留答案，并且不能把失败的交付确认为已落实。"""
        self.question(answered=True)
        answers = waitlib.new_answers(str(self.root))
        with mock.patch.object(waitlib, "summary", side_effect=RuntimeError("模拟摘要失败")):
            with self.assertRaisesRegex(RuntimeError, "模拟摘要失败"):
                waitlib.deliver(str(self.root), answers)
        self.assertEqual(waitlib.new_answers(str(self.root)), answers)
        with self.assertRaises(ValueError):
            waitlib.ack_answer(str(self.root), "验收", answers[0]["ts"])
        waitlib.deliver(str(self.root), answers)
        waitlib.ack_answer(str(self.root), "验收", answers[0]["ts"])

    def test_new_answer_version_requires_new_delivery(self):
        """旧版确认不能吞掉新版本答案。"""
        self.question(answered=True)
        old = waitlib.new_answers(str(self.root))
        waitlib.deliver(str(self.root), old)
        self.answer(ts="2026-10-19T10:01:00+08:00")
        with self.assertRaises(ValueError):
            waitlib.ack_answer(str(self.root), "验收", old[0]["ts"])
        self.assertEqual(len(waitlib.new_answers(str(self.root))), 1)

    def test_stage_pass_uses_actual_sequence(self):
        """批准并落实后进入轨道的下一阶段，不进入被省略的阶段。"""
        self.artifacts(2)
        self.question(answered=True)
        answers = waitlib.new_answers(str(self.root))
        waitlib.deliver(str(self.root), answers)
        waitlib.ack_answer(str(self.root), "验收", answers[0]["ts"])
        self.assertEqual(gate.workflow_next(str(self.root))["status"], "gate-ready")
        self.cli("gate.py", "pass", "2")
        self.assertEqual(gate.load_state(str(self.root))["stage"], 4)
        self.assertEqual(gate.workflow_next(str(self.root))["status"], "working")

    def test_unacknowledged_approval_cannot_pass(self):
        """用户已批准仍需落实并确认，不能跳过答案处理直接过闸。"""
        self.artifacts(2)
        self.question(answered=True)
        result = self.cli("gate.py", "pass", "2", ok=False)
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(gate.load_state(str(self.root))["stage"], 2)

    def test_legacy_seen_marker_does_not_ack_answer(self):
        """旧版已读取记录不能被当作已落实，升级后答案仍可交付。"""
        self.question(answered=True)
        self.write(f"{P.RUNTIME}/.agent-seen.json", {"验收": "2026-10-19T10:00:00+08:00"})
        self.assertEqual(len(waitlib.new_answers(str(self.root))), 1)

    def test_revision_keeps_history_and_allows_new_gate(self):
        """不通过后落实修改，新建验收题可批准，同时保留旧修改意见。"""
        self.artifacts(2)
        self.question("首次验收")
        with self.server() as base:
            self.assertEqual(self.post(base, "/api/answer/首次验收", {"choice": ["revise"]})[0], 400)
            self.assertEqual(self.post(base, "/api/answer/首次验收", {
                "choice": ["revise"], "note": "缩小标题间距"})[0], 200)
            answers = waitlib.new_answers(str(self.root))
            waitlib.deliver(str(self.root), answers)
            waitlib.ack_answer(str(self.root), "首次验收", answers[0]["ts"])
            self.assertEqual(gate.workflow_next(str(self.root))["status"], "working")
            self.write("work/wireframe/index.html", "<html lang='zh-CN'><body>标题间距已缩小</body></html>")
            self.question("再次验收")
            self.assertEqual(self.post(base, "/api/answer/再次验收", {"choice": ["approve"]})[0], 200)
            answers = waitlib.new_answers(str(self.root))
            waitlib.deliver(str(self.root), answers)
            waitlib.ack_answer(str(self.root), "再次验收", answers[0]["ts"])
        self.assertEqual(gate.workflow_next(str(self.root))["status"], "gate-ready")
        old = waitlib.load_json(str(self.root / P.DECISIONS / "首次验收" / "answer.json"))
        self.assertEqual(old["choice"], ["revise"])
        self.assertEqual(old["note"], "缩小标题间距")
        self.cli("gate.py", "pass", "2")
        self.assertEqual(gate.load_state(str(self.root))["stage"], 4)

    def test_final_pass_completes_and_cannot_repeat(self):
        """最终闸门通过后收口，重复 pass 不追加通过历史。"""
        self.state(stage=9, passed=[0, 1, 2, 4])
        self.artifacts(9)
        self.question(stage=9, answered=True)
        answers = waitlib.new_answers(str(self.root))
        waitlib.deliver(str(self.root), answers)
        waitlib.ack_answer(str(self.root), "验收", answers[0]["ts"])
        self.cli("gate.py", "pass", "9")
        completed = gate.workflow_next(str(self.root))
        self.assertEqual(completed["status"], "completed")
        self.assertTrue(completed["completed"])
        before = gate.load_state(str(self.root))
        self.cli("gate.py", "pass", "9", ok=False)
        self.assertEqual(gate.load_state(str(self.root)), before)
        self.assertNotEqual(self.hook().get("decision"), "block")
        result = self.cli("decide_server.py", "wait", "--chunk", "0", ok=False)
        self.assertEqual(result.returncode, 15, result.stdout + result.stderr)
        machine_line = next(line for line in result.stdout.splitlines() if line.startswith("RESULT "))
        self.assertEqual(json.loads(machine_line[7:])["status"], "completed")
        self.assertIn("交付", result.stdout)

    def test_optional_stage_skip_needs_approval_and_ack(self):
        """可选阶段跳过必须批准且落实，之后直接进入实际后继阶段。"""
        self.state(stage=5, passed=[0, 1, 2, 4], sequence=[0, 1, 2, 4, 5, 6, 9], optional=[5])
        q = self.question("跳过令牌", stage=5, role="skip")
        q["skip_stage"] = 5
        q["context"] = "本轮只交付固定样张，令牌由智能体沿用现有取值，不新增主题配置。"
        self.write(f"{P.DECISIONS}/跳过令牌/question.json", q)
        refused = self.cli("gate.py", "skip", "5", "--reason", "本轮沿用现有令牌", ok=False)
        self.assertNotEqual(refused.returncode, 0)
        with self.server() as base:
            self.assertEqual(self.post(base, "/api/answer/跳过令牌", {"choice": ["approve"]})[0], 200)
            refused = self.cli("gate.py", "skip", "5", "--reason", "本轮沿用现有令牌", ok=False)
            self.assertNotEqual(refused.returncode, 0)
            answers = waitlib.new_answers(str(self.root))
            waitlib.deliver(str(self.root), answers)
            waitlib.ack_answer(str(self.root), "跳过令牌", answers[0]["ts"])
        self.assertEqual(gate.workflow_next(str(self.root))["action"], "skip")
        self.cli("gate.py", "skip", "5", "--reason", "本轮沿用现有令牌")
        st = gate.load_state(str(self.root))
        self.assertEqual(st["stage"], 6)
        self.assertEqual(st["passed"].count(5), 1)
        self.assertEqual(gate.workflow_next(str(self.root))["status"], "working")
        self.assertIn("跳过", (self.root / P.PENDING).read_text(encoding="utf-8"))

    def test_three_stage_http_journey_reaches_completion(self):
        """连续三次网页验收贯穿轨道，阶段之间无需人工续跑指令。"""
        with self.server() as base:
            for stage in (2, 4, 9):
                self.assertEqual(gate.workflow_next(str(self.root))["stage"], stage)
                self.artifacts(stage)
                did = f"验收-{stage}"
                self.question(did, stage)
                self.assertEqual(self.post(base, f"/api/answer/{did}", {"choice": ["approve"]})[0], 200)
                answers = waitlib.new_answers(str(self.root))
                self.assertEqual([a["id"] for a in answers], [did])
                waitlib.deliver(str(self.root), answers)
                waitlib.ack_answer(str(self.root), did, answers[0]["ts"])
                self.assertEqual(gate.workflow_next(str(self.root))["status"], "gate-ready")
                self.cli("gate.py", "pass", str(stage))
        self.assertEqual(gate.workflow_next(str(self.root))["status"], "completed")
        self.assertEqual(gate.load_state(str(self.root))["passed"], [0, 1, 2, 4, 9])

    def test_wait_timeout_and_idle_request_another_wait(self):
        """单段超时和长时间无作答都保留等待，不转为人工续跑。"""
        self.question()
        with self.server():
            status, payload = waitlib.wait(str(self.root), timeout=0, idle_minutes=0, poll=0.01)
            self.assertEqual(status, "timeout")
            self.assertIn("wait", payload["next"])
            self.assertNotIn("说「继续」", payload["next"])
            with mock.patch.object(waitlib, "time") as clock, \
                 mock.patch.object(waitlib, "last_activity", return_value=1000):
                clock.time.side_effect = itertools.chain([1000], itertools.repeat(1061))
                status, payload = waitlib.wait(str(self.root), timeout=540, idle_minutes=1, poll=0.01)
            self.assertEqual(status, "idle")
            self.assertIn("等待", payload["next"])
            self.assertNotIn("说「继续」", payload["next"])
            result = self.cli("decide_server.py", "wait", "--chunk", "0", "--idle", "0", ok=False)
            self.assertEqual(result.returncode, waitlib.STATUS["timeout"], result.stdout + result.stderr)
            machine_line = next(line for line in result.stdout.splitlines() if line.startswith("RESULT "))
            self.assertEqual(json.loads(machine_line[7:])["status"], "timeout")
            self.assertEqual(self.hook()["decision"], "block")
        self.assertEqual(waitlib.new_answers(str(self.root)), [])

    def test_disconnected_server_does_not_silently_end(self):
        """服务失联可诊断，hook 重复触发仍应指示恢复服务。"""
        self.question()
        status, payload = waitlib.wait(str(self.root), timeout=0, idle_minutes=0)
        self.assertEqual(status, "no-server")
        self.assertIn("serve", payload["next"])
        for _ in range(3):
            output = self.hook()
            self.assertEqual(output.get("decision"), "block", output)
            self.assertIn("服务", output["reason"])

    def test_unfinished_work_never_silently_allows_stop(self):
        """连续无进展不能悄悄放行，必须继续或解释明确阻塞。"""
        for _ in range(6):
            output = self.hook()
            if output.get("decision") != "block":
                self.assertEqual(gate.workflow_next(str(self.root))["status"], "blocked")
                self.assertTrue(output.get("systemMessage"), output)
                self.assertNotIn("说「继续」", output["systemMessage"])

    def test_http_pause_and_resume_preserve_workflow(self):
        """用户暂停后允许结束，恢复后沿原阶段继续等待。"""
        self.question()
        with self.server() as base:
            self.assertEqual(self.post(base, "/api/pause")[0], 200)
            self.assertEqual(gate.workflow_next(str(self.root))["status"], "paused")
            self.assertNotEqual(self.hook().get("decision"), "block")
            self.assertEqual(self.post(base, "/api/resume")[0], 200)
            self.assertEqual(gate.workflow_next(str(self.root))["status"], "waiting")
            self.assertEqual(self.hook().get("decision"), "block")
        self.assertEqual(gate.load_state(str(self.root))["stage"], 2)

    def test_explicit_block_and_unblock_are_reviewable(self):
        """真实外部阻塞必须记录尝试与用户动作，解除后回到原工作。"""
        self.cli("gate.py", "block", "--reason", "缺少用户提供的原始图片", "--tried", "检查了项目素材目录",
                 "--needs", "提供原始图片")
        flow = gate.workflow_next(str(self.root))
        self.assertEqual(flow["status"], "blocked")
        self.assertNotEqual(self.hook().get("decision"), "block")
        self.assertIn("原始图片", json.dumps(flow, ensure_ascii=False))
        self.cli("gate.py", "unblock", "--reason", "原始图片已补充")
        self.assertEqual(gate.workflow_next(str(self.root))["status"], "working")

    def test_http_flow_matches_cli_and_function(self):
        """网页与命令行使用同一下一步判定，避免运行入口互相矛盾。"""
        self.question()
        expected = gate.workflow_next(str(self.root))
        with self.server() as base:
            with urllib.request.urlopen(base + "/api/state", timeout=3) as response:
                state = json.load(response)
        cli = json.loads(self.cli("gate.py", "next", "--json").stdout)
        for key in ("status", "action", "stage", "open", "queued", "completed"):
            self.assertEqual(state["flow"][key], expected[key])
            self.assertEqual(cli[key], expected[key])


if __name__ == "__main__":
    unittest.main()
