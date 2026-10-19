#!/usr/bin/env python3
"""本地网页决策服务。只依赖标准库。

用法（在项目根目录执行）：
  decide_server.py serve [--root design] [--port 8765] [--host 127.0.0.1] [--max-open 3]
  decide_server.py wait [--chunk 45] [--idle 0]       # 分段等待；到时续接，不结束设计流程
  decide_server.py ack ID --ts 原版本时间戳           # 落实答案后精确确认
  decide_server.py resume                             # 用户回来后解除「我先离开」
  decide_server.py export                              # 生成静态决策页 .taste-design/cache/export/index.html（无后端）

决策定义见 references/decisions.md：每个决策是 .taste-design/record/decisions/<ID>/question.json，
用户在网页上作答后服务写入同目录 answer.json，追加 record/decisions.md，并生成 record/summary/<ID>.md 摘要卡。

网页只显示「当前阶段」且「前置决策已答」的决策，同时最多显示 --max-open 个，
其余排队，保证决策逐个递进，而不是一次性全部铺开。
"""
import argparse, datetime, glob, json, mimetypes, os, sys, time, urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from rules import validate_question  # noqa: E402
from stages import STAGES  # noqa: E402
import paths as P  # noqa: E402
import summary as SUM  # noqa: E402
import waitlib  # noqa: E402


def now():
    return datetime.datetime.now().astimezone().isoformat(timespec="microseconds")


def load_json(p):
    with open(p, encoding="utf-8") as f:
        return json.load(f)


def image_size(path):
    """读取 PNG / GIF / JPEG / WebP 的像素尺寸（只读文件头，不依赖第三方库）。"""
    import struct
    try:
        with open(path, "rb") as f:
            head = f.read(32)
            if head[:8] == b"\x89PNG\r\n\x1a\n":
                return struct.unpack(">II", head[16:24])
            if head[:6] in (b"GIF87a", b"GIF89a"):
                return struct.unpack("<HH", head[6:10])
            if head[:4] == b"RIFF" and head[8:12] == b"WEBP":
                kind = head[12:16]
                if kind == b"VP8X":
                    return (int.from_bytes(head[24:27], "little") + 1, int.from_bytes(head[27:30], "little") + 1)
                if kind == b"VP8 ":
                    f.seek(26); w, h = struct.unpack("<HH", f.read(4)); return (w & 0x3FFF, h & 0x3FFF)
                if kind == b"VP8L":
                    f.seek(21); b = f.read(4)
                    return (1 + (((b[1] & 0x3F) << 8) | b[0]), 1 + (((b[3] & 0xF) << 10) | (b[2] << 2) | ((b[1] & 0xC0) >> 6)))
            if head[:2] == b"\xff\xd8":
                f.seek(2)
                while True:
                    m = f.read(2)
                    if len(m) < 2 or m[0] != 0xFF:
                        return None
                    if m[1] in (0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7, 0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF):
                        f.read(3); h, w = struct.unpack(">HH", f.read(4)); return (w, h)
                    ln = struct.unpack(">H", f.read(2))[0]
                    f.seek(ln - 2, 1)
    except Exception:
        return None
    return None


def local_rel(did, src):
    r = P.resolve_src(did, src)
    return r[0] if r else None


def media_url(did, src, static=False):
    """question.json 里的 src → 网页可用的 URL。
    http(s):// 原样；@/xxx 相对 .taste-design；其余相对 media/samples/<决策ID>/。"""
    r = P.resolve_src(did, src)
    if r is None:
        return src
    rel, frag = r
    # 静态导出页在 cache/export/ 下，回到 .taste-design 需要 ../../
    return (("../../" + rel) if static else ("/files/" + urllib.parse.quote(rel))) + frag


class Store:
    def __init__(self, root, max_open):
        self.root = os.path.abspath(root)
        self.max_open = max_open

    def state(self):
        return load_json(os.path.join(self.root, P.STATE))

    def all(self):
        out = []
        for q in sorted(glob.glob(os.path.join(self.root, P.DECISIONS, "*", "question.json"))):
            d = os.path.dirname(q)
            try:
                qj = load_json(q)
            except Exception as e:
                out.append({"id": os.path.basename(d), "_error": f"JSON 解析失败：{e}"})
                continue
            qj.setdefault("id", os.path.basename(d))
            ap = os.path.join(d, "answer.json")
            qj["_answer"] = load_json(ap) if os.path.exists(ap) else None
            qj["_dir"] = os.path.relpath(d, self.root)
            out.append(qj)
        return out

    def _resolve(self, q, static):
        base = q["id"]
        for m in [m for o in q.get("options") or [] for m in o.get("media") or []] + list(q.get("media") or []):
            m["url"] = media_url(base, m["src"], static)
            rel = local_rel(base, m["src"])
            if m.get("type", "image") == "image" and rel:
                wh = image_size(os.path.join(self.root, rel))
                if wh:
                    m["w"], m["h"] = wh
        if q.get("playground"):
            q["playground_url"] = media_url(base, q["playground"], static)
        if q["type"] == "gate" and not q.get("options"):
            q["options"] = [{"id": "approve", "label": "通过，进入下一阶段"},
                            {"id": "revise", "label": "不通过，需要修改"}]

    def view(self, static=False, include_flow=True):
        st = self.state()
        cur = st["stage"]
        here = {cur} | {int(k) for k, v in (st.get("merged") or {}).items() if v == cur}
        allq = self.all()
        answered_ids = {q["id"] for q in allq if q.get("_answer")}
        open_, queued, answered, broken = [], [], [], []
        for q in allq:
            if "_error" in q:
                broken.append(q); continue
            errs = validate_question(q)
            if errs:
                broken.append({"id": q["id"], "_error": "；".join(errs)}); continue
            if q.get("_answer"):
                if q.get("stage") in here:
                    answered.append({"id": q["id"], "title": q.get("title", ""), "answer": q["_answer"],
                                     "delivered": waitlib.delivered(self.root).get(q["id"]) == q["_answer"].get("ts"),
                                     "applied": waitlib.acked(self.root).get(q["id"]) == q["_answer"].get("ts")})
                continue
            if q.get("stage") not in here:
                continue  # 非当前阶段的决策一律不显示
            deps = q.get("depends_on") or []
            if any(dp not in answered_ids for dp in deps):
                queued.append({"id": q["id"], "title": q.get("title", ""), "waiting_for": [d for d in deps if d not in answered_ids]})
                continue
            open_.append(q)
        # 同时最多开放 max_open 个，其余排队
        for q in open_[self.max_open:]:
            queued.append({"id": q["id"], "title": q.get("title", ""), "waiting_for": ["前面的决策"]})
        open_ = open_[: self.max_open]
        for q in open_:
            self._resolve(q, static)
        # 回顾：所有阶段已作答的决策（按阶段、作答时间排序），含被回退作废的旧答案
        history = []
        for q in allq:
            if "_error" in q or not q.get("_answer"):
                continue
            self._resolve(q, static)
            d = os.path.join(self.root, q["_dir"])
            q["_superseded"] = [load_json(f) for f in sorted(glob.glob(os.path.join(d, "answer.superseded-*.json")))]
            history.append(q)
        history.sort(key=lambda x: (x.get("stage", 0), x["_answer"].get("ts", "")))
        sc = load_json(os.path.join(self.root, P.SCOPE)) if os.path.exists(os.path.join(self.root, P.SCOPE)) else {}
        result = {"stage": cur, "stage_name": STAGES.get(cur, {}).get("name", ""), "mode": st.get("mode"),
                "customizable": bool((sc or {}).get("user_customizable")),
                "customization_page": (sc or {}).get("customization_page") or "设置",
                "open": open_, "queued": queued, "answered": answered, "broken": broken, "static": static,
                "history": history, "stage_names": {k: v["name"] for k, v in STAGES.items()},
                "passed": st.get("passed", []), "sequence": st.get("sequence", []),
                "agent_waiting": (not static) and waitlib.agent_waiting(self.root),
                "paused": (not static) and waitlib.paused(self.root)}
        if include_flow:
            from gate import workflow_next
            result["flow"] = workflow_next(self.root, snapshot=result)
        return result

    def answer(self, did, body):
        v = self.view()
        q = next((x for x in v["open"] if x["id"] == did), None)
        if not q:
            return 409, "该决策当前不可作答（不在当前阶段、前置未答或已作答）"
        choice = body.get("choice") or []
        ids = {o["id"] for o in q.get("options") or []}
        setting = body.get("setting")
        if setting:
            if not q.get("allow_setting"):
                return 400, "这个决策不能做成设置项"
            if not v.get("customizable"):
                return 400, "阶段 0 定为外观不开放给最终用户；要做成设置项需先回到阶段 0 修改范围"
            vals = list(dict.fromkeys(setting.get("values") or []))
            if not 2 <= len(vals) <= 4 or any(x not in ids for x in vals):
                return 400, "做成设置项时请保留 2–4 个选项"
            if setting.get("default") not in vals:
                return 400, "请指定默认值"
            setting = {"axis": q.get("setting_axis"), "values": vals, "default": setting["default"]}
            choice = [setting["default"]]
        t = q["type"]
        other = (body.get("other") or "").strip()
        note = (body.get("note") or "").strip()
        value = body.get("value")
        if t in ("single", "scale", "gate"):
            if len(choice) != 1 and not (other and q.get("allow_other", True) and t != "gate"):
                return 400, "需要选择 1 项"
        if t == "multi" and not choice and not other:
            return 400, "至少选择 1 项"
        if any(c not in ids for c in choice):
            return 400, "选项不存在"
        if t == "gate" and choice == ["revise"] and not note:
            return 400, "选择不通过时请写明要改什么"
        if t == "tune" and not (value or "").strip():
            return 400, "请提交调好的数值"
        waitlib.set_paused(self.root, False)
        ans = {"id": did, "choice": choice, "other": other, "note": note, "value": value, "setting": setting,
               "answered_by": "user", "via": "web", "ts": now()}
        d = os.path.join(self.root, q["_dir"])
        with open(os.path.join(d, "answer.json"), "w", encoding="utf-8") as f:
            json.dump(ans, f, ensure_ascii=False, indent=2)
        with open(os.path.join(self.root, P.LOG), "a", encoding="utf-8") as f:
            f.write(f"- {ans['ts']} | 阶段{q['stage']} | {did} {q.get('title','')} | 选择 {','.join(choice) or '-'}"
                    f"{' | 其他 ' + other if other else ''}{' | 备注 ' + note if note else ''}"
                    f"{' | 数值 已提交' if value else ''}"
                    f"{' | 做成设置项 ' + '/'.join(setting['values']) + '，默认 ' + setting['default'] if setting else ''} | user(web)\n")
        try:
            SUM.write(self.root, did)
        except Exception as e:  # 摘要卡失败不影响作答
            print(f"[decide] 摘要卡生成失败：{e}", file=sys.stderr)
        return 200, "ok"


