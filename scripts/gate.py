#!/usr/bin/env python3
"""阶段闸门（状态机）。只依赖标准库。

用法（在项目根目录执行；设计目录为项目下的 .taste-design/，目录划分见 paths.py）：
  gate.py init [--phase ID] [--name 名称] [--mode attended|unattended] [--channel web|inline|static] [--media ignore|lfs|commit]
  gate.py phase list [--json]       # 列出同一项目的多个设计期
  gate.py phase add ID --name 名称 [--parent ID] [--inherit shared/brand.md ...]
  gate.py media ignore|lfs|commit   # 切换 media/ 的 git 策略（重写 .gitignore / .gitattributes）
  gate.py migrate [--from design]   # 把旧版 design/ 目录迁移到 .taste-design/
  gate.py status                    # 当前阶段、轨道、本阶段还差什么
  gate.py context --json --compact   # 默认恢复入口；详情按需用完整输出或 --section 分页
    gate.py next [--json]              # 统一流程状态、完整未确认答案与下一步
    gate.py block --reason … --tried … --needs …  # 登记需用户处理的真实外部阻塞
    gate.py unblock --reason …         # 解除阻塞后接续原任务
  gate.py check N                   # 开始阶段 N 的工作前必须调用；不允许则退出码 1
  gate.py pass N                    # 申请通过闸门 N；条件不满足则退出码 1
  gate.py skip N --reason "…"       # 跳过可选阶段（快速轨道的 playground），自动写入待复核清单
  gate.py assume --topic "…" --choice "…" --why "…"
                                    # 次要事项由智能体代定，写入 pending-review.md
  gate.py add-page 名称 --reason "…" # 范围确定后新增页面：只让该页补走流程，不整体回退
  gate.py rollback N --reason "…"   # 变更管理：回退到阶段 N（回退到 0 可重新定范围和轨道）
  gate.py channel web|inline|static --reason "…"
  gate.py record ID --choice B [--note …] --via chat --quote "用户原话" [--setting A,B]

阶段：0 启动与范围 → 1 创意简报 → 2 灰模 → 3 视觉发散 → 4 原型与资产规范 → 5 令牌
      → 6 区块打磨 → 7 全站铺开 → 8 质量检查 → 9 交付
闸门 0 通过时按 scope.json 确定本项目的阶段序列（省略、合并、可选）。
"""
import argparse, datetime, glob, json, os, re, shutil, sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from rules import validate_question  # noqa: E402
from stages import STAGES, ALL, load_scope, validate_scope, validate_phase_scope, plan, in_scope_pages  # noqa: E402
import paths as P  # noqa: E402
import summary as SUM  # noqa: E402
import theme as TH  # noqa: E402
import delivery as DL  # noqa: E402

SYNC_RE = re.compile(r"同步至闸门\s*[:：]\s*(\d+)")


def now():
    return datetime.datetime.now().astimezone().isoformat(timespec="microseconds")


def name(n):
    return f"{n} {STAGES[n]['name']}"


def load_state(root):
    p = os.path.join(root, P.STATE)
    if not os.path.exists(p):
        sys.exit(f"[gate] 未初始化：找不到 {p}。先运行 gate.py init")
    with open(p, encoding="utf-8") as f:
        st = json.load(f)
    st.setdefault("sequence", list(ALL))
    st.setdefault("merged", {})
    st.setdefault("optional", [])
    st["merged"] = {int(k): v for k, v in st["merged"].items()}
    meta = P.phase_info(root)
    if meta:
        st.setdefault("phase", meta.get("id"))
    return st


def save_state(root, st):
    st = dict(st)
    st["merged"] = {str(k): v for k, v in st["merged"].items()}
    with open(os.path.join(root, P.STATE), "w", encoding="utf-8") as f:
        json.dump(st, f, ensure_ascii=False, indent=2)


def log(root, line):
    with open(os.path.join(root, P.LOG), "a", encoding="utf-8") as f:
        f.write(line + "\n")


def pending_add(root, stage, topic, choice, why):
    p = os.path.join(root, P.PENDING)
    new = not os.path.exists(p)
    with open(p, "a", encoding="utf-8") as f:
        if new:
            f.write("# 待你复核：这些是智能体代为决定的，可以推翻\n\n")
        f.write(f"- [ ] （阶段 {stage}）{topic}：{choice} —— {why}\n")


PENDING_RE = re.compile(r"^- \[ \] （阶段 (\d+)）(.+?)：")


def pending_topics(root, stages):
    p = os.path.join(root, P.PENDING)
    if not os.path.exists(p):
        return []
    out = []
    with open(p, encoding="utf-8") as f:
        for line in f:
            m = PENDING_RE.match(line)
            if m and int(m.group(1)) in stages:
                out.append(m.group(2))
    return out


def snapshot(root, n):
    sc = load_scope(root) or {}
    if sc.get("delivery_mode") == "design-only":
        return []
    container = os.path.dirname(os.path.dirname(root)) if P.phase_info(root) else root
    base = os.path.dirname(container)
    dst = os.path.join(root, P.SNAPSHOTS, f"gate-{n}")
    copied = []
    for src in sc.get("source_dirs") or []:
        full = os.path.abspath(os.path.join(base, src))
        if not os.path.exists(full):
            print(f"[gate] 警告：source_dirs 里的 {src} 不存在，未快照")
            continue
        target = os.path.join(dst, src.strip("/").replace("..", "_"))
        if os.path.isdir(full):
            shutil.copytree(full, target, dirs_exist_ok=True,
                            ignore=shutil.ignore_patterns("node_modules", ".git", "__pycache__", "dist", "build", "target"))
        else:
            os.makedirs(os.path.dirname(target), exist_ok=True)
            shutil.copy2(full, target)
        copied.append(src)
    return copied


def pending_count(root):
    p = os.path.join(root, P.PENDING)
    if not os.path.exists(p):
        return 0
    with open(p, encoding="utf-8") as f:
        return sum(1 for line in f if line.startswith("- [ ]"))


def decisions(root, stages=None):
    out = []
    for q in sorted(glob.glob(os.path.join(root, P.DECISIONS, "*", "question.json"))):
        d = os.path.dirname(q)
        try:
            with open(q, encoding="utf-8") as f:
                qj = json.load(f)
        except Exception as e:
            print(f"[gate] 警告：{q} 不是合法 JSON：{e}", file=sys.stderr)
            continue
        qj.setdefault("id", os.path.basename(d))
        qj["_dir"] = d
        ap = os.path.join(d, "answer.json")
        qj["_answer"] = None
        if os.path.exists(ap):
            with open(ap, encoding="utf-8") as f:
                qj["_answer"] = json.load(f)
        if stages is None or qj.get("stage") in stages:
            out.append(qj)
    return out


def stages_of(st, n):
    """闸门 n 覆盖的阶段：自己 + 并入它的阶段。"""
    return [n] + [k for k, v in st["merged"].items() if v == n]


def user_ok(a, st):
    return a and (a.get("answered_by") == "user" or (a.get("answered_by") == "agent" and st.get("mode") == "unattended"))


def read(root, rel):
    p = os.path.join(root, rel)
    if not os.path.exists(p):
        return None
    with open(p, encoding="utf-8") as f:
        return f.read()


