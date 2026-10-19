#!/usr/bin/env python3
"""Claude Code PreToolUse hook：阻止越级写入、修改已通过阶段、伪造决策答案、拆分方案页。

在项目的 .claude/settings.json 里配置（路径按实际修改）：
{
  "hooks": {
    "PreToolUse": [
      {"matcher": "Write|Edit|MultiEdit|NotebookEdit",
       "hooks": [{"type": "command", "command": "python3 <skill目录>/scripts/stage_guard.py"}]}
    ]
  }
}
退出码 2 = 阻止该次工具调用，stderr 的内容会反馈给智能体。
"""
import json, os, sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from stages import STAGES, ALL, owner_of, host_of  # noqa: E402
import paths as P  # noqa: E402


def find_design_root(path):
    return P.find_root_for_path(path)


def block(msg):
    print("[stage_guard] 阻止：" + msg, file=sys.stderr)
    sys.exit(2)


def main():
    try:
        ev = json.load(sys.stdin)
    except Exception:
        sys.exit(0)
    ti = ev.get("tool_input") or {}
    path = ti.get("file_path") or ti.get("notebook_path")
    if not path:
        sys.exit(0)
    root = find_design_root(path)
    if not root:
        sys.exit(0)
    rel = os.path.relpath(os.path.abspath(path), root).replace(os.sep, "/")
    if rel.startswith(".."):
        sys.exit(0)
    with open(os.path.join(root, P.STATE), encoding="utf-8") as f:
        st = json.load(f)
    st.setdefault("sequence", list(ALL))
    cur = st["stage"]
    seq = st["sequence"]

    if rel.startswith(P.DECISIONS + "/") and "/answer" in rel and rel.endswith(".json"):
        block("answer.json 只能由用户在决策网页上提交（或经 gate.py record 登记对话中的原话）。不要自己写答案。")
    if rel == P.STATE or rel.startswith(P.RUNTIME + "/"):
        block("state.json 和 cache/runtime/ 只能由脚本修改。")
    if rel in (".gitignore", ".gitattributes", P.CONFIG):
        block("git 相关文件由 gate.py 管理：改素材策略请运行 gate.py media ignore|lfs|commit。")
    if rel.startswith(P.SUMMARY + "/"):
        block("record/summary/ 由脚本在作答时自动生成，不要手写；需要重建时运行 summary.py rebuild。")
    if rel == P.PENDING:
        sys.exit(0)  # 允许勾选/整理；新增条目请用 gate.py assume
    if rel.startswith("work/variants/") and rel.lower().endswith((".html", ".htm")) and rel != "work/variants/variants.html":
        block("所有方案必须写在 work/variants/variants.html 这一个页面里（每个方案一个 <template>），模板见 skill 的 templates/variants.html。")
    zone = rel.split("/", 1)[0]
    if zone not in P.ZONES and rel not in ("README.md",):
        block(f"{P.DIRNAME}/ 下只允许 record/ work/ media/ cache/ 四个区，{rel} 放错了位置（见 references/design-rules.md 0.11）。")

    owner = owner_of(rel)
    if owner is None or owner == "living":
        sys.exit(0)
    host = host_of(owner, st)
    if host is None:
        block(f"{rel} 属于阶段 {owner}（{STAGES[owner]['name']}），本项目的轨道省略了这个阶段。需要它就先和用户确认，再 gate.py rollback 0 重新定范围。")
    # proto/ 从阶段 4 起一直可写（令牌、打磨、铺开都会产生新版本）
    if rel.startswith("work/proto/") and 4 in seq and seq.index(cur) >= seq.index(4):
        sys.exit(0)
    hi, ci = seq.index(host), seq.index(cur)
    if hi > ci:
        block(f"{rel} 属于阶段 {owner}（{STAGES[owner]['name']}），当前只在阶段 {cur}（{STAGES[cur]['name']}）。"
              f"先完成本阶段并让用户在决策页验收，再 gate.py pass {cur}。")
    if hi < ci:
        block(f"{rel} 属于已通过的阶段 {owner}。修改它是变更：先向用户说明，再 gate.py rollback {host} --reason \"…\"。"
              f"（brief.md / traits.md 是活文档，随时可改）")
    sys.exit(0)


if __name__ == "__main__":
    main()