PAGE = r"""<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>设计决策</title>
<style>
:root{--bg:#f6f3ee;--card:#fffdf9;--ink:#1f1d1a;--mute:#6f6a62;--line:#e2dcd2;--acc:#c2410c;--acc-weak:#fde7da;--ok:#2f6f3e}
@media (prefers-color-scheme:dark){:root{--bg:#171614;--card:#201f1c;--ink:#efe9df;--mute:#a39b8e;--line:#36332e;--acc:#fb8a4a;--acc-weak:#3a2416;--ok:#7cc48c}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);font:15px/1.6 -apple-system,"PingFang SC","Noto Sans SC","Microsoft YaHei",sans-serif}
header{position:sticky;top:0;z-index:5;background:var(--bg);border-bottom:1px solid var(--line);padding:12px 16px;display:flex;gap:12px;align-items:baseline;flex-wrap:wrap}
header b{font-size:17px}
#agent.on{color:var(--ok);border-color:var(--ok)}#agent.off{color:var(--acc);border-color:var(--acc)}
#pause{padding:6px 12px;font-size:13px}[hidden]{display:none!important}.pill{font-size:12px;border:1px solid var(--line);border-radius:99px;padding:2px 10px;color:var(--mute)}
main{max-width:1180px;margin:0 auto;padding:16px}
.dec{background:var(--card);border:1px solid var(--line);border-radius:14px;padding:18px;margin-bottom:22px}
.dec h2{margin:0 0 4px;font-size:19px}.meta{color:var(--mute);font-size:13px}.ctx{margin:8px 0 14px}
.opts{display:grid;gap:14px;grid-template-columns:repeat(auto-fill,minmax(260px,1fr))}
.opts.scale{grid-template-columns:repeat(auto-fit,minmax(150px,1fr))}
.opt{border:2px solid var(--line);border-radius:12px;padding:10px;cursor:pointer;position:relative;background:var(--card);transition:border-color .12s}
.opt:hover{border-color:var(--mute)}.opt.sel{border-color:var(--acc);background:var(--acc-weak)}
.opt:focus-visible{outline:3px solid var(--acc);outline-offset:2px}
.oid{font-weight:700;font-size:13px;color:var(--acc)}.olabel{font-weight:600}.odesc{font-size:13px;color:var(--mute);margin-top:4px}
.fit{font-size:12px;margin-top:6px}.rec{display:inline-block;vertical-align:2px;background:var(--acc);color:#fff;font-size:11px;font-weight:600;border-radius:6px;padding:0 6px;margin-left:4px}
.media{display:grid;gap:6px;grid-template-columns:repeat(auto-fit,minmax(90px,1fr));margin-bottom:8px}
.media img,.media video{width:100%;aspect-ratio:4/3;object-fit:cover;border-radius:8px;background:#0001;display:block}
.media.one{grid-template-columns:1fr}
.mw{position:relative}.mw [data-view]{cursor:zoom-in}
.ex{position:absolute;top:6px;right:6px;z-index:3;width:30px;height:30px;padding:0;border-radius:8px;background:#000b;color:#fff;font-size:16px;line-height:30px;font-weight:400;box-shadow:0 1px 4px #0005}
.ex:hover{background:#000}.ex:focus-visible{outline:2px solid #fff;outline-offset:1px}
.lowres{position:absolute;left:6px;top:6px;z-index:3;font-size:11px;background:#b42318;color:#fff;border-radius:6px;padding:1px 6px}
.tick{display:inline-block;width:16px;height:16px;border:2px solid var(--mute);border-radius:50%;vertical-align:-3px;margin-right:6px}
.opt.multi .tick{border-radius:4px}.opt.sel .tick{border-color:var(--acc);background:var(--acc);box-shadow:inset 0 0 0 2px var(--card)}
.howto{font-size:12px;color:var(--mute);margin:-6px 0 10px}
.tabs{display:inline-flex;border:1px solid var(--line);border-radius:9px;overflow:hidden}
.tabs button{background:transparent;color:var(--ink);border-radius:0;padding:6px 14px;font-weight:500;font-size:14px}
.tabs button[aria-pressed=true]{background:var(--ink);color:var(--bg)}
.hbar{display:flex;gap:8px;flex-wrap:wrap;align-items:center;margin-bottom:14px}
.chip{background:transparent;color:var(--ink);border:1px solid var(--line);border-radius:99px;padding:4px 12px;font-size:13px;font-weight:500}
.chip[aria-pressed=true]{background:var(--acc);border-color:var(--acc);color:#fff}
.hist .opt{cursor:default}.hist .opt:not(.sel){opacity:.72}.hist .opt:hover{border-color:var(--line)}.hist .opt.sel:hover{border-color:var(--acc)}
.hstage{font-size:15px;margin:22px 0 10px;color:var(--mute);font-weight:600;border-bottom:1px solid var(--line);padding-bottom:4px}
.verdict{margin-top:12px;padding:10px 12px;border-radius:10px;background:var(--bg);font-size:14px}
.verdict b{color:var(--acc)}.old{font-size:12px;color:var(--mute);margin-top:6px}
.hsearch{flex:1 1 200px;max-width:320px}
.setrow{margin-top:12px;padding:10px 12px;border:1px dashed var(--line);border-radius:10px;font-size:14px;display:flex;gap:10px;align-items:flex-start;flex-wrap:wrap}
.setrow.on{border-color:var(--acc);background:var(--acc-weak)}.setrow label{cursor:pointer;display:flex;gap:8px;align-items:center;font-weight:600}
.setrow.dis{opacity:.6}.setrow.dis label{cursor:not-allowed}.setrow .meta{flex-basis:100%}
.setmode .opt .tick{border-radius:4px}
.defbtn{display:none;margin-left:8px;font-size:12px;padding:2px 8px;border-radius:6px;background:transparent;color:var(--acc);border:1px solid var(--acc);font-weight:600}
.setmode .opt.sel .defbtn{display:inline-block}.opt.def .defbtn{background:var(--acc);color:#fff}
.frame{width:100%;aspect-ratio:4/3;border:0;border-radius:8px;background:#fff}
.vp{position:relative;width:100%;overflow:hidden;border-radius:8px;background:#fff}.vp iframe{position:absolute;left:0;top:0;border:0;transform-origin:0 0;pointer-events:none}
.wide{grid-column:1/-1}.frame.big{aspect-ratio:auto;height:78vh;border:1px solid var(--line)}
.credit{font-size:11px;color:var(--mute);word-break:break-all}
.warn{font-size:12px;color:var(--acc)}
.row{display:flex;gap:10px;flex-wrap:wrap;margin-top:14px;align-items:flex-start}
textarea,input[type=text]{width:100%;font:inherit;color:inherit;background:var(--bg);border:1px solid var(--line);border-radius:8px;padding:8px}
.col{flex:1 1 280px}
button{font:inherit;border:0;border-radius:10px;padding:10px 18px;background:var(--acc);color:#fff;cursor:pointer;font-weight:600}
button:disabled{opacity:.4;cursor:not-allowed}button.ghost{background:transparent;color:var(--ink);border:1px solid var(--line)}
.side{color:var(--mute);font-size:13px}.side li{margin:2px 0}
.tune{display:grid;gap:12px;grid-template-columns:2fr 1fr}.tune iframe{width:100%;height:560px;border:1px solid var(--line);border-radius:10px;background:#fff}
@media (max-width:760px){.tune{grid-template-columns:1fr}.tune iframe{height:460px}}
#vw{position:fixed;inset:0;z-index:50;background:#0d0c0b;color:#eee;display:grid;grid-template-rows:auto 1fr auto auto}
#vw button,#vw a.vbtn{font:13px/1 -apple-system,"PingFang SC","Noto Sans SC",sans-serif;background:#ffffff14;color:#eee;border:1px solid #ffffff22;border-radius:8px;padding:7px 10px;cursor:pointer;text-decoration:none;font-weight:500}
#vw button:hover,#vw a.vbtn:hover{background:#ffffff26}#vw button[aria-pressed=true]{background:#eee;color:#111}
#vw button:focus-visible{outline:2px solid var(--acc);outline-offset:1px}
.vbar{display:flex;gap:8px;align-items:center;flex-wrap:wrap;padding:8px 12px;border-bottom:1px solid #ffffff1a}
.vtitle{font-size:14px;min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;max-width:46vw}.vmute{color:#aaa}
.vsp{flex:1}.vseg{display:inline-flex;gap:2px}.vseg button{border-radius:6px!important}
#vzl{min-width:58px}
.vstage{position:relative;display:grid;gap:8px;padding:8px;min-height:0}.vstage.two{grid-template-columns:1fr 1fr}
@media (max-width:760px){.vstage.two{grid-template-columns:1fr;grid-template-rows:1fr 1fr}.vtitle{max-width:calc(100% - 50px)}.vsp{display:none}
  .vbar{position:relative;padding-right:56px}#vclose{position:absolute;right:10px;top:8px}#vopen,#vfs{display:none}}
.pane{position:relative;min-height:0;display:grid;grid-template-rows:auto 1fr;border-radius:8px;outline:2px solid transparent}
.vstage.two .pane.act{outline-color:var(--acc)}
.pl{display:flex;gap:6px;align-items:center;font-size:12px;color:#ccc;padding:0 2px 4px}.pl select{font:inherit;background:#222;color:#eee;border:1px solid #444;border-radius:6px;padding:2px 4px;max-width:100%}
.pl .ok{color:#7cc48c}
.pc{position:relative;overflow:hidden;min-height:0;border-radius:6px;background:repeating-conic-gradient(#1c1b19 0 25%,#232220 0 50%) 0 0/24px 24px;touch-action:none}
.pc.img{cursor:grab}.pc.img.drag{cursor:grabbing}
.pc img{position:absolute;left:0;top:0;transform-origin:0 0;max-width:none;user-select:none;-webkit-user-drag:none;image-rendering:auto}
.pc.pix img{image-rendering:pixelated}
.pc iframe{position:absolute;left:0;top:0;border:0;background:#fff;transform-origin:0 0}
.pc video{position:absolute;inset:0;width:100%;height:100%;object-fit:contain;background:#000}
.pc .lk{position:absolute;inset:0;display:grid;place-items:center}.pc .lk a{color:#fff;font-size:16px}
.varrow{position:absolute;top:45%;transform:translateY(-50%);z-index:4;width:44px;height:64px;font-size:30px!important;padding:0!important;background:#0008!important}
.varrow.l{left:6px}.varrow.r{right:6px}.vstage.two~.varrow{display:none}
.vfoot{display:flex;gap:12px;align-items:center;padding:8px 12px;border-top:1px solid #ffffff1a;flex-wrap:wrap}
.vcap{flex:1 1 320px;font-size:13px;color:#ccc;min-width:0}.vcap b{color:#fff}.vcap .w{color:#ffb38a}.vcap .bad{color:#ff8a80}
#vsel{background:var(--acc)!important;color:#fff!important;border-color:transparent!important;font-weight:600!important;padding:9px 16px!important}
#vsel.on{background:#2f6f3e!important}#vsel:disabled{opacity:1;cursor:default}#vsel:disabled:not(.on){background:#ffffff1a!important;color:#ccc!important}
.vthumbs{display:flex;gap:6px;overflow-x:auto;padding:6px 12px 10px}
.vt{flex:0 0 auto;width:84px;height:60px;padding:0!important;position:relative;overflow:hidden;border-radius:6px!important}
.vt img{width:100%;height:100%;object-fit:cover;display:block}.vt span{position:absolute;left:3px;bottom:2px;font-size:11px;background:#000a;border-radius:4px;padding:0 4px}
.vt .ty{position:absolute;inset:0;display:grid;place-items:center;font-size:12px;color:#ccc}
.vt.a1{outline:2px solid var(--acc)}.vt.a2{outline:2px dashed #8ab4ff}
.vt i{position:absolute;right:3px;top:2px;font-style:normal;font-size:11px;color:#7cc48c}
.vzoomlbl{font-variant-numeric:tabular-nums}
.empty{text-align:center;color:var(--mute);padding:60px 0}
.toast{position:fixed;bottom:18px;left:50%;transform:translateX(-50%);background:var(--ink);color:var(--bg);padding:8px 16px;border-radius:8px;display:none}
</style></head><body>
<header><b>设计决策</b><span class="tabs" id="tabs"><button data-tab="now">当前决策</button><button data-tab="review">回顾</button></span><span class="pill" id="stage"></span><span class="pill" id="mode"></span><span class="pill" id="agent"></span><span class="side" id="hint"></span><span style="flex:1"></span><button class="ghost" id="pause" hidden></button></header>
<main id="app"></main>
<div class="toast" id="toast"></div>
<div id="vw" hidden role="dialog" aria-modal="true" aria-label="放大查看">
  <div class="vbar">
    <div class="vtitle"><b id="vq"></b> <span id="vn" class="vmute"></span></div>
    <span class="vsp"></span>
    <div class="vseg" id="vwidth" hidden title="页面宽度"><button data-w="375">375</button><button data-w="768">768</button><button data-w="1440">1440</button></div>
    <div class="vseg" id="vzoom"><button data-z="out" title="缩小（−）">−</button><button data-z="fit" id="vzl" class="vzoomlbl" title="适应窗口（0）">适应</button><button data-z="in" title="放大（+）">+</button><button data-z="one" title="原始像素 1:1（1）">1:1</button></div>
    <button id="vcmp" title="并排对比，缩放和平移同步（C）">并排对比</button>
    <a class="vbtn" id="vopen" target="_blank" rel="noopener" title="在新标签页打开原文件">↗</a>
    <button id="vfs" title="全屏（F）">⛶</button>
    <button id="vclose" title="关闭（Esc）">✕</button>
  </div>
  <div class="vstage" id="vstage"></div>
  <button class="varrow l" id="vprev" title="上一张（←）" aria-label="上一张">‹</button><button class="varrow r" id="vnext" title="下一张（→）" aria-label="下一张">›</button>
  <div class="vfoot"><div class="vcap" id="vcap"></div><button id="vsel" hidden></button></div>
  <div class="vthumbs" id="vthumbs"></div>
</div>
<script>
const STATIC = window.__STATIC__ || null;
const picks = {}; // id -> Set
const SETM = {};   // id -> {on:bool, def:optionId}
const $ = (s, el=document) => el.querySelector(s);
const esc = s => String(s ?? "").replace(/[&<>"]/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;"}[c]));
function toast(t){const e=$("#toast");e.textContent=t;e.style.display="block";setTimeout(()=>e.style.display="none",2200)}
let MEDIA={}, ORDER={};
const ORI={inbox:"创意素材",search:"检索参考",screenshot:"参考截图",generated:"生成对照",rendered:"代码渲染"};
const LOWRES=1000;
function mediaHTML(list,qid,oid){
  if(!list||!list.length) return "";
  const one = list.length===1 ? " one" : "";
  return `<div class="media${one}">` + list.map((m,i)=>{
    const key=`${qid}|${oid||"_"}|${i}`; MEDIA[key]={key,qid,oid,m}; (ORDER[qid]=ORDER[qid]||[]).push(key);
    const cap = `<div class="credit">${esc(ORI[m.origin]||"")}${m.ref?" · "+esc(m.ref):""}${m.credit?" · "+esc(m.credit):""}${m.w?` · ${m.w}×${m.h}`:""}</div>`;
    const note = m.caveat ? `<div class="warn">${esc(m.caveat)}</div>` : "";
    const ex = m.type==="link" ? "" : `<button class="ex" type="button" data-view="${esc(key)}" title="放大查看（全屏、缩放、对比）" aria-label="放大查看">⤢</button>`;
    const low = (m.w && Math.max(m.w,m.h)<LOWRES) ? `<span class="lowres" title="原图太小，放大后会模糊">低分辨率</span>` : "";
    let body;
    if(m.type==="html" && m.viewport && m.display!=="wide"){const vw=m.viewport, vh=m.viewport_height||Math.round(vw*0.625);
      body=`<div class="vp" data-view="${esc(key)}" style="aspect-ratio:${vw}/${vh}"><iframe sandbox="${m.trusted||m.attrs?"allow-scripts allow-same-origin":"allow-scripts"}"${m.attrs?` data-attrs='${esc(JSON.stringify(m.attrs))}'`:""} src="${esc(m.url)}" style="width:${vw}px;height:${vh}px" data-vw="${vw}" tabindex="-1"></iframe></div>`;}
    else if(m.type==="html") body=`<iframe class="frame${m.display==="wide"?" big":""}" sandbox="${m.trusted||m.attrs?"allow-scripts allow-same-origin":"allow-scripts"}"${m.attrs?` data-attrs='${esc(JSON.stringify(m.attrs))}'`:""} loading="lazy" src="${esc(m.url)}"></iframe>`;
    else if(m.type==="video") body=`<video src="${esc(m.url)}" controls loop muted playsinline></video>`;
    else if(m.type==="link") body=`<a href="${esc(m.url)}" target="_blank" rel="noopener">${esc(m.label||m.url)}</a>`;
    else body=`<img loading="lazy" data-view="${esc(key)}" src="${esc(m.url)}" alt="${esc(m.alt||"")}">`;
    return `<div class="mw${m.display==="wide"?" wide":""}">${body}${ex}${low}${note}${cap}</div>`;
  }).join("") + `</div>`;
}
function optHTML(q,o){
  const fit = (o.good_for||o.bad_for) ? `<div class="fit">${o.good_for?"适合："+esc(o.good_for):""}${o.good_for&&o.bad_for?"<br>":""}${o.bad_for?"不适合："+esc(o.bad_for):""}</div>` : "";
  return `<div class="opt${q.type==="multi"?" multi":""}" tabindex="0" role="button" data-q="${esc(q.id)}" data-o="${esc(o.id)}">
    ${mediaHTML(o.media,q.id,o.id)}
    <div><span class="tick" aria-hidden="true"></span>${q.type==="gate"?"":`<span class="oid">${esc(o.id)}</span> `}<span class="olabel">${esc(o.label)}</span>${o.recommended?' <span class="rec">推荐</span>':""}${q.allow_setting?`<button type="button" class="defbtn" data-def="${esc(q.id)}|${esc(o.id)}">设为默认</button>`:""}</div>
    ${o.desc?`<div class="odesc">${esc(o.desc)}</div>`:""}${fit}</div>`;
}
function decHTML(q){
  const typeName={single:"单选",multi:"多选",scale:"刻度（选一档）",tune:"拖动调节",gate:"阶段验收"}[q.type];
  let body="";
  if(q.type==="tune"){
    body=`<div class="tune"><iframe src="${esc(q.playground_url)}"></iframe>
      <div><div class="meta">在左侧调好后，数值会自动出现在这里（也可直接粘贴 CSS 变量）。</div>
      <textarea rows="16" data-value="${esc(q.id)}" placeholder="--color-bg: …"></textarea></div></div>`;
  } else {
    const hasMedia=(q.media&&q.media.length)||(q.options||[]).some(o=>o.media&&o.media.length);
    body = (hasMedia?`<div class="howto">点图片或 ⤢ 全屏查看细节（可缩放、并排对比）；点卡片下方文字选择。</div>`:"") + (q.media?mediaHTML(q.media,q.id,null):"") + `<div class="opts${q.type==="scale"?" scale":""}">${(q.options||[]).map(o=>optHTML(q,o)).join("")}</div>`;
  }
  const other = (q.type!=="gate"&&q.type!=="tune"&&q.allow_other!==false) ?
    `<div class="col"><input type="text" data-other="${esc(q.id)}" placeholder="都不对？写下你想要的，或把参考图放进 .taste-design/media/inbox/images/ 后写文件名"></div>`:"";
  const setrow = q.allow_setting ? (DATA.customizable
    ? `<div class="setrow" data-setrow="${esc(q.id)}"><label><input type="checkbox" data-setmode="${esc(q.id)}"> 都要，做成设置项</label>
       <div class="meta">保留 2–4 个选项，最终用户可在「${esc(DATA.customization_page)}」里切换；再点选中卡片上的「设为默认」指定默认值。只适合不同用户会合理地偏好不同选项的情况（如明暗、密度）；如果只是难以取舍，请直接选一个。</div></div>`
    : `<div class="setrow dis"><label><input type="checkbox" disabled> 都要，做成设置项</label>
       <div class="meta">阶段 0 定为「外观不开放给最终用户」，不能做成设置项。需要的话在备注里写明，智能体会先和你确认是否回到阶段 0 修改范围。</div></div>`) : "";
  const btn = STATIC ? `<button class="ghost" data-copy="${esc(q.id)}">复制回复文本</button>` : `<button data-submit="${esc(q.id)}" disabled>提交</button>`;
  return `<section class="dec" id="d-${esc(q.id)}">
    <div class="meta">${esc(q.id)} · ${typeName}${q.affects?" · 影响："+esc(q.affects):""}</div>
    <h2>${esc(q.title)}</h2>${q.context?`<div class="ctx">${esc(q.context)}</div>`:""}
    ${body}${setrow}
    <div class="row">${other}<div class="col"><textarea rows="2" data-note="${esc(q.id)}" placeholder="${q.type==="gate"?"不通过时必填：要改什么":"补充说明（可选），例如：B 的笔触 + D 的颜色"}"></textarea></div>${btn}</div>
  </section>`;
}
function canSubmit(q){
  const sm=SETM[q.id]; if(sm&&sm.on){const s=picks[q.id]||new Set(); return s.size>=2&&s.size<=4&&s.has(sm.def);}
  const s=picks[q.id]||new Set(), other=($(`[data-other="${q.id}"]`)||{}).value||"", note=($(`[data-note="${q.id}"]`)||{}).value||"";
  if(q.type==="tune") return !!(($(`[data-value="${q.id}"]`)||{}).value||"").trim();
  if(q.type==="gate") return s.size===1 && (!s.has("revise")||note.trim());
  if(q.type==="multi") return s.size>0||other.trim();
  return s.size===1||(s.size===0&&other.trim());
}
let DATA=null;
function header(v){
const ag=$("#agent"), pb=$("#pause");
  if(STATIC){ag.hidden=true;pb.hidden=true}
  else if(v.paused){ag.className="pill off";ag.textContent="已暂停：保留当前进度";pb.hidden=false;pb.textContent="取消暂停";pb.dataset.act="resume"}
  else if(v.flow&&v.flow.status==="completed"){ag.className="pill on";ag.textContent="设计流程已完成";pb.hidden=true}
  else if(v.flow&&v.flow.status==="blocked"){ag.className="pill off";ag.textContent="流程受阻："+v.flow.blocked.reason;pb.hidden=true}
  else if(v.agent_waiting){ag.className="pill on";ag.textContent="● 智能体正在等你，提交后立即继续";pb.hidden=false;pb.textContent="我先离开，稍后回来";pb.dataset.act="pause"}
  else{ag.className="pill off";ag.textContent=v.flow&&v.flow.status==="processing"?"答案已提交，等待智能体落实":v.open.length?"等待连接未就绪，答案提交后会保留":"当前阶段仍在制作或验证…";pb.hidden=true}
}
let TAB=(location.hash==="#review")?"review":"now", HFILTER="all", HQUERY="";
let QS={};   // 所有可见决策 id -> question（当前 + 回顾），查看器用
function histHTML(v){
  const H=v.history||[];
  if(!H.length) return `<div class="empty">还没有已作答的决策。</div>`;
  const stages=[...new Set(H.map(x=>x.stage))];
  let h=`<div class="hbar"><button class="chip" data-hf="all" aria-pressed="${HFILTER==="all"}">全部（${H.length}）</button>`+
    stages.map(s=>`<button class="chip" data-hf="${s}" aria-pressed="${String(HFILTER)===String(s)}">阶段 ${s} ${esc((v.stage_names||{})[s]||"")}（${H.filter(x=>x.stage===s).length}）</button>`).join("")+
    `<input type="text" class="hsearch" id="hq" placeholder="搜索标题、选项、备注" value="${esc(HQUERY)}"></div>
    <div class="howto">只读回顾：点图片或 ⤢ 全屏查看。想改已通过的决定，请在终端告诉智能体，它会按变更流程回退并重新请你确认。</div>`;
  const ql=HQUERY.trim().toLowerCase();
  const pick=H.filter(x=>(HFILTER==="all"||String(x.stage)===String(HFILTER)) && (!ql || JSON.stringify([x.id,x.title,x.context,(x.options||[]).map(o=>[o.label,o.desc]),x._answer.note,x._answer.other]).toLowerCase().includes(ql)));
  let cur=null;
  for(const x of pick){
    if(x.stage!==cur){cur=x.stage; h+=`<div class="hstage">阶段 ${cur} · ${esc((v.stage_names||{})[cur]||"")}${(v.passed||[]).includes(cur)?" · 已通过":""}</div>`}
    h+=histCard(x);
  }
  return h || `<div class="empty">没有匹配的决策。</div>`;
}
function histCard(x){
  const a=x._answer, chosen=new Set(a.setting?a.setting.values:(a.choice||[]));
  const lab=id=>{const o=(x.options||[]).find(o=>o.id===id); return o?`${id} ${o.label}`:id};
  const typeName={single:"单选",multi:"多选",scale:"刻度",tune:"调参",gate:"阶段验收"}[x.type]||x.type;
  const opts=(x.options||[]).map(o=>optHTML(x,o).replace('class="opt','class="opt'+(chosen.has(o.id)?" sel":"")).replace(/<button type="button" class="defbtn"[^>]*>[^<]*<\/button>/,"")).join("");
  const verdict=a.setting?`做成设置项：${a.setting.values.map(lab).join("、")}；默认 <b>${esc(lab(a.setting.default))}</b>`:
    (a.choice||[]).length?`选择 <b>${esc((a.choice||[]).map(lab).join("、"))}</b>`:(a.value?"提交了数值":"—");
  const by=a.answered_by==="agent"?"智能体代定":"你";
  const old=(x._superseded||[]).map(o=>`<div class="old">回退前曾选：${esc((o.choice||[]).join(","))||"—"}${o.note?"；"+esc(o.note):""}（${esc((o.ts||"").slice(0,16))}）</div>`).join("");
  return `<section class="dec hist" id="h-${esc(x.id)}">
    <div class="meta">${esc(x.id)} · ${typeName}${x.affects?" · 影响："+esc(x.affects):""}</div>
    <h2>${esc(x.title)}</h2>${x.context?`<div class="ctx">${esc(x.context)}</div>`:""}
    ${x.media?mediaHTML(x.media,x.id,null):""}${opts?`<div class="opts${x.type==="scale"?" scale":""}">${opts}</div>`:""}
    <div class="verdict">${verdict}${a.other?`；其他：${esc(a.other)}`:""}${a.note?`<div>备注：${esc(a.note)}</div>`:""}
      ${a.value?`<pre style="white-space:pre-wrap;margin:6px 0 0;font-size:12px">${esc(a.value)}</pre>`:""}
      <div class="old">${by} · ${esc((a.ts||"").slice(0,16).replace("T"," "))}</div>${old}</div>
  </section>`;
}
function render(v){
  DATA=v; MEDIA={}; ORDER={}; QS={};
  (v.open||[]).forEach(x=>QS[x.id]=x); (v.history||[]).forEach(x=>{ if(!QS[x.id]) QS[x.id]=x });
  document.querySelectorAll("#tabs button").forEach(b=>{b.setAttribute("aria-pressed",String(b.dataset.tab===TAB)); b.textContent=b.dataset.tab==="now"?`当前决策（${v.open.length}）`:`回顾（${(v.history||[]).length}）`});
  if(TAB==="review"){ $("#stage").textContent=`阶段 ${v.stage} · ${v.stage_name}`; const app=$("#app"); const y=scrollY;
    app.innerHTML=histHTML(v); fitVP(); if(V.open){ if(V.panes.every(k=>MEDIA[k])) renderViewer(); else closeViewer(); } scrollTo(0,y); return; }
  $("#stage").textContent=`阶段 ${v.stage} · ${v.stage_name}`;
  $("#mode").textContent=v.mode==="unattended"?"无人值守":"有人值守";
  $("#hint").textContent=STATIC?"静态页：选好后点「复制回复文本」，粘贴到对话里":"选好后提交；新决策会自动出现";

  const app=$("#app"); const keep=document.activeElement&&document.activeElement.dataset;
  let h="";
  for(const b of v.broken) h+=`<section class="dec"><div class="warn">决策 ${esc(b.id)} 格式错误，未展示：${esc(b._error)}</div></section>`;
  h+= v.open.length ? v.open.map(decHTML).join("") : `<div class="empty">当前没有需要你决定的事项。智能体准备好下一个决策后，这里会自动刷新。</div>`;
  if(v.queued.length) h+=`<div class="side"><b>排队中</b><ul>${v.queued.map(x=>`<li>${esc(x.id)} ${esc(x.title)}（等待 ${esc(x.waiting_for.join("、"))}）</li>`).join("")}</ul></div>`;
  if(v.answered.length) h+=`<div class="side"><b>本阶段已决定</b><ul>${v.answered.map(x=>`<li>${esc(x.id)} ${esc(x.title)}：${x.answer.setting?esc("设置项 "+x.answer.setting.values.join("/")+"，默认 "+x.answer.setting.default):esc((x.answer.choice||[]).join(",")||x.answer.other||"已提交数值")} <span style="color:${x.applied?"var(--ok)":"var(--mute)"}">${x.applied?"✓ 已落实":x.delivered?"· 已交付，待落实":"· 已提交，待交付"}</span></li>`).join("")}</ul></div>`;
  app.innerHTML=h;
  fitVP();
  if(V.open){ if(V.panes.every(k=>MEDIA[k])) renderViewer(); else closeViewer(); }
  for(const q of v.open){ (picks[q.id]||new Set()).forEach(o=>{const el=$(`.opt[data-q="${q.id}"][data-o="${o}"]`); el&&el.classList.add("sel")});
    const sm=SETM[q.id]; if(sm&&sm.on){const cb=$(`[data-setmode="${q.id}"]`); if(cb){cb.checked=true; $(`#d-${CSS.escape(q.id)}`).classList.add("setmode"); $(`[data-setrow="${q.id}"]`).classList.add("on")} markDefaults(q.id)}
    refresh(q.id); }
}
function fitVP(){document.querySelectorAll(".vp iframe").forEach(f=>{f.style.transform=`scale(${f.parentElement.clientWidth/(+f.dataset.vw)})`})}
addEventListener("resize",fitVP);
function q(id){return DATA.open.find(x=>x.id===id)}
function refresh(id){const b=$(`[data-submit="${id}"]`); if(b) b.disabled=!canSubmit(q(id));}
function toggle(el){ choose(el.dataset.q, el.dataset.o); }
function choose(id,o){
  const qq=q(id),s=picks[id]=picks[id]||new Set(), sm=SETM[id];
  if(qq.type==="multi"||(sm&&sm.on)){ if(s.has(o)){s.delete(o); if(sm&&sm.def===o) sm.def=null} else { if(sm&&sm.on&&s.size>=4){toast("最多保留 4 个");return} s.add(o); if(sm&&sm.on&&!sm.def) sm.def=o } }
  else {s.clear();s.add(o)}
  markDefaults(id);
  document.querySelectorAll(`.opt[data-q="${id}"]`).forEach(e=>e.classList.toggle("sel",s.has(e.dataset.o)));
  refresh(id);
  if(V.open) renderViewerChrome();
}
function markDefaults(id){const sm=SETM[id]; document.querySelectorAll(`.opt[data-q="${id}"]`).forEach(e=>e.classList.toggle("def",!!(sm&&sm.on&&sm.def===e.dataset.o)));}
function setMode(id,on){ SETM[id]={on,def:null}; const s=picks[id]=picks[id]||new Set();
  if(on){ if(s.size===1) SETM[id].def=[...s][0]; } else { const keep=[...s][0]; s.clear(); if(keep) s.add(keep); }
  const sec=$(`#d-${CSS.escape(id)}`); sec&&sec.classList.toggle("setmode",on); const r=$(`[data-setrow="${id}"]`); r&&r.classList.toggle("on",on);
  document.querySelectorAll(`.opt[data-q="${id}"]`).forEach(e=>e.classList.toggle("sel",s.has(e.dataset.o)));
  markDefaults(id); refresh(id); if(V.open) renderViewerChrome(); }
function payload(id){const sm=SETM[id]; if(sm&&sm.on) return {choice:[sm.def],setting:{values:[...(picks[id]||[])],default:sm.def},other:"",note:($(`[data-note="${id}"]`)||{}).value||""};
  return {choice:[...(picks[id]||[])],other:($(`[data-other="${id}"]`)||{}).value||"",note:($(`[data-note="${id}"]`)||{}).value||"",value:($(`[data-value="${id}"]`)||{}).value||null}}
document.addEventListener("click",async e=>{
  if(e.target.closest("#vw")) return;
  const z=e.target.closest("[data-view]"); if(z){e.preventDefault();openViewer(z.dataset.view);return}
  const df=e.target.closest("[data-def]"); if(df){const [qid,oid]=df.dataset.def.split("|"); SETM[qid].def=oid; markDefaults(qid); refresh(qid); e.stopPropagation(); return}
  const tb=e.target.closest("[data-tab]"); if(tb){TAB=tb.dataset.tab; history.replaceState(null,"",TAB==="review"?"#review":"#"); sig=""; scrollTo(0,0); load(); return}
  const hf=e.target.closest("[data-hf]"); if(hf){HFILTER=hf.dataset.hf; render(DATA); return}
  const o=e.target.closest(".opt"); if(o){ if(o.closest(".hist")) return; toggle(o);return}
  const s=e.target.closest("[data-submit]"); if(s){
    const id=s.dataset.submit; s.disabled=true;
    const r=await fetch(`/api/answer/${encodeURIComponent(id)}`,{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify(payload(id))});
    const t=await r.text(); if(r.ok){delete picks[id];toast("已提交 "+id);load()}else{toast(t);s.disabled=false} return}
  if(e.target.id==="pause"){await fetch("/api/"+e.target.dataset.act,{method:"POST"});load();return}
  const c=e.target.closest("[data-copy]"); if(c){
    const id=c.dataset.copy,p=payload(id);
    const txt=p.setting?`${id}=设置项 ${p.setting.values.join("/")} 默认 ${p.setting.default}${p.note?" 备注:"+p.note:""}`:`${id}=${p.choice.join(",")||"-"}${p.other?" 其他:"+p.other:""}${p.note?" 备注:"+p.note:""}${p.value?"\n"+p.value:""}`;
    try{await navigator.clipboard.writeText(txt);toast("已复制，粘贴到对话即可")}catch(_){prompt("复制下面的文字：",txt)} }
});
document.addEventListener("keydown",e=>{ if(V.open){viewerKey(e);return}
  const o=e.target.closest&&e.target.closest(".opt"); if(o&&(e.key==="Enter"||e.key===" ")&&!e.target.closest("button")){e.preventDefault();toggle(o)} });
document.addEventListener("change",e=>{const m=e.target.dataset&&e.target.dataset.setmode; if(m) setMode(m,e.target.checked);});
document.addEventListener("input",e=>{ if(e.target.id==="hq"){HQUERY=e.target.value; const pos=e.target.selectionStart; render(DATA); const n=$("#hq"); n.focus(); n.setSelectionRange(pos,pos); return}
  const d=e.target.dataset; const id=d.other||d.note||d.value; if(id&&DATA) refresh(id)});
// playground 通过 parent.postMessage({type:"decide:value", value:"--x: …"}, "*") 回传数值
window.addEventListener("message",e=>{const m=e.data; if(!m||m.type!=="decide:value"||!DATA)return;
  const t=DATA.open.find(x=>x.type==="tune"); if(!t)return; const ta=$(`[data-value="${t.id}"]`); if(ta){ta.value=m.value;refresh(t.id)}});
// 页面样张的 attrs：在样张页面的 <html> 上设置 data-* 属性（如 {"mode":"dark"}），用同一个原型预览不同主题
document.addEventListener("load",e=>{const f=e.target; if(!(f instanceof HTMLIFrameElement)||!f.dataset.attrs) return;
  try{const a=JSON.parse(f.dataset.attrs), h=f.contentDocument.documentElement; for(const [k,v] of Object.entries(a)) h.setAttribute("data-"+k,v)}catch(_){}},true);
// ================= 放大查看器 =================
const V={open:false,qid:null,panes:[],act:0,cmp:false,z:1,cx:.5,cy:.5,w:null,geo:[]};
const vw=$("#vw"), vstage=$("#vstage");
function optOf(k){const it=MEDIA[k];const qq=QS[it.qid];return qq&&(qq.options||[]).find(o=>o.id===it.oid)}
function openViewer(key){
  if(!MEDIA[key]) return;
  V.open=true; V.qid=MEDIA[key].qid; V.panes=[key]; V.act=0; V.cmp=false; V.w=null; resetView();
  vw.hidden=false; document.body.style.overflow="hidden"; renderViewer(); $("#vclose").focus();
}
function closeViewer(){ if(document.fullscreenElement) document.exitFullscreen().catch(()=>{}); V.open=false; vw.hidden=true; vstage.innerHTML=""; document.body.style.overflow=""; }
function resetView(){V.z=1;V.cx=.5;V.cy=.5}
function keys(){return ORDER[V.qid]||[]}
function otherOptionKey(k){const ks=keys(), it=MEDIA[k]; return ks.find(x=>MEDIA[x].oid&&MEDIA[x].oid!==it.oid) || ks.find(x=>x!==k) || k}
function renderViewer(){
  vstage.className="vstage"+(V.cmp?" two":"");
  vstage.innerHTML="";
  V.geo=[];
  V.panes.forEach((k,i)=>vstage.append(makePane(k,i)));
  renderViewerChrome();
  requestAnimationFrame(layout);
}
function paneLabel(k,i){
  const it=MEDIA[k], o=optOf(k), sel=it.oid&&(picks[it.qid]||new Set()).has(it.oid);
  if(!V.cmp) return "";
  const opts=keys().map(x=>{const ox=optOf(x), m=MEDIA[x];return `<option value="${esc(x)}"${x===k?" selected":""}>${esc(m.oid||"题目")}${ox?" "+esc(ox.label):""}${keys().filter(y=>MEDIA[y].oid===m.oid).length>1?" #"+(+x.split("|")[2]+1):""}</option>`}).join("");
  return `<select data-pane="${i}" aria-label="第 ${i+1} 栏显示">${opts}</select>${sel?'<span class="ok">✓ 已选</span>':""}`;
}
function makePane(k,i){
  const it=MEDIA[k], m=it.m;
  const pane=document.createElement("div"); pane.className="pane"+(i===V.act?" act":""); pane.dataset.i=i;
  pane.innerHTML=`<div class="pl">${paneLabel(k,i)}</div><div class="pc"></div>`;
  const pc=pane.querySelector(".pc");
  const t=m.type||"image";
  if(t==="image"){
    pc.classList.add("img");
    const img=new Image(); img.alt=m.alt||""; img.draggable=false; img.src=m.url;
    img.onload=()=>{V.geo[i]=Object.assign(V.geo[i]||{}, {nw:img.naturalWidth,nh:img.naturalHeight}); layout(); renderViewerChrome();};
    pc.append(img); V.geo[i]={type:"image",img,pc};
    bindPan(pc,i);
  } else if(t==="html"){
    const f=document.createElement("iframe"); f.setAttribute("sandbox", m.trusted||m.attrs?"allow-scripts allow-same-origin":"allow-scripts"); if(m.attrs) f.dataset.attrs=JSON.stringify(m.attrs); f.src=m.url; f.title=it.oid||"page";
    pc.append(f); V.geo[i]={type:"html",f,pc,vw:m.viewport||1440};
  } else if(t==="video"){
    pc.innerHTML=`<video src="${esc(m.url)}" controls autoplay loop muted playsinline></video>`; V.geo[i]={type:"video",pc};
  } else {
    pc.innerHTML=`<div class="lk"><a href="${esc(m.url)}" target="_blank" rel="noopener">${esc(m.label||m.url)} ↗</a></div>`; V.geo[i]={type:"link",pc};
  }
  pane.addEventListener("pointerdown",()=>{ if(V.act!==i){V.act=i; vstage.querySelectorAll(".pane").forEach(p=>p.classList.toggle("act",+p.dataset.i===i)); renderViewerChrome();} },true);
  return pane;
}
function fitOf(g){const pw=g.pc.clientWidth, ph=g.pc.clientHeight; return Math.min(pw/g.nw, ph/g.nh, 4)}
function layout(){
  V.geo.forEach((g,i)=>{
    if(!g) return;
    const pw=g.pc.clientWidth, ph=g.pc.clientHeight;
    if(g.type==="image" && g.nw){
      const fit=fitOf(g), s=fit*V.z, W=g.nw*s, H=g.nh*s;
      let cx=V.cx, cy=V.cy;
      cx = W<=pw ? .5 : Math.min(Math.max(cx, pw/2/W), 1-pw/2/W);
      cy = H<=ph ? .5 : Math.min(Math.max(cy, ph/2/H), 1-ph/2/H);
      if(i===V.act){V.cx=cx;V.cy=cy}
      g.s=s; g.x=pw/2-cx*W; g.y=ph/2-cy*H;
      g.img.style.width=g.nw+"px"; g.img.style.height=g.nh+"px";
      g.img.style.transform=`translate(${g.x}px,${g.y}px) scale(${s})`;
      g.pc.classList.toggle("pix", s>=3);
    } else if(g.type==="html"){
      const W=V.w||g.vw, sc=Math.min(1,pw/W);
      g.f.style.width=W+"px"; g.f.style.height=(ph/sc)+"px"; g.f.style.transform=`scale(${sc})`;
      g.sc=sc;
    }
  });
  zoomLabel();
}
function zoomLabel(){const g=V.geo[V.act]; $("#vzl").textContent = g&&g.type==="image"&&g.s ? (Math.abs(V.z-1)<.01?"适应 ":"")+Math.round(g.s*100)+"%" : "适应";}
function zoomAt(i,px,py,factor){
  const g=V.geo[i]; if(!g||!g.nw) return;
  const fit=fitOf(g), pw=g.pc.clientWidth, ph=g.pc.clientHeight;
  const u=((px-g.x)/g.s)/g.nw, v=((py-g.y)/g.s)/g.nh;
  const z=Math.min(Math.max(V.z*factor, .5), 12/fit);
  const s2=fit*z;
  V.cx=u-(px-pw/2)/(g.nw*s2); V.cy=v-(py-ph/2)/(g.nh*s2); V.z=z; layout();
}
function zoomCenter(f){const g=V.geo[V.act]; if(g&&g.nw) zoomAt(V.act,g.pc.clientWidth/2,g.pc.clientHeight/2,f)}
function oneToOne(){const g=V.geo[V.act]; if(!g||!g.nw) return; const f=fitOf(g); zoomCenter((1/f)/V.z)}
function bindPan(pc,i){
  const pts=new Map(); let last=null, pinch=null;
  pc.addEventListener("wheel",e=>{e.preventDefault(); const r=pc.getBoundingClientRect(); zoomAt(i,e.clientX-r.left,e.clientY-r.top,Math.exp(-e.deltaY*(e.ctrlKey?0.01:0.0015)))},{passive:false});
  pc.addEventListener("dblclick",e=>{const r=pc.getBoundingClientRect(), g=V.geo[i]; if(!g.nw) return;
    if(V.z>1.05){resetView();layout()} else { const f=fitOf(g); zoomAt(i,e.clientX-r.left,e.clientY-r.top, Math.max(2.5,1/f)/V.z) }});
  pc.addEventListener("pointerdown",e=>{pc.setPointerCapture(e.pointerId); pts.set(e.pointerId,{x:e.clientX,y:e.clientY}); last={x:e.clientX,y:e.clientY}; pc.classList.add("drag"); if(pts.size===2) pinch=null;});
  pc.addEventListener("pointermove",e=>{ if(!pts.has(e.pointerId)) return; pts.set(e.pointerId,{x:e.clientX,y:e.clientY}); const g=V.geo[i]; if(!g||!g.nw) return;
    if(pts.size===2){const [a,b]=[...pts.values()], d=Math.hypot(a.x-b.x,a.y-b.y), r=pc.getBoundingClientRect();
      if(pinch) zoomAt(i,(a.x+b.x)/2-r.left,(a.y+b.y)/2-r.top,d/pinch); pinch=d; return;}
    const W=g.nw*g.s, H=g.nh*g.s; V.cx-=(e.clientX-last.x)/W; V.cy-=(e.clientY-last.y)/H; last={x:e.clientX,y:e.clientY}; layout(); });
  const up=e=>{pts.delete(e.pointerId); pinch=null; if(!pts.size) pc.classList.remove("drag"); else last=[...pts.values()][0];};
  pc.addEventListener("pointerup",up); pc.addEventListener("pointercancel",up);
}
function renderViewerChrome(){
  const k=V.panes[V.act], it=MEDIA[k]; if(!it) return;
  const qq=QS[V.qid], o=optOf(k), m=it.m, g=V.geo[V.act]||{}, live=!!DATA.open.find(x=>x.id===V.qid);
  const ks=keys();
  $("#vq").textContent=`${qq?qq.id+" · "+qq.title:""}`;
  $("#vn").textContent=V.cmp?"并排对比 · 缩放与平移同步":`${ks.indexOf(k)+1} / ${ks.length}`;
  const types=V.panes.map(p=>MEDIA[p].m.type||"image");
  $("#vzoom").hidden=!types.includes("image"); $("#vwidth").hidden=!types.includes("html");
  const curW=V.w||(V.geo.find(x=>x&&x.type==="html")||{}).vw;
  document.querySelectorAll("#vwidth button").forEach(b=>b.setAttribute("aria-pressed",String(+b.dataset.w===curW)));
  $("#vcmp").setAttribute("aria-pressed",String(V.cmp)); $("#vcmp").hidden=ks.length<2;
  $("#vopen").href=m.url;
  const nw=g.nw||m.w, nh=g.nh||m.h;
  const dims = nw?` · ${nw}×${nh}`:"";
  const low = nw&&Math.max(nw,nh)<LOWRES?` <span class="bad">原图较小（长边 ${Math.max(nw,nh)}px），放大后会模糊</span>`:"";
  $("#vcap").innerHTML=`${it.oid?`<b>${esc(it.oid)}${o?" · "+esc(o.label):""}</b>`:"<b>题目附图</b>"}${o&&o.desc?" — "+esc(o.desc):""}
    <div>${esc(ORI[m.origin]||"")}${m.ref?" · "+esc(m.ref):""}${m.credit?` · <a href="${esc(m.credit)}" target="_blank" rel="noopener" style="color:#9cc3ff">${esc(m.credit)}</a>`:""}${dims}${low}</div>
    ${m.caveat?`<div class="w">${esc(m.caveat)}</div>`:""}${o&&o.motion?`<div>动效：${esc(o.motion)}</div>`:""}`;
  const sb=$("#vsel");
  if(it.oid && qq && !live && qq._answer){
    const a=qq._answer, ch=new Set(a.setting?a.setting.values:(a.choice||[]));
    sb.hidden=false; sb.classList.toggle("on",ch.has(it.oid)); sb.disabled=true;
    sb.textContent=ch.has(it.oid)?(a.setting&&a.setting.default===it.oid?`当时选了 ${it.oid}（默认）`:`当时选了 ${it.oid}`):`当时未选 ${it.oid}`;
  } else if(it.oid && qq && qq.type!=="tune"){ sb.disabled=false;
    const on=(picks[it.qid]||new Set()).has(it.oid), smv=SETM[it.qid]&&SETM[it.qid].on;
    sb.hidden=false; sb.classList.toggle("on",on);
    sb.textContent = on ? ((qq.type==="multi"||smv)?`已选 ${it.oid} ✓（点击取消）`:`已选 ${it.oid} ✓`) : (matchMedia("(hover:none)").matches?`选择 ${it.oid}`:`选择 ${it.oid}（Enter）`);
  } else sb.hidden=true;
  $("#vthumbs").innerHTML=ks.map(x=>{const mm=MEDIA[x].m, ox=MEDIA[x].oid, a=V.panes.indexOf(x); let on=ox&&(picks[V.qid]||new Set()).has(ox);
    const qh=QS[V.qid]; if(qh&&qh._answer&&!DATA.open.find(x=>x.id===V.qid)){const an=qh._answer; on=ox&&(an.setting?an.setting.values:(an.choice||[])).includes(ox)}
    const inner=(mm.type||"image")==="image"?`<img src="${esc(mm.url)}" alt="" loading="lazy">`:`<div class="ty">${mm.type==="html"?"网页":mm.type==="video"?"视频":"链接"}</div>`;
    return `<button class="vt${a===0?" a1":a===1?" a2":""}" data-vk="${esc(x)}" title="${esc(ox||"题目")}">${inner}<span>${esc(ox||"题目")}</span>${on?"<i>✓</i>":""}</button>`}).join("");
  const at=$("#vthumbs .a1"); at&&at.scrollIntoView({block:"nearest",inline:"nearest"});
  vstage.querySelectorAll(".pane").forEach(p=>{const i=+p.dataset.i, pl=p.querySelector(".pl"); if(V.cmp) pl.innerHTML=paneLabel(V.panes[i],i);});
  zoomLabel();
}
function step(d){const ks=keys(); if(ks.length<2) return; const k=V.panes[V.act]; V.panes[V.act]=ks[(ks.indexOf(k)+d+ks.length)%ks.length]; if(!V.cmp) resetView(); renderViewer();}
function toggleCompare(){ if(keys().length<2) return; V.cmp=!V.cmp; if(V.cmp){V.panes=[V.panes[0],otherOptionKey(V.panes[0])]; V.act=0} else {V.panes=[V.panes[V.act]]; V.act=0} renderViewer(); }
function selectCurrent(){const it=MEDIA[V.panes[V.act]]; if(it&&it.oid&&q(it.qid)&&!q(it.qid)._answer&&q(it.qid).type!=="tune") choose(it.qid,it.oid);}
function viewerKey(e){
  if(e.target.closest&&e.target.closest("select")) return;
  const k=e.key;
  if(k==="Escape"){e.preventDefault(); if(document.fullscreenElement) document.exitFullscreen(); else closeViewer(); return}
  if(k==="ArrowRight"){e.preventDefault();step(1)} else if(k==="ArrowLeft"){e.preventDefault();step(-1)}
  else if(k==="+"||k==="="){zoomCenter(1.25)} else if(k==="-"||k==="_"){zoomCenter(.8)}
  else if(k==="0"){resetView();layout()} else if(k==="1"){oneToOne()}
  else if(k==="c"||k==="C"){toggleCompare()} else if(k==="f"||k==="F"){toggleFs()}
  else if(k==="Enter"&&!e.target.closest("button,a")){e.preventDefault();selectCurrent()}
  else if(k==="Tab"){ /* 焦点留在查看器内 */ const f=[...vw.querySelectorAll("button:not([hidden]),a,select")].filter(x=>x.offsetParent); if(!f.length) return;
    const i=f.indexOf(document.activeElement); if(e.shiftKey&&i<=0){e.preventDefault();f[f.length-1].focus()} else if(!e.shiftKey&&i===f.length-1){e.preventDefault();f[0].focus()} }
}
function toggleFs(){ if(document.fullscreenElement) document.exitFullscreen(); else if(vw.requestFullscreen) vw.requestFullscreen().catch(()=>{}); }
vw.addEventListener("click",e=>{
  const t=e.target.closest("button"); if(!t) return;
  if(t.id==="vclose") closeViewer();
  else if(t.id==="vprev") step(-1); else if(t.id==="vnext") step(1);
  else if(t.id==="vcmp") toggleCompare();
  else if(t.id==="vfs") toggleFs();
  else if(t.id==="vsel") selectCurrent();
  else if(t.dataset.z){ ({out:()=>zoomCenter(.8),in:()=>zoomCenter(1.25),fit:()=>{resetView();layout()},one:oneToOne})[t.dataset.z]() }
  else if(t.dataset.w){V.w=+t.dataset.w; layout(); renderViewerChrome()}
  else if(t.dataset.vk){ V.panes[V.act]=t.dataset.vk; if(!V.cmp) resetView(); renderViewer(); }
});
vw.addEventListener("change",e=>{const s=e.target.closest("select[data-pane]"); if(!s) return; V.panes[+s.dataset.pane]=s.value; renderViewer();});
new ResizeObserver(()=>{ if(V.open) layout(); }).observe(vstage);
document.addEventListener("fullscreenchange",()=>{ if(V.open) requestAnimationFrame(layout); });

let sig="";
async function load(){
  if(STATIC){header(STATIC);render(STATIC);return}
  try{const r=await fetch("/api/state");const v=await r.json();const s=JSON.stringify([TAB,v.stage,v.open.map(x=>x.id),v.queued.length,v.answered.map(x=>x.id+x.delivered+x.applied),v.broken.length,(v.history||[]).map(x=>x.id+x._answer.ts)]);
    header(v); if(s!==sig){sig=s;render(v)}}catch(_){}
}
load(); if(!STATIC) setInterval(load,2000);
</script></body></html>"""