def blockers(root, st, n):
    probs = []
    covered = stages_of(st, n)
    sc = load_scope(root)
    probs += DL.check(root, st, sc, decisions(root))

    # 产物
    for s in covered:
        for f in STAGES[s]["files"]:
            if not os.path.exists(os.path.join(root, f)):
                probs.append(f"缺少产物 {f}")
        for g in STAGES[s]["globs"]:
            if not glob.glob(os.path.join(root, g)):
                probs.append(f"缺少产物 {g}")

    ds = decisions(root, covered)
    by_role = lambda r: [d for d in ds if d.get("role") == r]  # noqa: E731

    # 阶段专属检查
    if n == 0:
        if sc is None:
            probs.append("缺少 scope.json")
        else:
            probs += validate_scope(sc)
            meta = P.phase_info(root)
            container = os.path.dirname(os.path.dirname(root)) if meta else None
            probs += validate_phase_scope(sc, meta, container)
            for rel in (meta or {}).get("inherits") or []:
                try:
                    path = P.inheritance_path(container, rel)
                except ValueError as e:
                    probs.append(str(e))
                    continue
                if not os.path.exists(path):
                    probs.append(f"继承基线不存在：{rel}；请先补齐跨期基线，或在本期 phase.json 中移除这条继承")
            if sc.get("mode") == "redesign":
                shots = [f for ext in ("png", "jpg", "jpeg", "webp") for f in glob.glob(os.path.join(root, P.BASELINE, f"*.{ext}"))]
                need = max(1, len(in_scope_pages(sc)))
                if len(shots) < need:
                    probs.append(f"改版项目必须先截现状基线：{P.BASELINE}/ 里需要至少 {need} 张截图（每页一张），现有 {len(shots)} 张。"
                                 "截不了时请用户提供截图，不能跳过")
        if not any(user_ok(d["_answer"], st) for d in by_role("scope")):
            probs.append("需要一个 role=scope 的决策（改动范围 / 布局自由度 / 轨道）并由用户作答")
    if 3 in covered:
        html = read(root, "work/variants/variants.html") or ""
        if 'data-intensity="大胆"' not in html:
            probs.append("variants.html 里至少要有一个 data-intensity=\"大胆\" 的方案")
        extra = [os.path.basename(p) for p in glob.glob(os.path.join(root, "work", "variants", "*.html")) if os.path.basename(p) != "variants.html"]
        if extra:
            probs.append(f"方案必须集中在 work/variants/variants.html 一个页面里，发现多余文件：{extra}")
        lc = os.path.join(root, "work", "variants", "layout-check.json")
        vpath = os.path.join(root, "work", "variants", "variants.html")
        if not os.path.exists(lc):
            probs.append("缺少 work/variants/layout-check.json：运行 variants_check.py 检查克制 / 中等 / 大胆的布局差异")
        else:
            res = json.loads(read(root, "work/variants/layout-check.json") or "{}")
            if sc and res.get("layout_freedom") != sc.get("layout_freedom"):
                probs.append("布局自由度与 layout-check.json 不一致：按已批准的 scope.json 重新运行 variants_check.py，不得改报告绕过检查")
            if os.path.exists(vpath) and res.get("variants_mtime", 0) + 1 < os.path.getmtime(vpath):
                probs.append("variants.html 改过之后没有重新运行 variants_check.py")
            for r in res.get("variants", []):
                for x in r.get("problems", []):
                    probs.append(f"方案 {r['id']}（{r.get('intensity')}）：{x}")
        if not any(user_ok(d["_answer"], st) for d in by_role("direction")):
            probs.append("需要一个 role=direction 的方向选择决策并由用户作答")
    if n == 1 and sc:
        for ref in sc.get("references") or []:
            if not any(d.get("reference") == ref and user_ok(d["_answer"], st) for d in by_role("reference-breakdown")):
                probs.append(f"参考「{ref}」还没有做参考拆解（role=reference-breakdown, reference=\"{ref}\"）")
    if n == 4 and sc and sc.get("asset_types"):
        spec = read(root, "work/assets/spec.md") or ""
        miss = [a for a in sc["asset_types"] if a not in spec]
        if miss:
            probs.append(f"work/assets/spec.md 没有覆盖这些资产类型：{miss}")
        if not any(user_ok(d["_answer"], st) for d in by_role("asset-benchmark")):
            probs.append("需要一个 role=asset-benchmark 的决策，让用户为每类资产选定基准资产")
    if n == 4 and sc and sc.get("product_type") == "app":
        content = read(root, f"{P.BRIEF}/content.yaml") or ""
        if "states:" not in content:
            probs.append("应用类项目的 content.yaml 需要状态表（states:）：加载中、空、错误/断线、超阈值、权限不足等")
        protos = sorted(glob.glob(os.path.join(root, "work", "proto", "v*.html")))
        if protos:
            with open(protos[-1], encoding="utf-8") as f:
                if "demo" not in f.read():
                    probs.append(f"{os.path.basename(protos[-1])} 没有状态切换入口：原型需支持 ?demo=<状态> 参数或演示面板，让每个状态都能看到")
    if n == 4:
        traits = read(root, f"{P.BRIEF}/traits.md") or ""
        if re.search(r"\|\s*(motion|texture)\s*\|", traits) and "图层表" not in traits:
            probs.append("主题带质感或动效时，traits.md 需要「图层表」：背景 / 容器 / 数据 / 文字各层有无质感、动不动")
    if n == 7 and sc:
        try:
            pages = json.loads(read(root, "work/rollout/pages.json") or "[]")
            names = {p.get("name") for p in pages} if isinstance(pages, list) else set()
            miss = [p for p in in_scope_pages(sc) if p not in names]
            if miss:
                probs.append(f"work/rollout/pages.json 缺少这些页面：{miss}")
            undone = [p.get("name") for p in pages if isinstance(p, dict) and p.get("status") != "done"]
            if undone:
                probs.append(f"这些页面还没完成本期交付（status 不是 done）：{undone}")
            if sc.get("delivery_mode") == "design-only":
                for p in pages:
                    if not isinstance(p, dict):
                        continue
                    proto = p.get("prototype", "")
                    full = os.path.realpath(os.path.join(root, proto))
                    if not proto.startswith("work/") or not full.startswith(os.path.realpath(os.path.join(root, "work")) + os.sep) or not os.path.isfile(full):
                        probs.append(f"仅设计模式的页面「{p.get('name')}」需要 prototype 指向 work/ 内实际存在的工作原型")
        except Exception as e:
            probs.append(f"work/rollout/pages.json 无法解析：{e}")
    if n == 8 and sc and sc.get("asset_types"):
        html = read(root, "work/qa/asset-compare.html")
        if html is None:
            probs.append("缺少 work/qa/asset-compare.html：所有衍生资产与基准资产的并排对照（模板 templates/asset-compare.html）")
        else:
            m = re.search(r'<script id="data" type="application/json">(.*?)</script>', html, re.S)
            try:
                data = json.loads(m.group(1)) if m else None
                bad = []
                for g in (data or {}).get("groups", []):
                    for it in g.get("items", []):
                        ch = it.get("checks") or []
                        if "fail" in ch or len(ch) < len(g.get("criteria", [])):
                            bad.append(f"{g.get('type')}/{it.get('name')}")
                missing = [a for a in sc["asset_types"] if a not in {g.get("type") for g in (data or {}).get("groups", [])}]
                if data is None:
                    probs.append("work/qa/asset-compare.html 里找不到数据块")
                if missing:
                    probs.append(f"资产对照缺少这些类型：{missing}")
                if bad:
                    probs.append(f"这些衍生资产细节密度低于基准，不能交付：{bad}")
            except Exception as e:
                probs.append(f"work/qa/asset-compare.html 数据无法解析：{e}")
    # 设置项（主题 / 外观维度）
    spec = TH.load(root)
    for d in TH.setting_answers(ds):
        if not (sc or {}).get("user_customizable"):
            probs.append(f"{d['id']} 被做成了设置项，但 scope.json 的 user_customizable 是 false：先和用户确认，再 gate.py rollback 0 修改范围")
    if n in (5, 6) and ((sc or {}).get("user_customizable") or spec is not None):
        probs += TH.validate(root, spec, decisions(root), sc)
    if n == 8 and spec is not None:
        probs += TH.validate_matrix(root, spec)
    if n == 8 and not os.path.exists(os.path.join(root, "work", "qa", "manual-checks.md")):
        probs.append("缺少 work/qa/manual-checks.md：列出本环境验证不了、需要用户在目标设备上亲自看的项（没有就写「无」）")
    if n == 9:
        ho = read(root, "work/handoff/HANDOFF.md") or ""
        if ho and "验证" not in ho:
            probs.append("work/handoff/HANDOFF.md 的每个人工步骤都要写明验证方法（含「验证」字样）")
        if pending_count(root) and not any(user_ok(d["_answer"], st) for d in by_role("pending-review")):
            probs.append(f"pending-review.md 里有 {pending_count(root)} 项智能体代定事项，需要一个 role=pending-review 的决策让用户集中复核")

    # 活文档同步：每过一个闸门，brief 和 traits 都要同步到最新结论
    if n >= 1:
        for f in (f"{P.BRIEF}/brief.md", f"{P.BRIEF}/traits.md"):
            txt = read(root, f)
            if txt is None:
                continue
            m = SYNC_RE.findall(txt)
            if not m or max(int(x) for x in m) < n:
                probs.append(f"{f} 还没同步到闸门 {n}：核对结论并局部更新「同步至闸门：{n}」；实质内容变化才升版本号")

    # 有人值守：本阶段代定的事项必须写进本阶段的验收决策，让用户随验收一起确认
    if st.get("mode") != "unattended":
        topics = pending_topics(root, covered)
        gate_txt = json.dumps([d for d in ds if d.get("type") == "gate"], ensure_ascii=False, default=str)
        missing = [t for t in topics if t not in gate_txt]
        if missing:
            probs.append(f"本阶段有智能体代定的事项没有写进验收决策（context 或 media 里要逐条列出）：{missing}")

    # 决策
    pending = [d["id"] for d in ds if not d["_answer"]]
    if pending:
        probs.append("决策未作答：" + ", ".join(pending))
    gates = [d for d in ds if d.get("type") == "gate"]
    if not gates:
        probs.append(f"本阶段没有 gate 类型的验收决策（需建一个 stage={n}, type=gate 的决策）")
    elif not any(user_ok(g["_answer"], st) and "approve" in (g["_answer"].get("choice") or []) for g in gates):
        probs.append("验收决策尚未被用户批准（approve）")
    for d in ds:
        errs = validate_question(d)
        if errs:
            probs.append(f"{d['id']} 不合规范（决策页不会展示它）：" + "；".join(errs))
        a = d["_answer"]
        if a and a.get("answered_by") == "agent" and st.get("mode") != "unattended":
            probs.append(f"{d['id']} 由智能体代答，但当前是有人值守模式")
        if a and a.get("via") == "chat" and not a.get("quote"):
            probs.append(f"{d['id']} 通过对话作答但没有记录用户原话（quote）")
    import waitlib
    unacked = [a["id"] for a in waitlib.new_answers(root)]
    if unacked:
        probs.append("答案尚未落实并确认（ack）：" + ", ".join(unacked))
    return probs


