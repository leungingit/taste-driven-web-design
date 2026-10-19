"""等待用户决策的公共逻辑：decide_server.py wait（任何 CLI 智能体）和 wait_hook.py（Claude Code Stop hook）共用。

状态文件（都在 .taste-design/cache/runtime/ 下，不提交）：
  .agent-delivered.json   已成功生成交付结果的答案版本（id + ts）
  .agent-acked.json       智能体落实后明确确认的答案版本；旧 seen 标记不作为确认
  .agent-waiting     智能体正在等待时每 2 秒刷新一次；决策页据此显示「智能体在等你」
  .paused            用户在决策页点了「我先离开」
  .server.json       决策服务的端口和进程号
"""
import contextlib, glob, json, os, sys, time, urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import paths as P  # noqa: E402

STATUS = {
    "answered": 0,    # 有新答案，继续工作
    "timeout": 10,    # 本段等待到时，没有新答案：立刻再次调用 wait
    "paused": 11,     # 用户明确暂停
    "nothing": 12,    # 没有可作答的决策：去生成下一个决策或运行 gate.py pass
    "idle": 13,       # 空闲提示：续接等待，不能当作流程结束
    "no-server": 14,  # 决策服务没在运行：先启动服务
    "completed": 15,  # 整个设计流程完成
    "blocked": 16,    # 已记录具体原因、尝试与所需用户操作的真实阻塞
}


def find_root(start="."):
    return P.find_root(start)


def _p(root, name):
    os.makedirs(os.path.join(root, P.RUNTIME), exist_ok=True)
    return P.runtime(root, name)