def make_handler(store):
    class H(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def send(self, code, body, ctype="text/plain; charset=utf-8"):
            b = body.encode("utf-8") if isinstance(body, str) else body
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(b)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(b)

        def do_GET(self):
            path = urllib.parse.urlparse(self.path).path
            if path in ("/", "/index.html"):
                return self.send(200, PAGE, "text/html; charset=utf-8")
            if path == "/api/ping":
                return self.send(200, "ok")
            if path == "/api/state":
                return self.send(200, json.dumps(store.view(), ensure_ascii=False), "application/json; charset=utf-8")
            if path.startswith("/files/"):
                rel = urllib.parse.unquote(path[len("/files/"):])
                full = os.path.abspath(os.path.join(store.root, rel))
                if not full.startswith(store.root + os.sep) or not os.path.isfile(full):
                    return self.send(404, "not found")
                ctype = mimetypes.guess_type(full)[0] or "application/octet-stream"
                if ctype.startswith("text/") or ctype in ("application/javascript", "application/json", "image/svg+xml"):
                    ctype += "; charset=utf-8"
                with open(full, "rb") as f:
                    return self.send(200, f.read(), ctype)
            self.send(404, "not found")

        def do_POST(self):
            path = urllib.parse.urlparse(self.path).path
            if path in ("/api/pause", "/api/resume"):
                waitlib.set_paused(store.root, path == "/api/pause")
                return self.send(200, "ok")
            if not path.startswith("/api/answer/"):
                return self.send(404, "not found")
            did = urllib.parse.unquote(path[len("/api/answer/"):])
            try:
                body = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))) or b"{}")
            except Exception:
                return self.send(400, "bad json")
            code, msg = store.answer(did, body)
            self.send(code, msg)
    return H