def next_stage(st, n):
    seq = st["sequence"]
    i = seq.index(n)
    return seq[i + 1] if i + 1 < len(seq) else None


def workflow_next(root, snapshot=None):
    """所有入口共用的流程判定；查询不消费答案，也不改变设计阶段。"""
    import waitlib
    st = load_state(root)
    cur = st["stage"]
    meta = P.phase_info(root) or {}
    out = {"phase": st.get("phase") or meta.get("id"), "phase_name": meta.get("name") or "",
           "stage": cur, "stage_name": STAGES[cur]["name"], "new": [], "open": [],
           "queued": [], "blockers": [], "gate_ready": False, "completed": False,
           "delivery_mode": (load_scope(root) or {}).get("delivery_mode"),
           "delivery_boundary": st.get("delivery_boundary")}

    def result(status, action, hint):
        return {**out, "status": status, "action": action, "next": hint}

    if waitlib.paused(root):
        return result("paused", "resume", "用户已明确暂停。保留当前进度；用户恢复后运行 decide_server.py resume，再读取 next。")
    stopped = waitlib.load_json(P.runtime(root, ".flow-blocked.json"), {}) or {}
    if stopped.get("stage") == cur:
        out["blockers"] = [stopped["reason"]]
        out["blocked"] = stopped
        return result("blocked", "resolve", f"流程受阻：{stopped['reason']}；已尝试：{stopped['tried']}；需要：{stopped['needs']}。解决后运行 gate.py unblock --reason …。")
    out["new"] = waitlib.new_answers(root)
    out["completed"] = bool(st["sequence"]) and set(st["sequence"]).issubset(st["passed"]) and not out["new"]
    if out["completed"]:
        boundary = DL.check(root, st, load_scope(root), decisions(root))
        if boundary:
            out.update(completed=False, blockers=boundary)
            return result("working", "repair", "交付边界检查未通过：" + "；".join(boundary))
        return result("completed", "handoff", "整个设计流程已完成。输出最终交付与验证结果，不再 pass 或等待。")
    v = snapshot if snapshot is not None else waitlib.view(root)
    out.update(open=[q["id"] for q in v["open"]], queued=[q["id"] for q in v["queued"]])
    try:
        out["blockers"] = blockers(root, st, cur)
    except (ValueError, TypeError, KeyError, OSError) as e:
        out["blockers"] = [f"阶段产物校验失败（{type(e).__name__}）：{e}"]
        return result("working", "repair", "修复阶段产物格式或读取错误后重新查询 next；不要因工具异常结束流程。" + out["blockers"][0])
    out["blockers"] += [f"决策 {q['id']} 无法展示：{q['_error']}" for q in v.get("broken", [])]
    out["gate_ready"] = not out["blockers"]
    if out["new"]:
        return result("processing", "apply-answers", "先落实 new 中的完整答案、备注和数值；逐项执行 decide_server.py ack ID --ts 原版本时间戳，再查询 next。重复交付时先核对已做修改，避免重复执行。")
    skip_ok = any(d.get("role") == "skip" and d.get("skip_stage") == cur and user_ok(d["_answer"], st)
                  and "approve" in (d["_answer"].get("choice") or []) for d in decisions(root, stages_of(st, cur)))
    if cur in st["optional"] and skip_ok and not (cur == 5 and (load_scope(root) or {}).get("user_customizable")):
        return result("gate-ready", "skip", f"用户已批准跳过阶段 {cur}。运行 gate.py skip {cur} --reason …，记录代定取值并直接开始轨道下一阶段。")
    if out["gate_ready"]:
        nx = next_stage(plan(load_scope(root)) if cur == 0 else st, cur)
        hint = f"运行 gate.py pass {cur}；" + (f"随后 gate.py check {nx}，直接开始阶段 {nx}，不等待用户说继续。" if nx is not None else "随后输出最终交付。")
        return result("gate-ready", "pass", hint)
    if v["open"]:
        if st["mode"] == "unattended" and cur not in (0, 1):
            return result("working", "decide", "按无人值守协议落实当前决策、登记答案并确认，再查询 next。")
        out["decision_notice"] = waitlib.decision_notice(root, v)
        return result("waiting", "wait", "先在用户可见的对话消息中输出 decision_notice.text，确认实际入口可用并展示当前待决定项，再按已验证的宿主能力选择持续或短段等待；工具日志不等于已通知用户。")
    return result("working", "work", "继续当前阶段工作，修复无效或依赖未满足的决策；需要用户拍板时创建决策。还差：" + "；".join(out["blockers"][:6]))


