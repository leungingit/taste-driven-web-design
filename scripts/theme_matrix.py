#!/usr/bin/env python3
"""主题矩阵质检：按 work/theme/axes.json 的每个组合渲染原型，检查对比度并截图。

  theme_matrix.py [--widths 1440,375] [--root .taste-design]

输出：
  media/shots/qa/theme/<组合>-<宽度>.png     每个组合每个宽度一张截图
  work/qa/theme-matrix.json                   每个组合的对比度结果和截图路径（gate.py 闸门 8 会读取）

需要 playwright（pip install playwright && playwright install chromium）。
"""
import argparse, json, os, sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import paths as P  # noqa: E402
import theme as TH  # noqa: E402

JS_CONTRAST = """(pairs) => {
  const lum = c => { const m = c.match(/[\\d.]+/g); if (!m) return null;
    const [r,g,b] = m.slice(0,3).map(x => { x = +x/255; return x <= .03928 ? x/12.92 : Math.pow((x+.055)/1.055, 2.4) });
    return .2126*r + .7152*g + .0722*b };
  const res = v => { const el = document.createElement('span'); el.style.color = `var(${v})`; document.body.append(el);
    const c = getComputedStyle(el).color; el.remove(); return c };
  return pairs.map(([fg, bg, min]) => { const a = lum(res(fg)), b = lum(res(bg));
    if (a == null || b == null) return {fg, bg, ratio: null, ok: false};
    const r = (Math.max(a,b)+.05)/(Math.min(a,b)+.05); return {fg, bg, ratio: Math.round(r*100)/100, ok: r >= (min || 4.5)} });
}"""


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--root", default=None)
    ap.add_argument("--widths", default="1440,375")
    a = ap.parse_args()
    root = a.root or P.default_root()
    spec = TH.load(root)
    if not spec:
        sys.exit(f"[theme] 找不到 {TH.AXES}")
    proto = os.path.normpath(os.path.join(root, "work", "theme", spec.get("prototype", "")))
    if not os.path.isfile(proto):
        sys.exit(f"[theme] axes.json 的 prototype 指向的文件不存在：{proto}")
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        sys.exit("[theme] 需要 playwright：pip install playwright && playwright install chromium")
    widths = [int(w) for w in a.widths.split(",") if w.strip()]
    shots_dir = os.path.join(root, P.SHOTS, "qa", "theme")
    os.makedirs(shots_dir, exist_ok=True)
    rows = []
    url = "file://" + proto
    with sync_playwright() as p:
        b = p.chromium.launch()
        for c in TH.combos(spec):
            key = TH.combo_key(c)
            slug = "_".join(f"{k}-{v}" for k, v in c.items())
            row = {"key": key, "combo": c, "checks": [], "shots": {}}
            for w in widths:
                pg = b.new_page(viewport={"width": w, "height": 900 if w >= 1000 else 812}, device_scale_factor=2)
                pg.goto(url, wait_until="load")
                pg.evaluate("(c) => { for (const [k, v] of Object.entries(c)) document.documentElement.setAttribute('data-' + k, v) }", c)
                pg.wait_for_timeout(250)
                if not row["checks"]:
                    row["checks"] = pg.evaluate(JS_CONTRAST, spec.get("contrast_pairs") or [])
                rel = f"{P.SHOTS}/qa/theme/{slug}-{w}.png"
                pg.screenshot(path=os.path.join(root, rel))
                row["shots"][str(w)] = rel
                pg.close()
            row["contrast_ok"] = bool(row["checks"]) and all(x["ok"] for x in row["checks"])
            row["shot"] = row["shots"][str(widths[0])]
            rows.append(row)
            flag = "✓" if row["contrast_ok"] else "✗"
            print(f"  {flag} {key}  " + "  ".join(f"{x['fg']}/{x['bg']}={x['ratio']}" for x in row["checks"]))
        b.close()
    out = os.path.join(root, TH.MATRIX)
    os.makedirs(os.path.dirname(out), exist_ok=True)
    with open(out, "w", encoding="utf-8") as f:
        json.dump({"prototype": spec.get("prototype"), "widths": widths, "combos": rows}, f, ensure_ascii=False, indent=2)
    bad = sum(1 for r in rows if not r["contrast_ok"])
    print(f"[theme] {len(rows)} 个组合，{'全部达标' if not bad else f'{bad} 个不达标'}；结果 {out}")
    sys.exit(1 if bad else 0)


if __name__ == "__main__":
    main()
