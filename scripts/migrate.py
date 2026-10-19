"""把旧版布局（项目下的 design/ 目录）迁移到 .taste-design/ 的四区布局。由 `gate.py migrate` 调用。

做的事：
  1. 按映射表把文件移到 record/ work/ media/ cache/；运行时文件直接丢弃。
  2. 改写每个 question.json 里的 media.src / playground：旧的相对路径换成新位置。
  3. 尽力改写 work/ 下 HTML 里引用素材的相对路径（../inbox/ → ../../media/inbox/ 等），并报告改了多少处。
  4. 旧的 dist/DESIGN.md、dist/HANDOFF.md 搬到 work/handoff/（dist/ 里的其他文件不动）。
  5. 生成 .gitignore / .gitattributes / README.md 和全部决策摘要卡。
旧目录迁移完后为空才删除；不为空就保留并列出剩下的文件。--dry-run 只打印计划。
"""
import glob, json, os, re, shutil, sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import paths as P  # noqa: E402

RUNTIME_FILES = {".agent-seen.json", ".agent-waiting", ".paused", ".server.json", ".hook-noserver", ".gitignore"}


def map_path(old_rel):
    """旧 design/ 下的相对路径 → 新 .taste-design/ 下的相对路径；None 表示丢弃。"""
    r = old_rel.replace(os.sep, "/")
    name = os.path.basename(r)
    if name in RUNTIME_FILES and "/" not in r:
        return None
    m = re.match(r"decisions/([^/]+)/samples/(.+)$", r)
    if m:
        return f"{P.SAMPLES}/{m.group(1)}/{m.group(2)}"
    m = re.match(r"decisions/([^/]+)/(question\.json|answer(\.superseded-[^/]+)?\.json)$", r)
    if m:
        return f"{P.DECISIONS}/{m.group(1)}/{m.group(2)}"
    m = re.match(r"decisions/([^/]+)/(.+)$", r)             # 决策目录里的其他文件当作样例
    if m and m.group(1) != "index.html":
        return f"{P.SAMPLES}/{m.group(1)}/{m.group(2)}"
    if r == "decisions/index.html":
        return None                                          # 旧静态导出页，重新 export 即可
    table = [
        ("state.json", P.STATE), ("scope.json", P.SCOPE), ("decisions.md", P.LOG),
        ("pending-review.md", P.PENDING), ("changelog.md", P.CHANGELOG),
        ("inbox/refs.yaml", P.REFS), ("inbox/notes.md", P.NOTES),
    ]
    for a, b in table:
        if r == a:
            return b
    prefixes = [
        ("brief/keyframes/", P.KEYFRAMES + "/"), ("brief/", P.BRIEF + "/"),
        ("inbox/", P.INBOX + "/"), ("baseline/", P.BASELINE + "/"),
        ("wireframe/", "work/wireframe/"), ("variants/", "work/variants/"), ("proto/", "work/proto/"),
        ("playgrounds/", "work/playgrounds/"),
        ("assets/benchmark/", P.ASSET_MEDIA + "/benchmark/"), ("assets/derived/", P.ASSET_MEDIA + "/derived/"),
        ("assets/", "work/assets/"),
        ("rollout/shots/", P.SHOTS + "/rollout/"), ("rollout/", "work/rollout/"),
        ("qa/", "work/qa/"), ("snapshots/", P.SNAPSHOTS + "/"),
    ]
    if r == "tokens.css":
        return "work/tokens.css"
    for a, b in prefixes:
        if r.startswith(a):
            rest = r[len(a):]
            if b.startswith("work/") and re.search(r"\.(png|jpe?g|gif|webp|mp4|webm|mov)$", rest, re.I):
                zone = b.split("/")[1]                       # work 里的图片 → media/shots/<区>/
                return f"{P.SHOTS}/{zone}/{rest}"
            return b + rest
    return f"cache/legacy/{r}"                               # 未知文件先放 cache/legacy，交给用户判断


def rewrite_src(did, src, old_root):
    if src.startswith(("http://", "https://", "data:")):
        return src
    path, frag = src, ""
    for sep in ("#", "?"):
        if sep in path:
            path, rest = path.split(sep, 1)
            frag = sep + rest
            break
    old_rel = path[2:] if path.startswith("@/") else os.path.normpath(os.path.join("decisions", did, path)).replace(os.sep, "/")
    new_rel = map_path(old_rel)
    if not new_rel:
        return src
    pre = f"{P.SAMPLES}/{did}/"
    return (new_rel[len(pre):] if new_rel.startswith(pre) else "@/" + new_rel) + frag