def cmd_next(a):
    import waitlib
    root = os.path.abspath(a.root)
    flow = workflow_next(root)
    # 只有命令实际交付完整答案时才记录交付；网页状态查询不算交付。
    if flow["new"]:
        flow = waitlib.deliver(root, flow["new"])
    if a.json:
        print(json.dumps({k: v for k, v in flow.items() if k != "new_text"}, ensure_ascii=False))
    else:
        phase = f"{flow.get('phase')} {flow.get('phase_name') or ''}".strip()
        print(f"设计期：{phase or '单期'}｜流程状态：{flow['status']}｜当前阶段：{flow['stage']}")
        if flow.get("new_text"):
            print(flow["new_text"])
        if flow.get("decision_notice"):
            print(flow["decision_notice"]["text"])
        print(flow["next"])


def cmd_context(a):
    """恢复只读概览有界；详情显式分页，不交付或确认答案。"""
    if a.offset < 0 or (a.offset and not a.section):
        sys.exit("[gate] --offset 必须非负，且非零时需要 --section 指定详情")
    root = os.path.abspath(a.root)
    st = load_state(root)
    flow = workflow_next(root)
    covered = stages_of(st, st["stage"])
    skill = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    records = [P.PROGRESS, P.SCOPE, f"{P.BRIEF}/constraints.yaml", P.REFS,
               f"{P.BRIEF}/brief.md", f"{P.BRIEF}/traits.md", P.NOTES, f"{P.BRIEF}/content.yaml"]
    inherited = []
    meta = P.phase_info(root)
    if meta:
        container = os.path.dirname(os.path.dirname(root))
        for rel in meta.get("inherits") or []:
            try:
                path = P.inheritance_path(container, rel)
                inherited.append({"path": path, "exists": os.path.exists(path)})
            except ValueError as e:
                inherited.append({"path": rel, "exists": False, "error": str(e)})
    current = []
    for d in decisions(root, covered):
        entry = {"id": d["id"], "question": os.path.join(d["_dir"], "question.json")}
        if d["_answer"]:
            entry.update(answer=os.path.join(d["_dir"], "answer.json"),
                         ts=d["_answer"].get("ts"))
        current.append(entry)
    sections = {
        "decisions": current,
        "unacked": [{"id": x["id"], "ts": x.get("ts")} for x in flow["new"]],
        "blockers": flow["blockers"], "open": flow["open"], "queued": flow["queued"], "inherited": inherited,
    }
    if a.section:
        items = sections[a.section]
        end = a.offset + a.limit
        print(json.dumps({"root": root, "stage": st["stage"], "section": a.section,
                          "total": len(items), "offset": a.offset, "items": items[a.offset:end],
                          "next_offset": end if end < len(items) else None}, ensure_ascii=False, indent=2))
        return

    # 预览只用于定位。超出部分有显式标记，不能当作已读完整要求或答案。
    def preview(value, limit):
        return {"text": value[:limit], "truncated": len(value) > limit}

    checkpoint = {"path": os.path.join(root, P.PROGRESS), "status": "missing"}
    if os.path.exists(checkpoint["path"]):
        with open(checkpoint["path"], encoding="utf-8") as f:
            text = f.read(3001)
        match = re.search(r"对应阶段\s*[:：]\s*(\d+)", text)
        stage_matches = bool(match and int(match[1]) == st["stage"])
        checkpoint.update(preview(text, 3000), stage_matches=stage_matches,
                          status="available" if stage_matches and "待填写" not in text and "待核对" not in text else "needs-review")
    groups = {}
    for item in flow["blockers"]:
        kind = ("方案检查" if item.startswith("方案 ") else "产物缺失" if item.startswith("缺少") else
                "答案未确认" if item.startswith("答案尚未") else "决策与验收" if "决策" in item else "其他检查")
        if kind not in groups:
            groups[kind] = {"category": kind, "count": 0, "example": preview(item, 180)}
        groups[kind]["count"] += 1
    hints = {"processing": "运行 next --json 读取完整未确认答案，核对落实位置后精确 ack。",
             "waiting": "核对实际决策入口，在当前对话通知地址和待答项，再等待。",
             "working": "按分组阻塞和当前工作记录选一个小步骤；缺口明确后才查详情。",
             "gate-ready": "按 next --json 的 action 过闸并开始实际后继阶段。",
             "paused": "用户明确恢复后 resume；不凭工作记录自行解除暂停。",
             "blocked": "用 next --json 读取已登记的阻塞、尝试和所需操作。",
             "completed": "核对交付产物后输出最终交付，不重启设计流程。"}
    out = {
        "phase": st.get("phase"), "phase_name": (P.phase_info(root) or {}).get("name"),
        "root": root,
        "delivery_mode": flow["delivery_mode"], "delivery_boundary": flow["delivery_boundary"],
        "flow": {**{k: flow[k] for k in ("status", "action", "stage", "stage_name")},
                 "next": hints[flow["status"]],
                 "blockers": [preview(x, 180) for x in flow["blockers"][:a.limit]],
                 "open": flow["open"][:a.limit], "queued": flow["queued"][:a.limit]},
        "sequence": st["sequence"], "passed": st["passed"],
        "checkpoint": checkpoint,
        "recovery_action": "rebuild-checkpoint" if checkpoint["status"] != "available" else "verify-current-task",
        "inherited": inherited[:a.limit],
        "records": [{"path": os.path.join(root, rel), "exists": os.path.exists(os.path.join(root, rel)),
                     "bytes": os.path.getsize(os.path.join(root, rel)) if os.path.exists(os.path.join(root, rel)) else None}
                    for rel in records],
        "stage_guides": [os.path.join(skill, "references", f"stage-{n}.md") for n in sorted(covered)],
        "artifact_patterns": [os.path.join(root, rel) for n in sorted(covered)
                              for rel in STAGES[n]["files"] + STAGES[n]["globs"]],
        "decisions": current[:a.limit], "unacked": sections["unacked"][:a.limit],
        "blocker_groups": list(groups.values()),
        "pagination": {key: {"total": len(items), "next_offset": a.limit if len(items) > a.limit else None}
                       for key, items in sections.items()},
        "history_index": os.path.join(root, P.SUMMARY, "README.md"),
        "recovery_guide": os.path.join(skill, "references", "continuity.md"),
        "hint": "先核对当前任务、有效约束、直接依赖和下一步；缺工作记录时优先按事实补建。定位后立即做一个小步骤，不扫描全部历史或脚本源码。预览和索引不代表完整阅读；详情按需用 context --json --section 名称 --offset N 分页。",
    }
    if a.compact:
        out = {
            "phase": out["phase"], "phase_name": out["phase_name"], "root": root,
            "flow": out["flow"], "checkpoint": {
                "path": checkpoint["path"], "status": checkpoint["status"],
                "stage_matches": checkpoint.get("stage_matches")},
            "recovery_action": out["recovery_action"],
            "inherited": inherited[:a.limit],
            "records": [x for x in out["records"] if not x["exists"] or x["bytes"] == 0],
            "stage_guides": out["stage_guides"], "pagination": out["pagination"],
            "hint": "compact 模式只保留恢复入口；按需运行 context --json 或 --section 读取详情。",
        }
    print(json.dumps(out, ensure_ascii=False, indent=2))


