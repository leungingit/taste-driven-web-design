"""设置项（主题 / 外观维度）的规格与校验。规格文件：.taste-design/work/theme/axes.json

{
  "prototype": "../proto/v003.html",                 # 相对 work/theme/，主题画廊和矩阵脚本用它渲染
  "invariants": ["字号比例 1.25", "8px 间距网格", ...],   # 所有主题都不变的东西，至少 3 条
  "presets": [                                        # 完整设计过的主题预设，最多 3 套（可以没有）
    {"id": "aurora", "label": "极光", "source_decision": "D05-dir", "approved_by": "D12-preset-aurora"}
  ],
  "axes": [                                           # 互相独立的外观维度，最多 4 个，每个 2–4 个值
    {"id": "mode", "label": "明暗", "values": ["light", "dark"], "default": "light",
     "who": "夜间使用或长时间使用的用户", "source_decision": "D07-mode"},
    {"id": "density", "label": "密度", "kind": "layout", "area": "数据表格与列表",
     "values": ["comfortable", "compact"], "default": "comfortable", "who": "...", "source_decision": "D08"}
  ],
  "default": {"preset": "aurora", "mode": "light", "density": "comfortable"},
  "max_combinations": 12,                             # 预设数 × 各维度取值数之积，默认上限 12，最多 24
  "contrast_pairs": [["--color-text", "--color-bg", 4.5], ["--color-on-accent", "--color-accent", 4.5]],
  "declined": [                                       # 用户选了「做成设置项」但判断为「难以取舍」而退回的
    {"decision": "D09-layout", "reason": "属于方向犹豫，不是用户偏好", "resolved_by": "D10-layout-final"}
  ]
}

实现约定（tokens.css）：默认值写在 :root；每个非默认值写成 [data-<维度>="<值>"] 覆盖语义令牌；
预设写成 [data-preset="<id>"]。组件只引用语义令牌，不直接写色值。
"""
import itertools, json, os, re, sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import paths as P  # noqa: E402

AXES = "work/theme/axes.json"
GALLERY = "work/theme/gallery.html"
MATRIX = "work/qa/theme-matrix.json"
MAX_PRESETS, MAX_AXES, CAP = 3, 4, 24


def load(root):
    p = os.path.join(root, AXES)
    if not os.path.exists(p):
        return None
    with open(p, encoding="utf-8") as f:
        return json.load(f)


def dims(spec):
    """[(维度名, [取值...])...]，预设作为名为 preset 的维度放在最前。"""
    out = []
    if spec.get("presets"):
        out.append(("preset", [p["id"] for p in spec["presets"]]))
    for a in spec.get("axes") or []:
        out.append((a["id"], list(a.get("values") or [])))
    return out


def combos(spec):
    d = dims(spec)
    if not d:
        return []
    keys = [k for k, _ in d]
    return [dict(zip(keys, vals)) for vals in itertools.product(*[v for _, v in d])]


def combo_key(c):
    return ",".join(f"{k}={v}" for k, v in c.items())


def setting_answers(decisions):
    """从决策列表里找出用户选了「做成设置项」的答案。"""
    return [d for d in decisions if d.get("_answer") and d["_answer"].get("setting")]


def answered(decisions, did):
    return any(d["id"] == did and d.get("_answer") for d in decisions)