HTML_FIX = [
    (r"(\.\./)(inbox/)", r"../../media/inbox/"),
    (r"(\.\./)(baseline/)", r"../../media/baseline/"),
    (r"(\.\./)(assets/benchmark/)", r"../../media/assets/benchmark/"),
    (r"(\.\./)(assets/derived/)", r"../../media/assets/derived/"),
    (r"(\.\./)(brief/keyframes/)", r"../../media/keyframes/"),
]
ROLLOUT_FIX = [(r"(?<![./\w])(shots/)", r"../../media/shots/rollout/")]


def run(a):
    root = os.path.abspath(a.root)
    project = os.path.dirname(root)
    old = os.path.abspath(os.path.join(project, a.src))
    if not os.path.exists(os.path.join(old, "state.json")):
        sys.exit(f"[migrate] {old} 不是旧版设计目录（找不到 state.json）")
    if os.path.exists(os.path.join(root, P.STATE)):
        sys.exit(f"[migrate] {root} 已经初始化过，为避免覆盖，请先确认后手动处理")
    plan = []
    for dp, dn, fn in os.walk(old):
        for f in fn:
            full = os.path.join(dp, f)
            rel = os.path.relpath(full, old)
            plan.append((full, map_path(rel)))
    dist = os.path.join(project, "dist")
    for f in ("DESIGN.md", "HANDOFF.md"):
        if os.path.exists(os.path.join(dist, f)):
            plan.append((os.path.join(dist, f), f"work/handoff/{f}"))
    print(f"[migrate] {old} → {root}")
    for src, dst in plan:
        print(f"  {os.path.relpath(src, project)}  →  {dst or '（丢弃：运行时文件）'}")
    if a.dry_run:
        print("[migrate] --dry-run：没有改动任何文件")
        return
    for sub in P.MKDIRS:
        os.makedirs(os.path.join(root, sub), exist_ok=True)
    for src, dst in plan:
        if dst is None:
            os.remove(src)
            continue
        tgt = os.path.join(root, dst)
        os.makedirs(os.path.dirname(tgt), exist_ok=True)
        shutil.move(src, tgt)
    # 改写 question.json
    nq = 0
    for qp in glob.glob(os.path.join(root, P.DECISIONS, "*", "question.json")):
        did = os.path.basename(os.path.dirname(qp))
        with open(qp, encoding="utf-8") as f:
            q = json.load(f)
        for m in list(q.get("media") or []) + [m for o in q.get("options") or [] for m in o.get("media") or []]:
            if m.get("src"):
                m["src"] = rewrite_src(did, m["src"], old)
        if q.get("playground"):
            q["playground"] = rewrite_src(did, q["playground"], old)
        with open(qp, "w", encoding="utf-8") as f:
            json.dump(q, f, ensure_ascii=False, indent=2)
        nq += 1
    # 改写 work/ 下 HTML 的相对路径
    nh = 0
    for hp in glob.glob(os.path.join(root, "work", "**", "*.html"), recursive=True):
        with open(hp, encoding="utf-8") as f:
            s = f.read()
        rules = HTML_FIX + (ROLLOUT_FIX if os.sep + "rollout" + os.sep in hp else [])
        s2 = s
        for pat, rep in rules:
            s2 = re.sub(pat, rep, s2)
        if s2 != s:
            nh += sum(len(re.findall(p, s)) for p, _ in rules)
            with open(hp, "w", encoding="utf-8") as f:
                f.write(s2)
    policy = getattr(a, "media", None) or "ignore"
    P.write_git_files(root, policy)
    import summary as SUM
    ns = SUM.rebuild(root)
    with open(os.path.join(root, P.LOG), "a", encoding="utf-8") as f:
        f.write(f"- 迁移 | 从 {a.src}/ 迁移到 {P.DIRNAME}/ | 决策 {nq} 个 | HTML 路径改写 {nh} 处 | 摘要卡 {ns} 张\n")
    if os.path.isdir(dist) and not os.listdir(dist):
        os.rmdir(dist)
    left = [os.path.relpath(os.path.join(dp, f), project) for dp, dn, fn in os.walk(old) for f in fn]
    if not left:
        shutil.rmtree(old)
    print(f"[migrate] 完成：决策 {nq} 个，HTML 路径改写 {nh} 处，摘要卡 {ns} 张；media/ 策略 {policy}。")
    if left:
        print(f"[migrate] {a.src}/ 里还剩 {len(left)} 个文件没动，请确认后自行处理：{left[:10]}")
    legacy = os.path.join(root, "cache", "legacy")
    if os.path.exists(legacy):
        print(f"[migrate] 无法归类的文件放在 {legacy}，请检查后移到合适的区。")
    print("[migrate] 下一步：检查 work/ 下页面里的图片能否正常显示；更新 .claude/settings.json 里的 hook 路径（如有）；"
          f"如果旧 {a.src}/ 曾被 git 跟踪，提交这次移动（git add -A {a.src} {P.DIRNAME}）。")