def cmd_block(a):
    import waitlib
    root = os.path.abspath(a.root)
    st = load_state(root)
    if not all(x.strip() for x in (a.reason, a.tried, a.needs)):
        sys.exit("[gate] 阻塞原因、已尝试措施和所需用户操作都不能为空")
    waitlib.save_runtime(root, ".flow-blocked.json", {"stage": st["stage"], "reason": a.reason,
                         "tried": a.tried, "needs": a.needs, "ts": now()})
    log(root, f"- {now()} | 流程受阻 | {a.reason} | 已尝试 {a.tried} | 需要 {a.needs}")
    print("[gate] 已记录真实阻塞；向用户报告具体所需操作，不要求空泛的继续指令。")


def cmd_unblock(a):
    root = os.path.abspath(a.root)
    p = P.runtime(root, ".flow-blocked.json")
    if os.path.exists(p):
        os.remove(p)
    log(root, f"- {now()} | 阻塞已解除 | {a.reason}")
    print("[gate] 阻塞已解除。立即查询 next 并接续当前流程。")


def cmd_init(a):
    root = os.path.abspath(a.root)
    if getattr(a, "phase", None):
        container = root
        if os.path.exists(os.path.join(container, P.STATE)):
            sys.exit("[gate] 当前 .taste-design/ 是单期布局；不能直接在其中创建多期。先保留现有项目，另建多期目录或先按文档迁移。")
        root = P.add_phase_record(container, a.phase, getattr(a, "name", None),
                                  getattr(a, "parent", None), getattr(a, "inherit", None))
    else:
        container = P.find_container(os.path.dirname(root)) if os.path.exists(root) else None
        if container and os.path.isdir(os.path.join(container, P.PHASES)) and P.phase_ids(container):
            sys.exit("[gate] 当前是多期项目，必须用 --phase ID 初始化或新增某一期")
    legacy = os.path.join(os.path.dirname(root), "design", "state.json")
    if os.path.exists(legacy) and not os.path.exists(os.path.join(root, P.STATE)):
        sys.exit("[gate] 发现旧版 design/ 目录。先运行 gate.py migrate 迁移到 .taste-design/，不要重新初始化。")
    for sub in P.MKDIRS:
        os.makedirs(os.path.join(root, sub), exist_ok=True)
    if not os.path.exists(os.path.join(root, ".gitignore")) or a.media:
        P.write_git_files(root, a.media or "ignore")
    p = os.path.join(root, P.STATE)
    if os.path.exists(p) and not a.force:
        print(f"[gate] 已存在 {p}，未改动（--force 可重置）")
        return
    st = {"stage": 0, "passed": [], "mode": a.mode, "channel": a.channel,
          "sequence": list(ALL), "merged": {}, "optional": [], "history": [{"ts": now(), "event": "init"}]}
    meta = P.phase_info(root)
    if meta:
        st["phase"] = meta["id"]
    save_state(root, st)
    DL.capture(root)
    progress = os.path.join(root, P.PROGRESS)
    if not os.path.exists(progress):
        shutil.copyfile(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                                     "templates", "progress.md"), progress)
    log(root, f"# 决策记录\n\n- {now()} | 初始化 | 模式 {a.mode} | 通道 {a.channel} | 素材策略 {P.load_config(root)['media']}")
    phase = f"（设计期 {st['phase']}）" if st.get("phase") else ""
    print(f"[gate] 已初始化 {root}{phase}，当前阶段 {name(0)}；media/ 的 git 策略：{P.load_config(root)['media']}")
    if not st.get("phase"):
        print("[gate] 单期项目已初始化。若后续需要 P1/P2/P3，请保留本期作为兼容单期，"
              "不要直接改写 record/state.json 冒充多期；另建多期项目并用 gate.py init --phase P1 开始。")


def cmd_phase(a):
    root = os.path.abspath(a.root)
    container = root if os.path.exists(os.path.join(root, P.PROJECT)) else P.find_container(root)
    if not container:
        container = root
    if a.action == "add":
        if os.path.exists(os.path.join(container, P.STATE)):
            sys.exit("[gate] 当前是单期布局，不能直接添加多期；请在新的多期 .taste-design/ 中创建。")
        try:
            phase_root = P.add_phase_record(container, a.id, a.name, a.parent, a.inherit)
        except ValueError as e:
            sys.exit(f"[gate] {e}")
        for sub in P.MKDIRS:
            os.makedirs(os.path.join(phase_root, sub), exist_ok=True)
        P.write_git_files(phase_root, a.media)
        st = {"stage": 0, "passed": [], "mode": a.mode, "channel": a.channel, "phase": a.id,
              "sequence": list(ALL), "merged": {}, "optional": [],
              "history": [{"ts": now(), "event": "init"}]}
        save_state(phase_root, st)
        DL.capture(phase_root)
        progress = os.path.join(phase_root, P.PROGRESS)
        if not os.path.exists(progress):
            shutil.copyfile(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                                         "templates", "progress.md"), progress)
        log(phase_root, f"# 决策记录\n\n- {now()} | 初始化设计期 {a.id} | 模式 {a.mode} | 通道 {a.channel}")
        print(f"[gate] 已新增设计期 {a.id}（{a.name or a.id}）→ {phase_root}")
        return
    project = P.load_project(container)
    rows = []
    for item in (project or {}).get("phases") or []:
        p = os.path.join(container, P.PHASES, item["id"])
        state_path = os.path.join(p, P.STATE)
        row = {"id": item["id"], "name": item.get("name", item["id"]),
               "parent_phase": item.get("parent_phase"), "inherits": item.get("inherits") or [],
               "root": p}
        if os.path.exists(state_path):
            st = json.load(open(state_path, encoding="utf-8"))
            row.update(stage=st.get("stage"), passed=st.get("passed") or [],
                       completed=bool(st.get("sequence")) and set(st.get("sequence")).issubset(st.get("passed") or []))
        rows.append(row)
    if a.json:
        print(json.dumps({"container": container, "phases": rows}, ensure_ascii=False, indent=2))
        return
    if not rows:
        print("[gate] 还没有设计期。运行 gate.py init --phase P1 --name 第一期")
        return
    print(f"多期项目：{container}")
    for r in rows:
        state = "已完成" if r.get("completed") else f"阶段 {r.get('stage', '?')}"
        dep = f"；父期 {r['parent_phase']}" if r.get("parent_phase") else ""
        print(f"  {r['id']}  {r['name']}  {state}{dep}")