def validate(root, spec, decisions, scope):
    errs = []
    if spec is None:
        return ["缺少 work/theme/axes.json（外观开放给最终用户时必须有，模板见 theme.py 顶部说明）"]
    if len(spec.get("invariants") or []) < 3:
        errs.append("axes.json 的 invariants（所有主题都不变的东西）至少写 3 条，如字号比例、间距网格、图标风格、信息层级、文案语气")
    presets, axes = spec.get("presets") or [], spec.get("axes") or []
    if len(presets) > MAX_PRESETS:
        errs.append(f"主题预设最多 {MAX_PRESETS} 套，现在 {len(presets)} 套")
    if len(axes) > MAX_AXES:
        errs.append(f"外观维度最多 {MAX_AXES} 个，现在 {len(axes)} 个")
    ids = set()
    for a in axes:
        aid = a.get("id")
        if not aid or aid in ids or aid == "preset":
            errs.append(f"维度 id 缺失、重复或使用了保留名 preset：{aid}")
        ids.add(aid)
        vals = a.get("values") or []
        if not 2 <= len(vals) <= 4:
            errs.append(f"维度 {aid} 需要 2–4 个取值")
        if a.get("default") not in vals:
            errs.append(f"维度 {aid} 的 default 不在取值里")
        if not (a.get("who") or "").strip():
            errs.append(f"维度 {aid} 需要 who：哪类用户、什么场景会选非默认值（说不出来就不该做成设置）")
        if a.get("kind") == "layout" and not (a.get("area") or "").strip():
            errs.append(f"布局类维度 {aid} 需要 area：只作用于哪个局部区域（不允许整页换结构）")
    for pr in presets:
        if not pr.get("approved_by") or not answered(decisions, pr["approved_by"]):
            errs.append(f"预设 {pr.get('id')} 需要 approved_by 指向一个已作答的验收决策（每套预设都要整体验收）")
    dflt = spec.get("default") or {}
    for k, vals in dims(spec):
        if dflt.get(k) not in vals:
            errs.append(f"default 里缺少维度 {k} 的默认值，或默认值无效")
    n = len(combos(spec))
    limit = min(int(spec.get("max_combinations") or 12), CAP)
    if n > limit:
        errs.append(f"组合数 {n} 超过上限 {limit}：减少维度或取值（组合太多就测不完，说明设置太多了）")
    if not spec.get("contrast_pairs"):
        errs.append("axes.json 需要 contrast_pairs：要检查对比度的语义令牌对，如 [\"--color-text\", \"--color-bg\", 4.5]")
    # 每个「做成设置项」的答案都要落到规格里，或者被明确退回
    referenced = {x.get("source_decision") for x in axes + presets}
    declined = {x.get("decision"): x for x in spec.get("declined") or []}
    for d in setting_answers(decisions):
        did = d["id"]
        if did in declined:
            x = declined[did]
            if not x.get("reason") or not x.get("resolved_by") or not answered(decisions, x["resolved_by"]):
                errs.append(f"{did} 被退回为「难以取舍」，需要写明 reason，并有一个已作答的 resolved_by 决策让用户选定一个")
        elif did not in referenced:
            errs.append(f"{did} 用户选了做成设置项（{'/'.join(d['_answer']['setting']['values'])}），但 axes.json 里没有对应的维度或预设，也没有退回记录")
        elif not (scope or {}).get("user_customizable"):
            errs.append(f"{did} 做成了设置项，但 scope.json 的 user_customizable 是 false")
    # tokens.css 里要有每个非默认值的覆盖
    tokens = ""
    tp = os.path.join(root, "work", "tokens.css")
    if os.path.exists(tp):
        with open(tp, encoding="utf-8") as f:
            tokens = f.read()
    for k, vals in dims(spec):
        for v in vals:
            if v == dflt.get(k):
                continue
            if not re.search(rf'\[data-{re.escape(k)}=["\']?{re.escape(v)}["\']?\]', tokens):
                errs.append(f"work/tokens.css 缺少 [data-{k}=\"{v}\"] 的语义令牌覆盖")
    if not os.path.exists(os.path.join(root, GALLERY)):
        errs.append("缺少 work/theme/gallery.html（主题画廊，模板 templates/theme-gallery.html）")
    return errs


def validate_matrix(root, spec):
    errs = []
    want = {combo_key(c) for c in combos(spec)}
    if len(want) <= 1:
        return errs
    p = os.path.join(root, MATRIX)
    if not os.path.exists(p):
        return [f"缺少 {MATRIX}：运行 theme_matrix.py 为每个组合截图并检查对比度"]
    with open(p, encoding="utf-8") as f:
        rows = json.load(f).get("combos", [])
    got = {r.get("key"): r for r in rows}
    miss = sorted(want - set(got))
    if miss:
        errs.append(f"主题矩阵缺少这些组合：{miss[:6]}{'…' if len(miss) > 6 else ''}（重新运行 theme_matrix.py）")
    bad = [k for k, r in got.items() if k in want and not r.get("contrast_ok")]
    if bad:
        errs.append(f"这些组合对比度不达标：{bad[:6]}")
    noshot = [k for k, r in got.items() if k in want and not os.path.exists(os.path.join(root, r.get("shot", "") or "-"))]
    if noshot:
        errs.append(f"这些组合缺少截图：{noshot[:6]}")
    return errs
