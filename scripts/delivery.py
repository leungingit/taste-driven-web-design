"""交付边界：用户决策、工程指纹与阶段检查；只保存路径和摘要，不复制源码。"""
import hashlib
import json
import os
import stat

import paths as P
from rules import validate_question

MODES = {"design-only", "design-and-implement"}
BASELINE = "record/implementation-baseline.json"
DOCUMENTS = {"AGENTS.md", "docs/design-system.md"}
IGNORED = {".git", "node_modules", "__pycache__", ".venv", "venv"}
OUTPUTS = {"dist", "build", "target", ".next", "coverage", ".pytest_cache"}


def project_root(root):
    container = P.find_container(root) or root
    return os.path.dirname(container)


def allowed_document(project, rel, approved=False):
    path = os.path.join(project, rel)
    return approved and rel in DOCUMENTS and os.path.realpath(path) == os.path.join(os.path.realpath(project), rel)


def documents_approved(ds):
    active = [d for d in ds if d.get("role") == "documentation-sync" and d.get("_answer")]
    if len(active) != 1 or validate_question(active[0]):
        return False
    answer = active[0]["_answer"]
    return answer.get("answered_by") == "user" and answer.get("choice") == ["update"] and bool(answer.get("ts"))


def manifest(root):
    project = project_root(root)
    container = P.find_container(root) or root
    result = {}
    def unreadable(error):
        raise error
    for base, dirs, files in os.walk(project, followlinks=False, onerror=unreadable):
        dirs[:] = sorted(d for d in dirs if d not in IGNORED
                         and not (base == project and d in OUTPUTS)
                         and os.path.join(base, d) != container)
        links = [d for d in dirs if os.path.islink(os.path.join(base, d))]
        dirs[:] = [d for d in dirs if d not in links]
        for entry in sorted(files + links):
            path = os.path.join(base, entry)
            rel = os.path.relpath(path, project).replace(os.sep, "/")
            info = os.lstat(path)
            if stat.S_ISLNK(info.st_mode):
                digest = hashlib.sha256(os.fsencode(os.readlink(path))).hexdigest()
            elif stat.S_ISREG(info.st_mode):
                h = hashlib.sha256()
                with open(path, "rb") as f:
                    for chunk in iter(lambda: f.read(1024 * 1024), b""):
                        h.update(chunk)
                digest = h.hexdigest()
            else:
                continue
            result[rel] = [stat.S_IFMT(info.st_mode), stat.S_IMODE(info.st_mode), digest]
    return result


def capture(root):
    path = os.path.join(root, BASELINE)
    if os.path.exists(path):
        return
    files = manifest(root)
    with open(path, "w", encoding="utf-8") as f:
        json.dump({"files": files}, f, ensure_ascii=False, indent=2)


def decision(ds):
    valid = [d for d in ds if d.get("role") == "delivery-boundary" and d.get("stage") == 0
             and (d.get("_answer") or {}).get("answered_by") == "user"]
    if len(valid) != 1:
        return None
    d = valid[0]
    if validate_question(d):
        return None
    a = d["_answer"]
    if len(a.get("choice") or []) != 1 or a["choice"][0] not in MODES or not a.get("ts"):
        return None
    return {"mode": a["choice"][0], "decision_id": d["id"], "answer_ts": a["ts"]}


def check(root, st, sc, ds):
    mode = (sc or {}).get("delivery_mode")
    sealed = st.get("delivery_boundary")
    # 旧版已经进入中途的项目保持兼容；重新过闸门 0 时必须补选。
    if mode is None and sealed is None and 0 in st.get("passed", []):
        return []
    selected = decision(ds)
    probs = []
    if mode not in MODES:
        probs.append("交付边界未确认：scope.json 需要 delivery_mode（design-only / design-and-implement）")
    if selected is None or selected["mode"] != mode:
        probs.append("需要唯一的阶段 0 role=delivery-boundary 用户单选答案，并与 delivery_mode 一致；不能代答或使用自由文本代替")
    if sealed and 0 in st.get("passed", []) and (sealed != selected or sealed["mode"] != mode):
        probs.append("交付边界与闸门 0 已确认记录不一致；先 rollback 0，再让用户重新选择")
    if mode == "design-only" or ((sealed or {}).get("mode") == "design-only"
                                and (0 in st.get("passed", []) or selected is None or selected["mode"] != mode)):
        path = os.path.join(root, BASELINE)
        if not os.path.exists(path):
            probs.append("缺少工程指纹基线；不得用当前源码静默补建，需核对原始工程后重新建立设计期")
        else:
            with open(path, encoding="utf-8") as f:
                before = json.load(f)["files"]
            after = manifest(root)
            project = project_root(root)
            approved = documents_approved(ds)
            changed = sorted(p for p in before.keys() | after.keys()
                             if before.get(p) != after.get(p) and not allowed_document(project, p, approved))
            if changed:
                probs.append("仅设计模式发现工程实现变动（新增/删除/内容或权限变化）：" + "、".join(changed[:10])
                             + (f" 等共 {len(changed)} 项" if len(changed) > 10 else "")
                             + "；先核对并处理，不得刷新基线掩盖差异")
    return probs