def cmd_media(a):
    root = os.path.abspath(a.root)
    load_state(root)
    P.write_git_files(root, a.policy)
    log(root, f"- {now()} | 素材策略改为 {a.policy}")
    tips = {"ignore": "media/ 不再提交；已提交过的文件需要 git rm -r --cached .taste-design/media 才会从仓库移除。",
            "lfs": "media/ 将用 Git LFS 管理：先 git lfs install；已提交过的文件可用 git lfs migrate import 转换。",
            "commit": "media/ 将直接提交，注意仓库体积。"}
    print(f"[gate] 素材策略已改为 {a.policy}。{tips[a.policy]}")


def describe_plan(st):
    seq = " → ".join(str(s) for s in st["sequence"])
    extra = []
    for k, v in st["merged"].items():
        extra.append(f"阶段 {k}（{STAGES[k]['name']}）并入闸门 {v}")
    for s in ALL:
        if s not in st["sequence"] and s not in st["merged"]:
            extra.append(f"阶段 {s}（{STAGES[s]['name']}）省略")
    for s in st["optional"]:
        extra.append(f"阶段 {s}（{STAGES[s]['name']}）可跳过，跳过时进入待复核清单")
    return seq + ("；" + "；".join(extra) if extra else "")


def cmd_status(a):
    root = os.path.abspath(a.root)
    st = load_state(root)
    n = st["stage"]
    sc = load_scope(root)
    meta = P.phase_info(root) or {}
    phase = f"设计期：{meta.get('id')} {meta.get('name') or ''}".strip() + "   " if meta else ""
    print(f"{phase}当前阶段：{name(n)}   模式：{st['mode']}   通道：{st['channel']}   轨道：{(sc or {}).get('track', '未定')}")
    print(f"阶段序列：{describe_plan(st)}")
    print(f"交付边界：{(sc or {}).get('delivery_mode', '旧版未记录 / 待用户确认')}")
    print(f"已通过：{st['passed'] or '无'}   待复核事项：{pending_count(root)}")
    flow = workflow_next(root)
    print(f"流程状态：{flow['status']}｜下一步：{flow['next']}")
    if flow["status"] in ("completed", "paused", "blocked"):
        return
    for d in decisions(root, stages_of(st, n)):
        s = "已答" if d["_answer"] else "待答"
        print(f"  [{s}] {d['id']} ({d.get('type')}{'/' + d['role'] if d.get('role') else ''}) {d.get('title', '')}")
    probs = flow["blockers"]
    if probs:
        print("距离通过闸门还差：")
        for p in probs:
            print("  - " + p)
    else:
        print(f"闸门 {n} 条件已满足，可运行：gate.py pass {n}")


def cmd_check(a):
    root = os.path.abspath(a.root)
    st = load_state(root)
    n, cur = a.stage, st["stage"]
    sc = load_scope(root)
    if cur != 0 or (sc or {}).get("delivery_mode") or st.get("delivery_boundary"):
        probs = DL.check(root, st, sc, decisions(root))
        if probs:
            sys.exit("[gate] 交付边界检查未通过：" + "；".join(probs))
    if n == cur or st["merged"].get(n) == cur:
        print(f"[gate] 允许：阶段 {name(n)}" + (f"（并入闸门 {cur}）" if n != cur else ""))
        return
    if n not in st["sequence"] and n not in st["merged"]:
        print(f"[gate] 拒绝：阶段 {name(n)} 在本项目的轨道中被省略。需要它就先和用户确认，再 gate.py rollback 0 重新定范围。")
        sys.exit(1)
    if st["sequence"].index(st["merged"].get(n, n)) > st["sequence"].index(cur):
        print(f"[gate] 拒绝：当前在阶段 {name(cur)}，闸门 {cur} 未通过前不得开始阶段 {n}。运行 gate.py status 查看还差什么。")
        sys.exit(1)
    print(f"[gate] 拒绝：阶段 {n} 已通过。修改它属于变更，先 gate.py rollback {n} --reason …")
    sys.exit(1)


def cmd_pass(a):
    root = os.path.abspath(a.root)
    st = load_state(root)
    n = a.stage
    if set(st["sequence"]).issubset(st["passed"]):
        probs = DL.check(root, st, load_scope(root), decisions(root))
        if probs:
            sys.exit("[gate] 交付边界检查未通过：" + "；".join(probs))
        print("[gate] 全部阶段已完成，无需重复 pass。")
        return
    if n != st["stage"]:
        sys.exit(f"[gate] 拒绝：只能通过当前阶段 {st['stage']} 的闸门")
    flow = workflow_next(root)
    if flow["status"] in ("paused", "blocked"):
        sys.exit("[gate] " + flow["next"])
    probs = flow["blockers"]
    if probs:
        print(f"[gate] 闸门 {n} 未通过：")
        for p in probs:
            print("  - " + p)
        sys.exit(1)
    if n == 0:
        st["delivery_boundary"] = DL.decision(decisions(root))
        st.update(plan(load_scope(root)))
        print(f"[gate] 本项目的阶段序列：{describe_plan(st)}")
        start = (load_scope(root) or {}).get("start_stage")
        if start:
            print(f"[gate] 本期从阶段 {start} 开始；阶段 0 仅用于登记范围与接续依据。"
                  "被跳过的旧期验收不能静默充作本期验收，先核对用户批准的继承来源。")
        print("[gate] 请把这条序列原样告诉用户（走的是哪条轨道、哪些闸门被合并或省略）。")
    snap = snapshot(root, n)
    if snap:
        print(f"[gate] 已快照源码 {snap} → {P.DIRNAME}/{P.SNAPSHOTS}/gate-{n}/")
    st["passed"].append(n)
    st["history"].append({"ts": now(), "event": f"pass {n}"})
    nx = next_stage(st, n)
    if nx is not None:
        st["stage"] = nx
    save_state(root, st)
    log(root, f"- {now()} | 闸门 {n} 通过 | {STAGES[n]['name']}")
    print(f"[gate] 闸门 {n} 通过。" + (f"进入阶段 {name(nx)}" if nx is not None else "全部阶段完成。"))


