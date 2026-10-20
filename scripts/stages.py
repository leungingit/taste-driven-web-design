"""阶段定义与轨道计算，gate.py / decide_server.py / stage_guard.py 共用。"""
import json, os, sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import paths as P  # noqa: E402

# 所有路径相对 .taste-design/；目录划分见 paths.py
STAGES = {
    0: {"name": "启动与范围", "files": [P.SCOPE], "globs": [], "owns": [P.SCOPE, P.BASELINE + "/"]},
    1: {"name": "创意简报", "files": [f"{P.BRIEF}/brief.md", f"{P.BRIEF}/traits.md", f"{P.BRIEF}/content.yaml", f"{P.BRIEF}/constraints.yaml"],
        "globs": [], "owns": [P.BRIEF + "/"]},
    2: {"name": "信息架构（灰模）", "files": [], "globs": ["work/wireframe/*.html"], "owns": ["work/wireframe/"]},
    3: {"name": "视觉发散", "files": ["work/variants/variants.html"], "globs": [], "owns": ["work/variants/"]},
    4: {"name": "原型与资产规范", "files": ["work/assets/spec.md"], "globs": ["work/proto/v*.html"],
        "owns": ["work/proto/", "work/assets/", P.ASSET_MEDIA + "/"]},
    5: {"name": "设计令牌定稿", "files": ["work/tokens.css"], "globs": ["work/playgrounds/*.html"], "owns": ["work/playgrounds/", "work/tokens.css", "work/theme/"]},
    6: {"name": "区块打磨", "files": [], "globs": ["work/proto/v*.html"], "owns": []},
    7: {"name": "全站铺开", "files": ["work/rollout/pages.json", "work/rollout/overview.html"], "globs": [],
        "owns": ["work/rollout/", P.SHOTS + "/rollout/"]},
    8: {"name": "质量检查", "files": ["work/qa/report.md"], "globs": [], "owns": ["work/qa/", P.SHOTS + "/qa/"]},
    9: {"name": "交付", "files": ["work/handoff/DESIGN.md", "work/handoff/HANDOFF.md"], "globs": [], "owns": ["work/handoff/"]},
}
ALL = sorted(STAGES)

# 任何阶段都可以写的"活文档"和过程文件：每过一个闸门都要同步
LIVING = [f"{P.BRIEF}/brief.md", f"{P.BRIEF}/traits.md", P.PENDING, P.LOG, P.CHANGELOG, P.REFS, P.NOTES, P.PROGRESS,
          P.SUMMARY + "/", P.SAMPLES + "/", P.INBOX + "/", P.KEYFRAMES + "/", P.SHOTS + "/gates/", "cache/"]

SCOPE_ENUMS = {
    "mode": {"new", "redesign"},
    "product_type": {"site", "app"},
    "scope": {"single", "sample-then-rollout", "all-pages"},
    "layout_freedom": {"keep", "rearrange", "restructure"},
    "track": {"full", "fast"},
    "delivery_mode": {"design-only", "design-and-implement"},
}


def load_scope(root):
    p = os.path.join(root, P.SCOPE)
    if not os.path.exists(p):
        return None
    with open(p, encoding="utf-8") as f:
        return json.load(f)


def page_name(p):
    return p if isinstance(p, str) else (p or {}).get("name")


def in_scope_pages(sc):
    """pages 里每项可以是字符串（本期要做）或 {"name":…, "in_scope": true/false, "reason": …}。"""
    out = []
    for p in (sc or {}).get("pages") or []:
        if isinstance(p, str) or p.get("in_scope", True):
            out.append(page_name(p))
    return out


def validate_scope(sc):
    errs = []
    for k, vals in SCOPE_ENUMS.items():
        if sc.get(k) not in vals:
            errs.append(f"scope.json 的 {k} 必须是 {sorted(vals)}")
    for k in ("asset_types", "references", "pages", "source_dirs"):
        if not isinstance(sc.get(k, []), list):
            errs.append(f"scope.json 的 {k} 必须是列表")
    if not sc.get("pages"):
        errs.append("scope.json 必须列出全部可导航的页面与分页（pages），本期不做的也要列出并标 in_scope: false")
    elif not in_scope_pages(sc):
        errs.append("pages 里至少要有一个本期要做的页面")
    for p in sc.get("pages") or []:
        if isinstance(p, dict) and not p.get("in_scope", True) and not p.get("reason"):
            errs.append(f"页面「{page_name(p)}」标为本期不做，需要写 reason")
    if not isinstance(sc.get("user_customizable"), bool):
        errs.append("scope.json 需要 user_customizable（true/false）：外观参数是否开放给最终用户在产品里调整")
    elif sc["user_customizable"] and sc.get("customization_page") not in in_scope_pages(sc):
        errs.append("外观参数开放给最终用户时，customization_page（如「设置 → 主题」）必须是本期要做的页面")
    if sc.get("scope") == "single" and len(in_scope_pages(sc)) > 1:
        errs.append("scope 为 single 时只能有一个本期要做的页面；多页请选 sample-then-rollout 或 all-pages")
    return errs