def cmd_serve(a):
    store = Store(a.root, a.max_open)
    store.state()
    if a.host not in ("127.0.0.1", "localhost"):
        print("[decide] 警告：监听非本机地址，局域网内任何人都能打开并作答。")
    srv = ThreadingHTTPServer((a.host, a.port), make_handler(store))
    os.makedirs(os.path.join(store.root, P.RUNTIME), exist_ok=True)
    with open(P.runtime(store.root, ".server.json"), "w") as f:
        json.dump({"port": a.port, "pid": os.getpid()}, f)
    print(f"[decide] 决策页面：http://{'localhost' if a.host in ('127.0.0.1','0.0.0.0') else a.host}:{a.port}/")
    print("[decide] 若通过 SSH 连到这台机器，在本地终端运行：ssh -L %d:localhost:%d <主机>，再在本地浏览器打开上面的地址" % (a.port, a.port))
    sys.stdout.flush()
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass


def cmd_wait(a):
    """单段等待返回后接续同一流程；不因超时或空闲要求人工继续。"""
    root = os.path.abspath(a.root)
    status, payload = waitlib.wait(root, a.chunk, a.idle, who="cli")
    if status == "answered":
        print(f"[decide] 用户提交了 {len(payload['new'])} 个答案：")
        print(payload["new_text"])
        print(f"[decide] 仍待作答：{payload['open'] or '无'}；排队：{payload['queued'] or '无'}")
    print(f"[decide] 下一步：{payload['next']}")
    print("RESULT " + json.dumps({**{k: v for k, v in payload.items() if k != "new_text"},
                                 "flow_status": payload.get("status"), "status": status}, ensure_ascii=False))
    sys.exit(waitlib.STATUS[status])


