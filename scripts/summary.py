#!/usr/bin/env python3
"""决策摘要卡：每个作答后的决策生成 record/summary/<ID>.md（含选项小缩略图），并维护 record/summary/README.md 总览。

摘要卡和缩略图都在 record/ 下、随仓库提交，所以即使 media/ 不提交，团队成员也能在代码托管网站上看到
每个决策问了什么、有哪些选项、最后选了什么、为什么。

  summary.py rebuild      重新生成全部摘要卡（gate.py / decide_server.py 在作答时会自动调用 write）
"""
import argparse, glob, json, os, sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import paths as P  # noqa: E402

THUMB_W = 360
TYPE_NAME = {"single": "单选", "multi": "多选", "scale": "刻度", "tune": "调参", "gate": "阶段验收"}
ORI = {"inbox": "创意素材", "search": "检索参考", "screenshot": "参考截图", "generated": "生成对照", "rendered": "代码渲染"}


def _load(p, default=None):
    try:
        with open(p, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return default


def _thumb(root, src_rel, out_name):
    """生成小缩略图（JPEG，宽 360），返回相对 summary 目录的路径；没有 Pillow 或失败时返回 None。"""
    try:
        from PIL import Image
    except ImportError:
        return None
    src = os.path.join(root, src_rel)
    if not os.path.isfile(src):
        return None
    out_rel = f"thumbs/{out_name}.jpg"
    out = os.path.join(root, P.SUMMARY, out_rel)
    try:
        if os.path.exists(out) and os.path.getmtime(out) >= os.path.getmtime(src):
            return out_rel
        im = Image.open(src)
        im.seek(0)
        im = im.convert("RGB")
        if im.width > THUMB_W:
            im = im.resize((THUMB_W, max(1, round(im.height * THUMB_W / im.width))), Image.LANCZOS)
        os.makedirs(os.path.dirname(out), exist_ok=True)
        im.save(out, "JPEG", quality=72, optimize=True)
        return out_rel
    except Exception:
        return None


def _media_cell(root, did, oid, media):
    cells = []
    for i, m in enumerate(media or []):
        t = m.get("type", "image")
        r = P.resolve_src(did, m.get("src", ""))
        if r is None:                       # 远程地址
            cells.append(f"[{'图片' if t == 'image' else t}]({m.get('src')})")
            continue
        rel, frag = r
        link = os.path.relpath(os.path.join(root, rel), os.path.join(root, P.SUMMARY)).replace(os.sep, "/") + frag
        if t == "image":
            th = _thumb(root, rel, f"{did}-{oid or 'q'}-{i}")
            cells.append(f"[![{oid or ''}]({th})]({link})" if th else f"[图片]({link})")
        elif t == "html":
            cells.append(f"[页面样张]({link})")
        elif t == "video":
            cells.append(f"[视频]({link})")
        else:
            cells.append(f"[链接]({m.get('src')})")
    return " ".join(cells) or "—"


def _src_note(media):
    notes = []
    for m in media or []:
        s = ORI.get(m.get("origin"), "")
        if m.get("ref"):
            s += f" {m['ref']}"
        if m.get("credit"):
            s += f" {m['credit']}"
        if s.strip():
            notes.append(s.strip())
    return "；".join(dict.fromkeys(notes))


def _esc(s):
    return str(s or "").replace("|", "\\|").replace("\n", " ")


def write(root, did):
    d = P.decision_dir(root, did)
    q = _load(os.path.join(d, "question.json"))
    a = _load(os.path.join(d, "answer.json"))
    if not q:
        return None
    os.makedirs(os.path.join(root, P.SUMMARY), exist_ok=True)
    chosen = set((a or {}).get("choice") or [])
    lines = [f"# {did} · {q.get('title', '')}", ""]
    meta = [f"阶段 {q.get('stage')}", TYPE_NAME.get(q.get("type"), q.get("type", ""))]
    if q.get("role"):
        meta.append(f"角色 {q['role']}")
    if q.get("reference"):
        meta.append(f"参考 {q['reference']}")
    lines.append("- " + " · ".join(meta))
    if a:
        opts = {o.get("id"): o for o in q.get("options") or []}
        pick = "、".join(f"{c} {opts.get(c, {}).get('label', '')}".strip() for c in a.get("choice") or []) or "—"
        by = {"user": "用户", "agent": "智能体代定"}.get(a.get("answered_by"), a.get("answered_by", ""))
        if a.get("setting"):
            st_ = a["setting"]
            vals = "、".join(f"{c} {opts.get(c, {}).get('label', '')}".strip() for c in st_["values"])
            lines.append(f"- 结论：**做成设置项**（维度 `{st_.get('axis')}`）：{vals}；默认 **{st_['default']} {opts.get(st_['default'], {}).get('label', '')}**（{by}，{a.get('via', '')}，{a.get('ts', '')}）")
            chosen.update(st_["values"])
        else:
            lines.append(f"- 结论：**{pick}**（{by}，{a.get('via', '')}，{a.get('ts', '')}）")
        if a.get("other"):
            lines.append(f"- 其他：{a['other']}")
        if a.get("note"):
            lines.append(f"- 备注：{a['note']}")
        if a.get("quote"):
            lines.append(f"- 用户原话：{a['quote']}")
    else:
        lines.append("- 结论：待作答")
    if q.get("context"):
        lines += ["", "> " + q["context"].replace("\n", "\n> ")]
    if q.get("media"):
        lines += ["", "题目附图：" + _media_cell(root, did, None, q["media"])]
    opts = list(q.get("options") or [])
    if opts:
        opts.sort(key=lambda o: (o.get("id") not in chosen,))
        lines += ["", "| 选项 | 样例 | 说明 |", "|---|---|---|"]
        for o in opts:
            name = f"{o.get('id')} {o.get('label', '')}".strip()
            name = f"✅ **{_esc(name)}**" if o.get("id") in chosen else _esc(name)
            desc = [o.get("desc"), o.get("intensity") and f"力度：{o['intensity']}", o.get("motion") and f"动效：{o['motion']}",
                    _src_note(o.get("media"))]
            lines.append(f"| {name} | {_media_cell(root, did, o.get('id'), o.get('media'))} | {_esc('；'.join(x for x in desc if x))} |")
    if a and a.get("value"):
        lines += ["", "提交的数值：", "", "```", str(a["value"]).strip(), "```"]
    old = sorted(glob.glob(os.path.join(d, "answer.superseded-*.json")))
    if old:
        lines += ["", "历史作答（回退前）："]
        for f in old:
            x = _load(f, {})
            lines.append(f"- {x.get('ts', '')}：{','.join(x.get('choice') or []) or '—'}{'；' + x['note'] if x.get('note') else ''}")
    with open(os.path.join(root, P.SUMMARY, f"{did}.md"), "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    index(root)
    return did


def index(root):
    try:
        from stages import STAGES
    except Exception:
        STAGES = {}
    rows = []
    for qp in sorted(glob.glob(os.path.join(root, P.DECISIONS, "*", "question.json"))):
        d = os.path.dirname(qp)
        did = os.path.basename(d)
        q = _load(qp, {})
        a = _load(os.path.join(d, "answer.json"))
        if not a:
            continue
        opts = {o.get("id"): o.get("label", "") for o in q.get("options") or []}
        pick = "、".join(f"{c} {opts.get(c, '')}".strip() for c in a.get("choice") or []) or (a.get("other") or "已提交数值")
        if a.get("setting"):
            pick = f"设置项 {'/'.join(a['setting']['values'])}（默认 {a['setting']['default']}）"
        rows.append((q.get("stage", 0), a.get("ts", ""), did, q.get("title", ""), pick, a.get("answered_by", ""), a.get("note", "")))
    rows.sort()
    out = ["# 决策总览", "", "由 summary.py 自动生成。每行链接到该决策的摘要卡（选项、缩略图、结论、备注）。", ""]
    cur = None
    for st, ts, did, title, pick, by, note in rows:
        if st != cur:
            cur = st
            out += ["", f"## 阶段 {st} {STAGES.get(st, {}).get('name', '')}", "", "| 决策 | 结论 | 作答 | 时间 | 备注 |", "|---|---|---|---|---|"]
        out.append(f"| [{did} {_esc(title)}]({did}.md) | {_esc(pick)} | {'用户' if by == 'user' else '智能体代定'} | {ts[:16]} | {_esc(note)[:60]} |")
    pend = os.path.join(root, P.PENDING)
    if os.path.exists(pend):
        out += ["", f"智能体代定、待复核的事项见 [pending-review.md](../pending-review.md)。"]
    with open(os.path.join(root, P.SUMMARY, "README.md"), "w", encoding="utf-8") as f:
        f.write("\n".join(out) + "\n")


def rebuild(root):
    n = 0
    for qp in sorted(glob.glob(os.path.join(root, P.DECISIONS, "*", "question.json"))):
        if os.path.exists(os.path.join(os.path.dirname(qp), "answer.json")):
            write(root, os.path.basename(os.path.dirname(qp)))
            n += 1
    index(root)
    return n


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--root", default=None)
    ap.add_argument("cmd", choices=["rebuild"])
    a = ap.parse_args()
    root = a.root or P.default_root()
    print(f"[summary] 已生成 {rebuild(root)} 张决策摘要卡 → {os.path.join(root, P.SUMMARY)}")