def load_json(p, default=None):
    try:
        with open(p, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return default


def paused(root):
    return os.path.exists(_p(root, ".paused"))


def set_paused(root, on):
    p = _p(root, ".paused")
    if on:
        with open(p, "w") as f:
            f.write(str(time.time()))
    elif os.path.exists(p):
        os.remove(p)


def agent_waiting(root, fresh=6):
    p = _p(root, ".agent-waiting")
    return os.path.exists(p) and time.time() - os.path.getmtime(p) < fresh


@contextlib.contextmanager
def heartbeat(root, who):
    p = _p(root, ".agent-waiting")
    def beat():
        with open(p, "w") as f:
            json.dump({"who": who, "pid": os.getpid(), "ts": time.time()}, f)
    try:
        yield beat
    finally:
        with contextlib.suppress(FileNotFoundError):
            os.remove(p)


def server_alive(root):
    info = load_json(_p(root, ".server.json"))
    if not info:
        return False
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{info['port']}/api/ping", timeout=2) as r:
            return r.status == 200
    except Exception:
        return False


def all_answers(root):
    out = {}
    for p in glob.glob(os.path.join(root, P.DECISIONS, "*", "answer.json")):
        a = load_json(p)
        if a:
            a.setdefault("id", os.path.basename(os.path.dirname(p)))
            out[a["id"]] = a
    return out


def save_runtime(root, name, value):
    p = _p(root, name)
    tmp = p + f".{os.getpid()}.tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(value, f, ensure_ascii=False, indent=2)
    os.replace(tmp, p)


def acked(root):
    return load_json(_p(root, ".agent-acked.json"), {}) or {}


def delivered(root):
    return load_json(_p(root, ".agent-delivered.json"), {}) or {}


def ack_answer(root, did, ts):
    """落实后确认精确版本；未交付或已被替换的答案不能误确认。"""
    a = all_answers(root).get(did)
    if not a or a.get("ts") != ts:
        raise ValueError("答案不存在或版本已变化，请重新读取后确认")
    if delivered(root).get(did) != ts:
        raise ValueError("该版本尚未交付；先运行 wait 或 gate.py next --json 读取完整答案")
    s = acked(root)
    s[did] = ts
    save_runtime(root, ".agent-acked.json", s)


def new_answers(root):
    st = load_json(os.path.join(root, P.STATE), {}) or {}
    cur = st.get("stage")
    here = {cur} | {int(k) for k, v in (st.get("merged") or {}).items() if v == cur}
    s = acked(root)
    out = []
    for did, a in sorted(all_answers(root).items()):
        q = load_json(os.path.join(root, P.DECISIONS, did, "question.json"), {}) or {}
        if q.get("stage") in here and (did not in s or s[did] != a.get("ts")):
            out.append(a)
    return out


def last_activity(root):
    ts = [os.path.getmtime(p) for p in glob.glob(os.path.join(root, P.DECISIONS, "*", "*.json"))]
    return max(ts) if ts else time.time()


def view(root):
    from decide_server import Store
    return Store(root, 99).view(include_flow=False)


def decision_notice(root, snapshot):
    """生成等待前应转达给用户的入口和当前可作答项，不将排队项冒充已开放。"""
    st = load_json(os.path.join(root, P.STATE), {}) or {}
    channel = st.get("channel", "web")
    info = load_json(_p(root, ".server.json"), {}) or {}
    limit = info.get("max_open", 3) if channel == "web" else 3
    items = [{"id": q["id"], "title": q.get("title", q["id"])} for q in snapshot["open"][:limit]]
    url, path = None, None
    lines = [f"当前阶段：{snapshot['stage']} · {snapshot['stage_name']}"]
    if channel == "web":
        if info.get("port"):
            host = info.get("host", "127.0.0.1")
            host = "localhost" if host in ("127.0.0.1", "0.0.0.0") else host
            url = f"http://{host}:{info['port']}/"
            lines.append(f"请打开决策页：[打开决策页]({url})")
        else:
            lines.append("尚未取得决策页地址：先启动 decide_server.py serve 并确认服务可用，再将实际地址告知用户；不要直接等待。")
    elif channel == "static":
        path = os.path.join(root, P.EXPORT, "index.html")
        lines.append(f"请打开已导出的决策页：[{os.path.basename(path)}]({path})；创建或变更决策后须重新 export。")
    else:
        lines.append("请查看对话中展示的决策样张；智能体须先展示样张，再等待你的答复。")
    lines.append("本轮待决定：")
    lines.extend(f"- {q['id']}：{q['title']}" for q in items)
    if channel == "web":
        lines.append("请在页面中逐项选择并提交，需要调整可填写备注；提交后我会读取答案并继续。若服务位于 SSH 远程机器，需先配置端口转发。")
    else:
        lines.append("请按决策 ID 回复选择和备注；静态页面可复制回复文本发回当前对话。")
    return {"channel": channel, "url": url, "path": path, "items": items, "text": "\n".join(lines)}


def summary(root, answers):
    """新答案 + 当前局面 + 下一步提示。"""
    from gate import workflow_next
    v = view(root)
    flow = workflow_next(root, snapshot=v)
    qs = {}
    for a in answers:
        q = load_json(os.path.join(root, P.DECISIONS, a["id"], "question.json"), {})
        qs[a["id"]] = q.get("title", "")
    lines = []
    for a in answers:
        parts = [f"选择 {','.join(a.get('choice') or []) or '-'}"]
        if a.get("setting"):
            stg = a["setting"]
            parts = [f"做成设置项（维度 {stg.get('axis')}）：保留 {'/'.join(stg['values'])}，默认 {stg['default']}"
                     "——先判断它是不是「不同用户会合理偏好不同选项」：是就写进 work/theme/axes.json（含 who）；"
                     "只是难以取舍就记入 axes.json 的 declined 并建一个决策请用户选定一个（见 references/design-rules.md 0.12）"]
        if a.get("other"):
            parts.append(f"其他：{a['other']}")
        if a.get("note"):
            parts.append(f"备注：{a['note']}")
        if a.get("value"):
            parts.append("提交了数值（见 answer.json 的 value）")
        lines.append(f"- {a['id']}「{qs[a['id']]}」：" + "；".join(parts))
    return {**flow, "new": answers, "new_text": "\n".join(lines)}


def mark_delivered(root, answers):
    s = delivered(root)
    s.update({a["id"]: a.get("ts") for a in answers})
    save_runtime(root, ".agent-delivered.json", s)


def deliver(root, answers):
    """摘要构建失败时不消费答案；交付后仍需 ack，允许中断后重试。"""
    result = summary(root, answers)
    mark_delivered(root, answers)
    return result


def wait(root, timeout, idle_minutes, poll=1.0, who="cli"):
    """阻塞直到出现新答案或其他终止条件。返回 (status, payload)。"""
    start = time.time()
    with heartbeat(root, who) as beat:
        while True:
            beat()
            from gate import workflow_next
            flow = workflow_next(root)
            if flow["status"] in ("paused", "blocked", "completed"):
                return flow["status"], flow
            got = flow["new"]
            if got:
                time.sleep(0.8)            # 用户可能连着提交几个，稍等合并
                flow = workflow_next(root)
                if flow["status"] in ("paused", "blocked", "completed"):
                    return flow["status"], flow
                got = flow["new"]
                if not got:
                    continue
                return "answered", deliver(root, got)
            if flow["status"] != "waiting":
                return "nothing", flow
            if not server_alive(root):
                return "no-server", {"next": "决策服务没在运行。后台启动 decide_server.py serve，把地址告诉用户，再运行 wait。"}
            if idle_minutes and time.time() - max(start, last_activity(root)) > idle_minutes * 60:
                return "idle", {**flow, "next": "本段空闲提示：续接同一等待命令；空闲不是用户暂停，不得结束流程。"}
            if time.time() - start >= timeout:
                return "timeout", {**flow, "next": "本段等待到时。立即续接同一 wait 命令；工具返回不代表流程结束。"}
            time.sleep(poll)