def cmd_ack(a):
    try:
        waitlib.ack_answer(os.path.abspath(a.root), a.id, a.ts)
    except ValueError as e:
        sys.exit(f"[decide] 确认失败：{e}")
    print(f"[decide] 已确认 {a.id} 的指定版本已落实。立即查询 gate.py next --json。")


def cmd_pause(a):
    waitlib.set_paused(os.path.abspath(a.root), True)
    print("[decide] 已暂停：Stop hook 不再等待或续跑，用户回来后运行 resume")


def cmd_resume(a):
    waitlib.set_paused(os.path.abspath(a.root), False)
    print("[decide] 已解除暂停。立即查询 gate.py next --json，接续原任务。")


def cmd_export(a):
    store = Store(a.root, a.max_open)
    v = store.view(static=True)
    html = PAGE.replace("<script>\nconst STATIC", "<script>window.__STATIC__=" + json.dumps(v, ensure_ascii=False).replace("</", "<\\/") + ";</script>\n<script>\nconst STATIC", 1)
    out = os.path.join(store.root, P.EXPORT, "index.html")
    os.makedirs(os.path.dirname(out), exist_ok=True)
    with open(out, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"[decide] 已生成静态决策页：{out}（开放决策 {len(v['open'])} 个）")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--root", default=None, help=f"设计目录，默认向上查找 {P.DIRNAME}/")
    ap.add_argument("--max-open", type=int, default=3)
    sp = ap.add_subparsers(dest="cmd", required=True)
    p = sp.add_parser("serve"); p.add_argument("--port", type=int, default=8765); p.add_argument("--host", default="127.0.0.1"); p.set_defaults(f=cmd_serve)
    p = sp.add_parser("wait"); p.add_argument("--chunk", type=float, default=45, help="单次最长等待秒数；到时续接等待，须小于工具时限")
    p.add_argument("--idle", type=float, default=0, help="空闲提示间隔（分钟）；提示后续接等待，0 为不提示"); p.set_defaults(f=cmd_wait)
    p = sp.add_parser("ack"); p.add_argument("id"); p.add_argument("--ts", required=True); p.set_defaults(f=cmd_ack)
    sp.add_parser("resume").set_defaults(f=cmd_resume)
    sp.add_parser("pause").set_defaults(f=cmd_pause)
    sp.add_parser("export").set_defaults(f=cmd_export)
    a = ap.parse_args()
    if a.root is None:
        a.root = P.default_root()
    a.f(a)


if __name__ == "__main__":
    main()
