#!/usr/bin/env python3
"""Claude Code 的停止护栏：未完成时交还控制，超时不等于流程完成。

仅在实际宿主验证 hook 会被调用且 block 会生效后，才能依赖它接续。
默认仍由智能体在活跃回合内运行分段 wait。配置见 references/runtime.md。
"""
import argparse, glob, json, os, sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import waitlib  # noqa: E402
from gate import workflow_next  # noqa: E402


def allow(msg=None):
    if msg:
        print(json.dumps({"systemMessage": msg}, ensure_ascii=False))
    sys.exit(0)


def block(reason):
    print(json.dumps({"decision": "block", "reason": reason}, ensure_ascii=False))
    sys.exit(0)


def keep_working(root, st=None):
    """无进展只触发诊断，不静默结束；有真实外部阻塞时显式登记。"""
    flow = workflow_next(root)
    if flow["status"] in ("completed", "paused", "blocked"):
        allow(flow["next"])
    files = glob.glob(os.path.join(root, "record", "**", "*"), recursive=True)
    files += glob.glob(os.path.join(root, "work", "**", "*"), recursive=True)
    newest = max((os.stat(f).st_mtime_ns for f in files if os.path.isfile(f)), default=0)
    g = waitlib.load_json(waitlib._p(root, ".hook-continue"), {}) or {}
    n = g.get("n", 0) + 1 if g.get("newest") == newest and g.get("stage") == flow["stage"] else 1
    waitlib.save_runtime(root, ".hook-continue", {"n": n, "newest": newest, "stage": flow["stage"]})
    hint = flow["next"]
    if n > 3:
        hint += ("\n连续多次未见阶段产物进展。先核对 next 的 blockers、命令错误和实际源码变更，"
                 "执行一个可验证的修复；不能以更新日志代替进展。确有需用户处理的外部阻塞时，"
                 "用 gate.py block --reason 原因 --tried 已尝试措施 --needs 具体所需操作 登记并报告；不要让用户仅说继续。")
    block(hint)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--max", type=float, default=45, help="单段等待秒数，须小于 hook 时限；到时交还智能体续接")
    ap.add_argument("--idle", type=float, default=0, help="空闲提示间隔（分钟）；到时仍需续接，0 为不提示")
    a = ap.parse_args()
    try:
        ev = json.load(sys.stdin)
    except Exception:
        ev = {}
    root = waitlib.find_root(ev.get("cwd") or os.getcwd())
    if not root:
        allow()
    flow = workflow_next(root)
    if flow["status"] in ("completed", "paused", "blocked"):
        allow(flow["next"])
    if flow["new"]:
        block(reason_for(waitlib.deliver(root, flow["new"])))
    st = waitlib.load_json(os.path.join(root, waitlib.P.STATE), {})
    if flow["status"] == "waiting" and st.get("channel", "web") != "web":
        allow("等待 inline/static 用户决策；这只是交互等待，设计任务仍未完成，收到答复后接续同一流程。")
    if flow["status"] != "waiting":
        keep_working(root)
    if not waitlib.server_alive(root):
        block("决策服务未连接。检查错误并恢复 decide_server.py serve，再运行分段 wait；恢复失败且确需用户处理时，"
              "用 gate.py block 记录原因、已尝试措施与具体所需操作。不能静默放行或要求用户说继续。")
    status, payload = waitlib.wait(root, a.max, a.idle, who="stop-hook")
    if status == "answered":
        block(reason_for(payload))
    if status in ("completed", "paused", "blocked"):
        allow(payload["next"])
    block(payload["next"] + "\n继续执行当前流程；需要等待时在活跃回合内运行 wait --chunk 45 --idle 0，工具分段返回后续接。")


def reason_for(p):
    return ("用户已提交尚未落实确认的答案：\n" + p["new_text"] +
            "\n完整版本与数值见 gate.py next --json。落实后逐项运行 decide_server.py ack ID --ts 原版本时间戳。"
            + "\n下一步：" + p["next"])


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        block(f"设计流程状态读取或等待失败（{type(e).__name__}）：{e}。保留当前进度，检查 gate.py next --json 的具体错误并修复；"
              "不要把工具异常当作完成。确需用户处理时用 gate.py block 登记具体原因、已尝试措施和所需操作。")
