#!/usr/bin/env python3
"""视觉发散的力度检查：量化每个方案的布局和参照布局差多少，防止「克制 / 中等 / 大胆」只是换了点样式。

  variants_check.py [--root .taste-design] [--width 1440]

做法：用浏览器渲染 work/variants/variants.html 里的每个方案，提取主要布局块（面积够大、不是纯包裹层的元素），
按位置和大小计算两个方案之间的「布局相似度」（0–1，1 表示布局块几乎完全重合）。

参照布局（按优先级）：variants.html 里 data-role="reference" 的模板（改版项目放现状页面、新项目放灰模）
→ work/wireframe/ 下第一个 HTML → 第一个克制方案。

规则（layout_freedom 为 keep 时只检查克制，其余档位改为在同一布局内比表现力）：
  克制  与参照相似度 ≥ 0.55     布局基本保持，样式和表现形式调整
  中等  与参照相似度 ≤ 0.55，且与每个克制方案 ≤ 0.6     布局有调整
  大胆  与参照相似度 ≤ 0.25，且与每个中等方案 ≤ 0.4      布局被颠覆
另外每个方案要写 data-skeleton（布局骨架一句话），大胆方案要写 data-break（颠覆了什么：
导航范式 / 阅读顺序 / 页面隐喻 / 交互方式 / 信息组织）。

结果写入 work/variants/layout-check.json，gate.py 闸门 3 会读取。
"""
import argparse, glob, json, os, re, sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import paths as P  # noqa: E402

TH = {"keep_min": 0.55, "mid_max": 0.55, "mid_vs_keep": 0.6, "bold_max": 0.25, "bold_vs_mid": 0.4}
OUT = "work/variants/layout-check.json"

JS_BLOCKS = """(maxScreens) => {
  const vw = innerWidth, vh = innerHeight;
  const H = Math.min(document.documentElement.scrollHeight, vh * maxScreens);
  const page = vw * H, out = [];
  const els = [...document.body.querySelectorAll('*')].filter(e => {
    const cs = getComputedStyle(e); if (cs.display === 'none' || cs.visibility === 'hidden' || +cs.opacity === 0) return false;
    return !['SCRIPT','STYLE','BR','SPAN','A','B','I','EM','STRONG','svg','path'].includes(e.tagName);
  });
  const boxOf = e => { const r = e.getBoundingClientRect(); const y = r.top + scrollY;
    const x0 = Math.max(0, r.left), x1 = Math.min(vw, r.right), y0 = Math.max(0, y), y1 = Math.min(H, y + r.height);
    return (x1 > x0 && y1 > y0) ? {x: x0, y: y0, w: x1 - x0, h: y1 - y0} : null; };
  const big = new Map();
  for (const e of els) { const b = boxOf(e); if (!b) continue; const a = b.w * b.h;
    if (a >= page * 0.01 && a <= page * 0.92) big.set(e, b); }
  for (const [e, b] of big) {           // 去掉包裹层：有子元素几乎占满它
    const a = b.w * b.h; let wrapper = false;
    for (const c of e.children) { const cb = big.get(c); if (cb && cb.w * cb.h >= a * 0.85) { wrapper = true; break; } }
    if (!wrapper) out.push({x: b.x / vw, y: b.y / H, w: b.w / vw, h: b.h / H});
  }
  return out;
}"""


def iou(a, b):
    x0, y0 = max(a["x"], b["x"]), max(a["y"], b["y"])
    x1, y1 = min(a["x"] + a["w"], b["x"] + b["w"]), min(a["y"] + a["h"], b["y"] + b["h"])
    inter = max(0, x1 - x0) * max(0, y1 - y0)
    u = a["w"] * a["h"] + b["w"] * b["h"] - inter
    return inter / u if u else 0


def directed(A, B):
    if not A or not B:
        return 0.0
    tot = sum(a["w"] * a["h"] for a in A)
    return sum(a["w"] * a["h"] * max(iou(a, b) for b in B) for a in A) / tot


def sim(A, B):
    return round((directed(A, B) + directed(B, A)) / 2, 3)