def cmd_skip(a):
    root = os.path.abspath(a.root)
    st = load_state(root)
    n = a.stage
    probs = DL.check(root, st, load_scope(root), decisions(root))
    if probs:
        sys.exit("[gate] 交付边界检查未通过：" + "；".join(probs))
    if n == 5 and (load_scope(root) or {}).get("user_customizable"):
        sys.exit("[gate] 拒绝：外观开放给最终用户时不能跳过阶段 5，设置项的维度、预设和令牌要在这里定稿")
    if n != st["stage"] or n not in st["optional"]:
        sys.exit(f"[gate] 拒绝：只能跳过当前阶段，且该阶段在本轨道中必须是可选的（可选：{st['optional']}）")
    flow = workflow_next(root)
    if flow["status"] in ("paused", "blocked", "processing"):
        sys.exit("[gate] " + flow["next"])
    if st.get("mode") != "unattended":
        ok = any(d.get("role") == "skip" and d.get("skip_stage") == n and user_ok(d["_answer"], st)
                 and "approve" in (d["_answer"].get("choice") or []) for d in decisions(root, stages_of(st, n)))
        if not ok:
            sys.exit(f"[gate] 拒绝：有人值守时跳过阶段 {n} 需要用户单独点头。建一个 role=skip、skip_stage={n} 的 gate 类型决策，"
                     "context 写明跳过后由谁、按什么定这些取值；用户 approve 后再 skip。")
    pending_add(root, n, f"跳过{STAGES[n]['name']}", "相关取值由智能体决定", a.reason)
    log(root, f"- {now()} | 跳过阶段 {n} {STAGES[n]['name']} | 原因：{a.reason} | decided_by: agent")
    st["passed"].append(n)
    st["history"].append({"ts": now(), "event": f"skip {n}", "reason": a.reason})
    nx = next_stage(st, n)
    st["stage"] = nx if nx is not None else n
    save_state(root, st)
    print(f"[gate] 已跳过阶段 {name(n)}，已写入 pending-review.md。进入阶段 {name(st['stage'])}")


def cmd_assume(a):
    root = os.path.abspath(a.root)
    st = load_state(root)
    pending_add(root, st["stage"], a.topic, a.choice, a.why)
    log(root, f"- {now()} | 阶段{st['stage']} | 代定：{a.topic} = {a.choice} | 理由：{a.why} | decided_by: agent")
    print(f"[gate] 已记入待复核清单（共 {pending_count(root)} 项）")


def cmd_add_page(a):
    """范围确定后新增页面：只让这个页面补走流程，其他页面不回退。"""
    root = os.path.abspath(a.root)
    st = load_state(root)
    sc = load_scope(root)
    if sc is None or 0 not in st["passed"]:
        sys.exit("[gate] 闸门 0 还没通过，直接在 scope.json 的 pages 里加就行")
    names = [p if isinstance(p, str) else p.get("name") for p in sc.get("pages") or []]
    if a.name in names:
        sc["pages"] = [({"name": a.name, "in_scope": True} if (p == a.name or (isinstance(p, dict) and p.get("name") == a.name)) else p)
                       for p in sc["pages"]]
    else:
        sc.setdefault("pages", []).append(a.name)
    changed_scope = False
    if sc.get("scope") == "single":
        sc["scope"] = "sample-then-rollout"
        changed_scope = True
    with open(os.path.join(root, P.SCOPE), "w", encoding="utf-8") as f:
        json.dump(sc, f, ensure_ascii=False, indent=2)
    if 7 not in st["sequence"]:
        seq = st["sequence"]
        seq.insert(seq.index(8) if 8 in seq else len(seq), 7)
    rp = os.path.join(root, "work", "rollout", "pages.json")
    os.makedirs(os.path.dirname(rp), exist_ok=True)
    pages = []
    if os.path.exists(rp):
        with open(rp, encoding="utf-8") as f:
            pages = json.load(f)
    else:
        # 第一次铺开：已有的页面先登记进来（单页项目里那一页就是已完成的样张页）
        for nm in in_scope_pages(sc):
            if nm != a.name:
                pages.append({"name": nm, "status": "done" if changed_scope else "todo",
                              "note": "样张页" if changed_scope else ""})
    needs = [x for x, cond in (("baseline", sc.get("mode") == "redesign"),
                               ("wireframe", sc.get("layout_freedom") != "keep"),
                               ("states", sc.get("product_type") == "app")) if cond]
    if not any(p.get("name") == a.name for p in pages):
        pages.append({"name": a.name, "status": "todo", "added": now(), "reason": a.reason, "needs": needs})
        with open(rp, "w", encoding="utf-8") as f:
            json.dump(pages, f, ensure_ascii=False, indent=2)
    st["history"].append({"ts": now(), "event": f"add-page {a.name}", "reason": a.reason})
    save_state(root, st)
    log(root, f"- {now()} | 新增页面 {a.name} | 原因：{a.reason}" + ("｜范围由 single 改为 sample-then-rollout" if changed_scope else ""))
    seq = st["sequence"]
    if seq.index(st["stage"]) > seq.index(7):
        cmd_rollback(argparse.Namespace(root=a.root, stage=7, reason=f"新增页面「{a.name}」，只补做该页"))
    print(f"[gate] 已新增页面「{a.name}」，记入 work/rollout/pages.json（需要补：{'、'.join(needs) or '无'}）。"
          "它在阶段 7 全站铺开里补走流程，其他页面不回退。")


def cmd_rollback(a):
    root = os.path.abspath(a.root)
    st = load_state(root)
    n = a.stage
    if n not in st["sequence"] or st["sequence"].index(n) >= st["sequence"].index(st["stage"]):
        sys.exit("[gate] 只能回退到序列中更早的阶段")
    idx = st["sequence"].index(n)
    later = set(st["sequence"][idx:]) | {k for k, v in st["merged"].items() if v in st["sequence"][idx:]}
    st["stage"] = n
    st["passed"] = [p for p in st["passed"] if p not in later]
    stamp = datetime.datetime.now().strftime("%Y%m%d%H%M%S")
    for d in decisions(root):
        if (d.get("type") == "gate" or (n == 0 and d.get("role") == "delivery-boundary")) and d.get("stage") in later and d["_answer"]:
            os.rename(os.path.join(d["_dir"], "answer.json"), os.path.join(d["_dir"], f"answer.superseded-{stamp}.json"))
    if n == 0:
        st.update({"sequence": list(ALL), "merged": {}, "optional": []})
    st["history"].append({"ts": now(), "event": f"rollback {n}", "reason": a.reason})
    save_state(root, st)
    log(root, f"- {now()} | 回退到阶段 {n} | 原因：{a.reason}")
    print(f"[gate] 已回退到阶段 {name(n)}。该阶段及之后的验收决策已失效，需要用户重新作答。")


def cmd_channel(a):
    root = os.path.abspath(a.root)
    st = load_state(root)
    st["channel"] = a.channel
    st["history"].append({"ts": now(), "event": f"channel {a.channel}", "reason": a.reason})
    save_state(root, st)
    log(root, f"- {now()} | 交互通道改为 {a.channel} | 原因：{a.reason}")
    print(f"[gate] 交互通道已改为 {a.channel}")


