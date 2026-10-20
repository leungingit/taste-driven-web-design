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
import delivery as DL  # noqa: E402


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
        try:
            root = P.find_root_phase(ev.get("cwd") or os.getcwd()) or P.find_root_phase(os.path.dirname(os.path.abspath(path)))
            if not root:
                sys.exit(0)
            from stages import load_scope
            from gate import decisions, load_state
            sc = load_scope(root) or {}
            st = load_state(root)
            sealed = st.get("delivery_boundary") or {}
            mode = sc.get("delivery_mode")
            if mode or sealed or st["stage"] == 0:
                selected = DL.decision(decisions(root))
                if not selected or selected["mode"] != mode or (0 in st.get("passed", []) and sealed != selected):
                    block("交付边界未确认或被改写；先完成阶段 0 的用户选择，变更需 rollback 0。")
                if mode == "design-only":
                    project = DL.project_root(root)
                    rel = os.path.relpath(os.path.abspath(path), project).replace(os.sep, "/")
                    shared = os.path.join(P.find_container(root) or root, P.SHARED)
                    shared_rel = os.path.relpath(os.path.abspath(path), shared)
                    in_shared = not shared_rel.startswith("..") and os.path.realpath(path) == os.path.join(os.path.realpath(shared), shared_rel)
                    if not DL.allowed_document(project, rel, DL.documents_approved(decisions(root))) and not in_shared:
                        block("用户选择了仅设计：只能写设计产物；AGENTS.md、docs/design-system.md 的关联说明需另行获得用户文档同步确认，不得修改工程实现。")
                elif 0 not in st.get("passed", []):
                    block("先通过闸门 0 确认交付边界，再修改工程实现。")
        except (ValueError, OSError, TypeError, KeyError) as e:
            block(f"无法核实交付边界：{e}")
        sys.exit(0)
    rel = os.path.relpath(os.path.abspath(path), root)
    if os.path.realpath(path) != os.path.join(os.path.realpath(root), rel):
        block("设计产物路径经过符号链接，无法保证写入仍在设计目录内。")
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
    if rel in (P.STATE, DL.BASELINE) or rel.startswith(P.RUNTIME + "/"):
        block("state.json、工程指纹基线和 cache/runtime/ 只能由脚本修改。")
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