def templates(html):
    out = []
    html = re.sub(r"<!--.*?-->", "", html, flags=re.S)
    for m in re.finditer(r"<template\s+([^>]*)>", html):
        attrs = dict(re.findall(r'([\w-]+)="([^"]*)"', m.group(1)))
        if "id" in attrs:
            out.append(attrs)
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--root", default=None)
    ap.add_argument("--phase", default=None)
    ap.add_argument("--width", type=int, default=1440)
    a = ap.parse_args()
    root = P.resolve_root(a.root, a.phase)
    vp = os.path.join(root, "work", "variants", "variants.html")
    if not os.path.exists(vp):
        sys.exit("[variants] 找不到 work/variants/variants.html")
    with open(vp, encoding="utf-8") as f:
        tpls = templates(f.read())
    try:
        scope = json.load(open(os.path.join(root, P.SCOPE), encoding="utf-8"))
    except Exception:
        scope = {}
    keep = scope.get("layout_freedom") == "keep"
    from playwright.sync_api import sync_playwright
    blocks = {}
    with sync_playwright() as p:
        b = p.chromium.launch()
        pg = b.new_page(viewport={"width": a.width, "height": 900})
        for t in tpls:
            pg.goto("about:blank")
            pg.goto("file://" + os.path.abspath(vp) + "#embed=" + t["id"], wait_until="load")
            pg.wait_for_function("() => { const f = document.querySelector('iframe'); return f && f.contentDocument && f.contentDocument.readyState === 'complete' && f.contentDocument.body && f.contentDocument.body.children.length }", timeout=10000)
            pg.wait_for_timeout(300)
            fr = next((f for f in pg.frames if f != pg.main_frame), None)
            blocks[t["id"]] = fr.evaluate(JS_BLOCKS, 2) if fr else []
        ref_id, ref_blocks = None, None
        refs = [t for t in tpls if t.get("data-role") == "reference"]
        wf = sorted(glob.glob(os.path.join(root, "work", "wireframe", "*.html")))
        if refs:
            ref_id = refs[0]["id"]; ref_blocks = blocks[ref_id]
        elif wf:
            pg.goto("file://" + os.path.abspath(wf[0]), wait_until="load"); pg.wait_for_timeout(300)
            ref_id = "wireframe:" + os.path.basename(wf[0]); ref_blocks = pg.evaluate(JS_BLOCKS, 2)
        b.close()
    variants = [t for t in tpls if t.get("data-role") != "reference"]
    keeps = [t["id"] for t in variants if t.get("data-intensity") == "克制"]
    mids = [t["id"] for t in variants if t.get("data-intensity") == "中等"]
    if ref_blocks is None and keeps:
        ref_id, ref_blocks = keeps[0], blocks[keeps[0]]
    rows, ok_all = [], True
    for t in variants:
        vid, lv = t["id"], t.get("data-intensity")
        r = {"id": vid, "intensity": lv, "blocks": len(blocks[vid]), "problems": []}
        r["vs_reference"] = sim(blocks[vid], ref_blocks) if ref_blocks is not None else None
        if not t.get("data-skeleton"):
            r["problems"].append("缺少 data-skeleton（一句话写清布局骨架）")
        if len(blocks[vid]) < 2:
            r["problems"].append("提取到的布局块太少（不足 2 个），方案可能没有完整实现首屏和区块")
        s = r["vs_reference"]
        if s is not None and vid != ref_id:
            if lv == "克制" and s < TH["keep_min"]:
                r["problems"].append(f"克制方案与参照布局相似度 {s} < {TH['keep_min']}：克制应保持布局，只调整样式和表现形式")
            if not keep:
                if lv == "中等":
                    if s > TH["mid_max"]:
                        r["problems"].append(f"中等方案与参照布局相似度 {s} > {TH['mid_max']}：中等应调整布局，而不只是换样式")
                    for k in keeps:
                        sk = sim(blocks[vid], blocks[k])
                        if sk > TH["mid_vs_keep"]:
                            r["problems"].append(f"中等方案与克制方案 {k} 的布局相似度 {sk} > {TH['mid_vs_keep']}：两档区分不开")
                if lv == "大胆":
                    if s > TH["bold_max"]:
                        r["problems"].append(f"大胆方案与参照布局相似度 {s} > {TH['bold_max']}：大胆应颠覆布局")
                    if not t.get("data-break"):
                        r["problems"].append("大胆方案缺少 data-break：写明颠覆了什么（导航范式 / 阅读顺序 / 页面隐喻 / 交互方式 / 信息组织）")
                    for m in mids:
                        sm = sim(blocks[vid], blocks[m])
                        if sm > TH["bold_vs_mid"]:
                            r["problems"].append(f"大胆方案与中等方案 {m} 的布局相似度 {sm} > {TH['bold_vs_mid']}：大胆没有拉开距离")
        r["ok"] = not r["problems"]
        ok_all &= r["ok"]
        rows.append(r)
        flag = "✓" if r["ok"] else "✗"
        print(f"  {flag} {vid} {lv or ''}  与参照相似度 {s}" + ("".join("\n      - " + x for x in r["problems"])))
    out = os.path.join(root, OUT)
    with open(out, "w", encoding="utf-8") as f:
        json.dump({"reference": ref_id, "layout_freedom": scope.get("layout_freedom"), "thresholds": TH,
                   "variants": rows, "ok": ok_all, "variants_mtime": os.path.getmtime(vp)}, f, ensure_ascii=False, indent=2)
    print(f"[variants] 参照：{ref_id}；{'全部通过' if ok_all else '有方案不符合力度要求'}；结果 {out}")
    sys.exit(0 if ok_all else 1)


if __name__ == "__main__":
    main()