def cmd_record(a):
    root = os.path.abspath(a.root)
    st = load_state(root)
    d = P.decision_dir(root, a.id)
    if not os.path.exists(os.path.join(d, "question.json")):
        sys.exit(f"[gate] 找不到决策 {a.id}")
    if os.path.exists(os.path.join(d, "answer.json")):
        sys.exit(f"[gate] {a.id} 已作答")
    with open(os.path.join(d, "question.json"), encoding="utf-8") as f:
        qj = json.load(f)
    post_delivery_docs = (qj.get("role") == "documentation-sync" and st["stage"] == 9
                          and set(st["sequence"]).issubset(st["passed"]) and a.by == "user" and a.quote)
    if st["channel"] == "web" and a.via == "chat" and not post_delivery_docs:
        sys.exit("[gate] 拒绝：当前通道是 web，决策必须在网页上作答。若网页确实无法打开，先运行 gate.py channel inline|static --reason 原因 并告诉用户。")
    if qj.get("role") in ("delivery-boundary", "documentation-sync") and a.by != "user":
        sys.exit("[gate] 交付边界和文档同步必须由用户确认，不能由智能体代答")
    if a.by == "user" and a.via == "chat" and not a.quote:
        sys.exit("[gate] 对话作答必须用 --quote 记录用户原话")
    if a.by == "agent" and st["mode"] != "unattended":
        sys.exit("[gate] 有人值守模式下智能体不得代答决策；次要事项请用 gate.py assume")
    choice = [c.strip() for c in a.choice.split(",") if c.strip()]
    if qj.get("role") in ("delivery-boundary", "documentation-sync") and (len(choice) != 1 or choice[0] not in {o["id"] for o in qj.get("options") or []}):
        sys.exit("[gate] 请明确选择一个交付边界或文档同步选项")
    setting = None
    if a.setting:
        with open(os.path.join(d, "question.json"), encoding="utf-8") as f:
            qj = json.load(f)
        vals = [c.strip() for c in a.setting.split(",") if c.strip()]
        sc = load_scope(root) or {}
        if not qj.get("allow_setting"):
            sys.exit(f"[gate] {a.id} 不允许做成设置项（question.json 没有 allow_setting）")
        if not sc.get("user_customizable"):
            sys.exit("[gate] 阶段 0 定为外观不开放给最终用户；要做成设置项先和用户确认，再 gate.py rollback 0 修改范围")
        if not 2 <= len(vals) <= 4 or choice[:1] == [] or choice[0] not in vals:
            sys.exit("[gate] --setting 需要 2–4 个选项，且 --choice 填其中一个作为默认值")
        setting = {"axis": qj.get("setting_axis"), "values": vals, "default": choice[0]}
        choice = choice[:1]
    ans = {"id": a.id, "choice": choice, "setting": setting,
           "note": a.note or "", "answered_by": a.by, "via": a.via, "quote": a.quote or "", "ts": now()}
    with open(os.path.join(d, "answer.json"), "w", encoding="utf-8") as f:
        json.dump(ans, f, ensure_ascii=False, indent=2)
    log(root, f"- {ans['ts']} | {a.id} | 选择 {','.join(ans['choice'])} | 备注 {ans['note']} | {a.by}({a.via})")
    SUM.write(root, a.id)
    if a.by == "agent":
        pending_add(root, st["stage"], f"决策 {a.id}", ",".join(ans["choice"]), a.note or "无人值守代答")
    print(f"[gate] 已登记 {a.id}")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--root", default=None, help=f"设计目录，默认向上查找 {P.DIRNAME}/")
    ap.add_argument("--phase", default=None, help="多期项目的设计期 ID；也可设 TASTE_DESIGN_PHASE")
    sp = ap.add_subparsers(dest="cmd", required=True)
    p = sp.add_parser("init"); p.add_argument("--phase", default=argparse.SUPPRESS, help="多期项目中要初始化的设计期 ID")
    p.add_argument("--mode", default="attended", choices=["attended", "unattended"])
    p.add_argument("--channel", default="web", choices=["web", "inline", "static"]); p.add_argument("--force", action="store_true")
    p.add_argument("--media", choices=P.MEDIA_POLICIES, help="media/ 的 git 策略，默认 ignore")
    p.add_argument("--name", help="多期项目中的期名称")
    p.add_argument("--parent", help="父期 ID；只表示来源，不自动继承验收状态")
    p.add_argument("--inherit", action="append", help="跨期稳定的相对路径，可重复")
    p.set_defaults(f=cmd_init)
    p = sp.add_parser("phase"); p.add_argument("action", choices=["add", "list"]); p.add_argument("id", nargs="?")
    p.add_argument("--name"); p.add_argument("--parent"); p.add_argument("--inherit", action="append")
    p.add_argument("--media", default="ignore", choices=P.MEDIA_POLICIES)
    p.add_argument("--mode", default="attended", choices=["attended", "unattended"])
    p.add_argument("--channel", default="web", choices=["web", "inline", "static"])
    p.add_argument("--json", action="store_true"); p.set_defaults(f=cmd_phase)
    p = sp.add_parser("media"); p.add_argument("policy", choices=P.MEDIA_POLICIES); p.set_defaults(f=cmd_media)
    p = sp.add_parser("migrate"); p.add_argument("--from", dest="src", default="design"); p.add_argument("--dry-run", action="store_true")
    p.set_defaults(f=lambda a: __import__("migrate").run(a))
    sp.add_parser("status").set_defaults(f=cmd_status)
    p = sp.add_parser("context"); p.add_argument("--json", action="store_true", required=True)
    p.add_argument("--section", choices=["decisions", "unacked", "blockers", "open", "queued", "inherited"])
    p.add_argument("--offset", type=int, default=0); p.add_argument("--limit", type=int, choices=range(1, 21), default=5)
    p.add_argument("--compact", action="store_true", help="仅输出恢复入口；省略重复的完整状态与文件列表")
    p.set_defaults(f=cmd_context)
    p = sp.add_parser("next"); p.add_argument("--json", action="store_true"); p.set_defaults(f=cmd_next)
    p = sp.add_parser("block"); p.add_argument("--reason", required=True); p.add_argument("--tried", required=True)
    p.add_argument("--needs", required=True); p.set_defaults(f=cmd_block)
    p = sp.add_parser("unblock"); p.add_argument("--reason", required=True); p.set_defaults(f=cmd_unblock)
    for nm, fn in [("check", cmd_check), ("pass", cmd_pass)]:
        p = sp.add_parser(nm); p.add_argument("stage", type=int, choices=ALL); p.set_defaults(f=fn)
    p = sp.add_parser("skip"); p.add_argument("stage", type=int, choices=ALL); p.add_argument("--reason", required=True); p.set_defaults(f=cmd_skip)
    p = sp.add_parser("assume"); p.add_argument("--topic", required=True); p.add_argument("--choice", required=True)
    p.add_argument("--why", required=True); p.set_defaults(f=cmd_assume)
    p = sp.add_parser("add-page"); p.add_argument("name"); p.add_argument("--reason", required=True); p.set_defaults(f=cmd_add_page)
    p = sp.add_parser("rollback"); p.add_argument("stage", type=int, choices=ALL); p.add_argument("--reason", required=True); p.set_defaults(f=cmd_rollback)
    p = sp.add_parser("channel"); p.add_argument("channel", choices=["web", "inline", "static"]); p.add_argument("--reason", required=True); p.set_defaults(f=cmd_channel)
    p = sp.add_parser("record"); p.add_argument("id"); p.add_argument("--choice", required=True); p.add_argument("--note")
    p.add_argument("--via", default="chat", choices=["chat", "native"]); p.add_argument("--quote")
    p.add_argument("--by", default="user", choices=["user", "agent"])
    p.add_argument("--setting", help="做成设置项时保留的选项，逗号分隔；--choice 为默认值"); p.set_defaults(f=cmd_record)
    a = ap.parse_args()
    a.phase = a.phase or os.environ.get("TASTE_DESIGN_PHASE")
    try:
        a.root = P.resolve_root(a.root, a.phase, creating=a.cmd in ("init", "phase"))
        a.f(a)
    except ValueError as e:
        sys.exit(f"[gate] {e}")


if __name__ == "__main__":
    main()
