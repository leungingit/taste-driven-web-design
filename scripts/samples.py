#!/usr/bin/env python3
"""从已有创意素材制作决策样例图。

  samples.py shot <网址或本地 html> --out 文件.png [--width 1440] [--height 900] [--full] [--selector CSS选择器] [--wait 毫秒]
      给参考网站、作品页或本项目页面截图（需要 playwright：pip install playwright && playwright install chromium）
  samples.py crop <图片> --box x,y,w,h --out 文件.png [--scale 0.5]
      从素材图里裁出需要比较的局部（需要 Pillow）
  samples.py frames <视频> --out 目录 [--every 1.5]
      从动效参考视频抽关键帧（需要 ffmpeg）

产出的样例放到 .taste-design/media/samples/<ID>/（question.json 里直接写文件名即可），并在 question.json 的 media 里写明 origin、ref 或 credit。
"""
import argparse, os, pathlib, shutil, subprocess, sys


def cmd_shot(a):
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        sys.exit("[samples] 需要 playwright：pip install playwright && playwright install chromium")
    target = a.target
    if not target.startswith(("http://", "https://", "file://")):
        target = pathlib.Path(target).resolve().as_uri()
    os.makedirs(os.path.dirname(os.path.abspath(a.out)), exist_ok=True)
    with sync_playwright() as p:
        b = p.chromium.launch()
        pg = b.new_page(viewport={"width": a.width, "height": a.height}, device_scale_factor=a.dpr)
        pg.goto(target, wait_until="networkidle", timeout=60000)
        pg.wait_for_timeout(a.wait)
        if a.selector:
            pg.locator(a.selector).first.screenshot(path=a.out)
        else:
            pg.screenshot(path=a.out, full_page=a.full)
        b.close()
    print(f"[samples] 已截图 {a.out}")


def cmd_crop(a):
    try:
        from PIL import Image
    except ImportError:
        sys.exit("[samples] 需要 Pillow：pip install pillow")
    x, y, w, h = [int(v) for v in a.box.split(",")]
    im = Image.open(a.image).crop((x, y, x + w, y + h))
    if a.scale != 1:
        im = im.resize((max(1, int(w * a.scale)), max(1, int(h * a.scale))), Image.LANCZOS)
    os.makedirs(os.path.dirname(os.path.abspath(a.out)), exist_ok=True)
    im.save(a.out)
    print(f"[samples] 已裁切 {a.out}（{im.size[0]}×{im.size[1]}）")


def cmd_frames(a):
    if not shutil.which("ffmpeg"):
        sys.exit("[samples] 需要 ffmpeg")
    os.makedirs(a.out, exist_ok=True)
    subprocess.run(["ffmpeg", "-loglevel", "error", "-i", a.video, "-vf", f"fps=1/{a.every}",
                    os.path.join(a.out, "frame_%03d.png")], check=True)
    print(f"[samples] 已抽帧到 {a.out}")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sp = ap.add_subparsers(dest="cmd", required=True)
    p = sp.add_parser("shot"); p.add_argument("target"); p.add_argument("--out", required=True)
    p.add_argument("--width", type=int, default=1440); p.add_argument("--height", type=int, default=900)
    p.add_argument("--dpr", type=float, default=2); p.add_argument("--full", action="store_true")
    p.add_argument("--selector"); p.add_argument("--wait", type=int, default=800); p.set_defaults(f=cmd_shot)
    p = sp.add_parser("crop"); p.add_argument("image"); p.add_argument("--box", required=True)
    p.add_argument("--out", required=True); p.add_argument("--scale", type=float, default=1); p.set_defaults(f=cmd_crop)
    p = sp.add_parser("frames"); p.add_argument("video"); p.add_argument("--out", required=True)
    p.add_argument("--every", type=float, default=1.5); p.set_defaults(f=cmd_frames)
    a = ap.parse_args()
    a.f(a)


if __name__ == "__main__":
    main()