def validate_phase_scope(sc, meta, container=None):
    """多期项目的本期接续声明；单期返回空。"""
    if not meta or not sc:
        return []
    errs = []
    relation = sc.get("phase_relation")
    if relation not in {"independent", "extend", "rework"}:
        errs.append("多期项目的 scope.json 需要 phase_relation：independent / extend / rework")
    inherit = sc.get("inherit_mode")
    if inherit not in {"none", "shared", "explicit"}:
        errs.append("多期项目的 scope.json 需要 inherit_mode：none / shared / explicit")
    start = sc.get("start_stage")
    if type(start) is not int or start not in {0, 2, 3, 4, 5, 6}:
        errs.append("多期项目的 scope.json 需要 start_stage，取值 0 / 2 / 3 / 4 / 5 / 6；从阶段 0 完整开始也显式写 0")
    for value in (meta.get("inherits", []), sc.get("inherits", [])):
        if not isinstance(value, list) or any(not isinstance(x, str) for x in value):
            errs.append("phase.json 与 scope.json 的 inherits 必须是路径字符串列表")
            return errs
        for rel in value:
            try:
                P.inheritance_path(container or os.path.abspath(P.DIRNAME), rel)
            except ValueError as e:
                errs.append(str(e))
    declared = {os.path.normpath(x.replace("\\", "/")) for x in meta.get("inherits", [])}
    scoped = {os.path.normpath(x.replace("\\", "/")) for x in sc.get("inherits", [])}
    if inherit == "none" and (declared or scoped):
        errs.append("inherit_mode 为 none 时不能再声明 inherits；若确需继承，先改 inherit_mode")
    if inherit in {"shared", "explicit"} and not (declared or scoped):
        errs.append(f"inherit_mode 为 {inherit} 时需要在 phase.json 或 scope.json 写明 inherits")
    if declared != scoped:
        errs.append(f"phase.json 与 scope.json 的 inherits 不一致：{sorted(declared)} ≠ {sorted(scoped)}")
    if inherit == "shared" and any(not x.startswith("shared/") for x in declared | scoped):
        errs.append("inherit_mode 为 shared 时只能继承 shared/ 内的路径；其他来源请使用 explicit")
    return errs


def plan(sc):
    """根据范围算出阶段序列、合并关系、可选阶段。"""
    seq = list(ALL)
    merged, optional = {}, []
    if sc is None:
        return {"sequence": seq, "merged": merged, "optional": optional}
    if sc.get("phase_relation") and isinstance(sc.get("start_stage"), int):
        start = sc["start_stage"]
        if start:
            seq = [0] + [s for s in seq if s >= start]
    if sc.get("layout_freedom") == "keep":
        if 2 in seq:
            seq.remove(2)                  # 保留布局：不做灰模
    if sc.get("scope") == "single":
        if 7 in seq:
            seq.remove(7)                  # 单页：不需要全站铺开
    if sc.get("track") == "fast":
        if 3 in seq:
            seq.remove(3)
            if 1 in seq:
                merged[3] = 1              # 快速轨道：方向选择并入简报闸门
            else:
                seq.append(3)
                seq.sort()
        if not sc.get("user_customizable") and 5 in seq:
            optional.append(5)             # playground 可跳过，但要进待复核清单；外观开放给用户时不可跳过（要定设置项）
    return {"sequence": seq, "merged": merged, "optional": optional}


def host_of(stage, st):
    """该阶段的工作在哪个阶段进行（被合并时返回宿主阶段；被省略返回 None）。"""
    merged = {int(k): v for k, v in (st.get("merged") or {}).items()}
    if stage in merged:
        return merged[stage]
    return stage if stage in st.get("sequence", ALL) else None


def owner_of(rel):
    """.taste-design/ 下相对路径属于哪个阶段；活文档返回 'living'；未知返回 None。"""
    for p in LIVING:
        if rel == p or rel.startswith(p):
            return "living"
    for s in ALL:
        for p in STAGES[s]["owns"]:
            if rel == p or rel.startswith(p):
                return s
    return None
