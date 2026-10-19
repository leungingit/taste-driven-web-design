"""目录布局：所有脚本只从这里取路径。

单期项目：项目根目录下的隐藏目录 .taste-design/（可用环境变量 TASTE_DESIGN_DIR 改名），
按 git 处理方式分四个区：

  record/   提交   决策过程与结论：状态、范围、简报、每个决策的题目与答案、决策日志、决策摘要卡（含小缩略图）
  work/     提交   文本设计稿：灰模、方案页、原型、playground、令牌、资产规范、铺开清单、质检报告、交付说明
  media/    可选   二进制素材：用户素材、决策样例图、基线截图、改造截图、关键帧、资产图（默认不提交，可改 Git LFS）
  cache/    不提交 运行时文件：等待状态、服务端口、源码快照、静态导出页、临时文件

多期项目：.taste-design/project.json 登记各期；每一期仍是独立的四区目录：

  phases/<ID>/record|work|media|cache
  shared/ 只放跨期稳定内容：品牌、设计系统等
"""
import datetime, json, os, re

DIRNAME = os.environ.get("TASTE_DESIGN_DIR", ".taste-design")
ZONES = ("record", "work", "media", "cache")
MEDIA_POLICIES = ("ignore", "lfs", "commit")
PHASES = "phases"
PROJECT = "project.json"
SHARED = "shared"
PHASE_META = "record/phase.json"

# 各文件在根目录下的相对位置
STATE = "record/state.json"
SCOPE = "record/scope.json"
CONFIG = "record/config.json"
DECISIONS = "record/decisions"           # record/decisions/<ID>/{question.json, answer.json}
LOG = "record/decisions.md"
PENDING = "record/pending-review.md"
CHANGELOG = "record/changelog.md"
SUMMARY = "record/summary"               # 决策摘要卡：<ID>.md + thumbs/
REFS = "record/refs.yaml"
NOTES = "record/notes.md"
PROGRESS = "record/progress.md"           # 当前工作位置与未完成事项，不替代状态和答案
BRIEF = "record/brief"                   # brief.md traits.md content.yaml constraints.yaml

SAMPLES = "media/samples"                # media/samples/<ID>/…   question.json 里不带前缀的 src 相对这里
INBOX = "media/inbox"                    # images/ video/ prototypes/ brand/
BASELINE = "media/baseline"
SHOTS = "media/shots"                    # rollout/ qa/ gates/
KEYFRAMES = "media/keyframes"
ASSET_MEDIA = "media/assets"             # benchmark/ derived/

RUNTIME = "cache/runtime"                # 交付/确认版本、等待心跳、暂停、服务与阻塞状态
SNAPSHOTS = "cache/snapshots"
EXPORT = "cache/export"

MKDIRS = [
    DECISIONS, SUMMARY + "/thumbs", BRIEF,
    "work/wireframe", "work/variants", "work/proto", "work/playgrounds", "work/assets",
    "work/rollout", "work/qa", "work/handoff",
    SAMPLES, INBOX + "/images", INBOX + "/video", INBOX + "/prototypes", INBOX + "/brand",
    BASELINE, SHOTS + "/rollout", SHOTS + "/qa", KEYFRAMES, ASSET_MEDIA + "/benchmark", ASSET_MEDIA + "/derived",
    RUNTIME, SNAPSHOTS, EXPORT,
]


def find_root(start="."):
    """从 start 向上查找当前设计根。

    单期项目返回 .taste-design/；多期项目必须通过 phase 选择，
    单期目录内只有一个期时可直接返回该期，多个期时拒绝猜测。
    """
    return find_root_phase(start)


def find_root_phase(start=".", phase=None):
    phase = phase or os.environ.get("TASTE_DESIGN_PHASE")
    d = os.path.abspath(start)
    while True:
        if os.path.exists(os.path.join(d, STATE)):
            if phase:
                return select_phase(find_container(d) or d, phase)
            return d
        if os.path.basename(d) == DIRNAME:
            return select_phase(d, phase)
        cand = os.path.join(d, DIRNAME)
        if os.path.exists(os.path.join(cand, PROJECT)) or os.path.isdir(os.path.join(cand, PHASES)) \
                or os.path.exists(os.path.join(cand, STATE)):
            return select_phase(cand, phase)
        nd = os.path.dirname(d)
        if nd == d:
            return None
        d = nd


def find_container(start="."):
    """从 start 向上查找 .taste-design 容器，不要求其中已有某一期。"""
    d = os.path.abspath(start)
    while True:
        if os.path.basename(d) == DIRNAME and (
                os.path.exists(os.path.join(d, PROJECT)) or os.path.isdir(os.path.join(d, PHASES))
                or os.path.exists(os.path.join(d, STATE))):
            return d
        cand = os.path.join(d, DIRNAME)
        if os.path.exists(os.path.join(cand, PROJECT)) or os.path.isdir(os.path.join(cand, PHASES)) \
                or os.path.exists(os.path.join(cand, STATE)):
            return cand
        nd = os.path.dirname(d)
        if nd == d:
            return None
        d = nd


def find_root_for_path(path):
    """只对位于某一期设计目录内的路径返回设计根；项目源码路径返回 None。"""
    path = os.path.abspath(path)
    container = find_container(path)
    if not container:
        return None
    in_phase = os.path.join(container, PHASES) + os.sep
    if (path == container or path.startswith(container + os.sep)) and os.path.exists(os.path.join(container, STATE)):
        return container
    if path.startswith(in_phase):
        rel = path[len(in_phase):]
        pid = rel.split(os.sep, 1)[0]
        candidate = os.path.join(container, PHASES, pid)
        return candidate if os.path.exists(os.path.join(candidate, STATE)) else None
    return None


def phase_ids(container):
    base = os.path.join(container, PHASES)
    if not os.path.isdir(base):
        return []
    return sorted(d for d in os.listdir(base)
                  if re.match(r"^[A-Za-z0-9][A-Za-z0-9._-]*$", d)
                  and os.path.exists(os.path.join(base, d, STATE)))


def phase_dir(container, phase):
    if not re.match(r"^[A-Za-z0-9][A-Za-z0-9._-]*$", phase or ""):
        raise ValueError(f"期 ID 只能用字母、数字、点、下划线或连字符：{phase!r}")
    return os.path.join(container, PHASES, phase)


def select_phase(container, phase=None):
    """从容器选出某一期；单期兼容旧布局，多期必须明确 phase。"""
    phase = phase or os.environ.get("TASTE_DESIGN_PHASE")
    if phase:
        root = phase_dir(container, phase)
        if not os.path.exists(os.path.join(root, STATE)):
            ids = phase_ids(container)
            raise ValueError(f"找不到设计期 {phase!r}；现有期：{ids or '无'}；容器：{container}")
        return root
    if os.path.exists(os.path.join(container, STATE)) and not os.path.isdir(os.path.join(container, PHASES)):
        return container
    ids = phase_ids(container)
    if len(ids) == 1:
        return os.path.join(container, PHASES, ids[0])
    if len(ids) > 1:
        raise ValueError(f"检测到多个设计期：{ids}。请用 --phase ID 指定，不能默认猜最新一期")
    return None


def resolve_root(root=None, phase=None, creating=False):
    """命令行入口统一解析 root；--root 可指向容器、某期或项目目录。"""
    explicit = os.path.abspath(root) if root else None
    phase = phase or os.environ.get("TASTE_DESIGN_PHASE")
    if not creating and not explicit:
        found = find_root_phase(os.getcwd(), phase)
        if found:
            return found
    if explicit and os.path.exists(os.path.join(explicit, STATE)) and not phase:
        return explicit
    container = explicit if explicit and os.path.basename(explicit) == DIRNAME else find_container(explicit or os.getcwd())
    if not container:
        container = explicit or os.path.join(os.getcwd(), DIRNAME)
    if creating:
        return container
    selected = select_phase(container, phase)
    return selected or container


def default_root(phase=None):
    return resolve_root(None, phase)


def p(root, rel):
    return os.path.join(root, rel)


def runtime(root, name):
    return os.path.join(root, RUNTIME, name)


def decision_dir(root, did):
    return os.path.join(root, DECISIONS, did)


def phase_info(root):
    """返回本期的 phase.json；单期项目返回 None。"""
    p = os.path.join(root, PHASE_META)
    if not os.path.exists(p):
        return None
    with open(p, encoding="utf-8") as f:
        return json.load(f)


def project_path(container):
    return os.path.join(container, PROJECT)


def load_project(container):
    p = project_path(container)
    if not os.path.exists(p):
        return None
    with open(p, encoding="utf-8") as f:
        return json.load(f)


def save_project(container, project):
    p = project_path(container)
    tmp = p + f".{os.getpid()}.tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(project, f, ensure_ascii=False, indent=2)
    os.replace(tmp, p)


CONTAINER_README = """# .taste-design 多期设计记录

本目录按设计期隔离流程与产物：

| 路径 | 内容 |
|---|---|
| `project.json` | 期列表、名称与继承关系 |
| `phases/<ID>/` | 本期独立的 record / work / media / cache |
| `shared/brand.md` | 跨期稳定、已验证的品牌基线 |
| `shared/design-system/` | 跨期稳定的设计系统与组件约定 |

所有命令都要明确期，例如：

```bash
python3 <skill>/scripts/gate.py --phase P1 next --json
python3 <skill>/scripts/gate.py --phase P2 context --json --compact
python3 <skill>/scripts/decide_server.py --phase P2 serve
```

不要默认选择“最新一期”。`shared/` 只放跨期稳定结论，阶段范围、验收、答案和当前工作仍留在各自的 `phases/<ID>/record/`。
"""


SHARED_README = """# 跨期共享基线

只记录 P1、P2……都需要遵守、且已经由用户确认的内容。阶段专属要求、答案和当前工作留在各自的设计期里。

- `brand.md`：品牌气质、视觉母题、不可变识别特征及来源。
- `design-system/`：跨期稳定令牌、组件契约、素材规则。

新增一期时，用 `gate.py phase add ... --inherit shared/brand.md` 显式登记依赖；闸门 0 会检查继承路径是否存在。
"""


BRAND_TEMPLATE = """# 跨期品牌基线

只写已确认且跨期有效的内容；每项注明来源决策或文件。

- 品牌气质：
- 不可变的视觉识别特征：
- 来源：
- 最后核对：
"""


DESIGN_SYSTEM_README = """# 跨期设计系统

放跨期稳定的令牌、组件契约、图标/素材规则和对应验收来源。本期专属实验不要放这里。
"""


def ensure_container(container):
    """创建或补齐多期项目容器；不存在的期由 phase add / init --phase 创建。"""
    os.makedirs(os.path.join(container, PHASES), exist_ok=True)
    os.makedirs(os.path.join(container, SHARED, "design-system"), exist_ok=True)
    files = {
        os.path.join(container, "README.md"): CONTAINER_README,
        os.path.join(container, SHARED, "README.md"): SHARED_README,
        os.path.join(container, SHARED, "brand.md"): BRAND_TEMPLATE,
        os.path.join(container, SHARED, "design-system", "README.md"): DESIGN_SYSTEM_README,
    }
    for path, text in files.items():
        if not os.path.exists(path):
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "w", encoding="utf-8") as f:
                f.write(text)
    project = load_project(container)
    if project is None:
        project = {"schema": 1, "phases": []}
        save_project(container, project)
    return project


def inheritance_path(container, rel):
    """只允许容器内的相对路径；不能通过绝对路径、.. 或符号链接越界。"""
    if not isinstance(rel, str):
        raise ValueError("继承路径必须是字符串")
    norm = rel.replace("\\", "/")
    if not norm or norm.startswith("/") or re.match(r"^[A-Za-z]:", norm) or ".." in norm.split("/"):
        raise ValueError(f"继承路径必须位于 .taste-design/ 内：{rel!r}")
    base = os.path.realpath(container)
    path = os.path.realpath(os.path.join(base, norm))
    if path == base or os.path.commonpath([base, path]) != base:
        raise ValueError(f"继承路径必须位于 .taste-design/ 内：{rel!r}")
    return os.path.join(container, norm)


def add_phase_record(container, phase, name, parent=None, inherits=None):
    root = phase_dir(container, phase)
    for rel in inherits or []:
        inheritance_path(container, rel)
    project = load_project(container) or {"schema": 1, "phases": []}
    if any(x.get("id") == phase for x in project.get("phases") or []):
        raise ValueError(f"设计期 {phase!r} 已存在")
    if os.path.exists(os.path.join(root, STATE)):
        raise ValueError(f"设计期目录 {phase!r} 已有状态，不能覆盖")
    ids = {x.get("id") for x in project.get("phases") or []}
    if parent and parent not in ids:
        raise ValueError(f"父期 {parent!r} 不存在；现有期：{sorted(ids)}")
    ensure_container(container)
    item = {"id": phase, "name": name or phase, "parent_phase": parent, "inherits": inherits or []}
    project.setdefault("phases", []).append(item)
    save_project(container, project)
    os.makedirs(os.path.join(root, "record"), exist_ok=True)
    meta = {**item, "created_at": datetime.datetime.now().astimezone().isoformat(timespec="seconds")}
    with open(os.path.join(root, PHASE_META), "w", encoding="utf-8") as f:
        json.dump(meta, f, ensure_ascii=False, indent=2)
    return root


def resolve_src(did, src):
    """question.json 里 media.src → 相对根目录的路径（或原样返回 URL）。
    http(s)/data: 原样；@/xxx 相对 .taste-design；其余相对 media/samples/<决策ID>/。"""
    if src.startswith(("http://", "https://", "data:")):
        return None
    path, frag = src, ""
    for sep in ("#", "?"):
        if sep in path:
            path, rest = path.split(sep, 1)
            frag = sep + rest
            break
    rel = path[2:] if path.startswith("@/") else f"{SAMPLES}/{did}/{path}"
    return os.path.normpath(rel).replace(os.sep, "/"), frag


def load_config(root):
    try:
        with open(p(root, CONFIG), encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {"media": "ignore"}


GITIGNORE_HEAD = """# 由 gate.py 生成。改素材策略请运行：gate.py media ignore|lfs|commit
# record/ 和 work/ 是决策记录与设计稿，应当提交；cache/ 永远不提交。
cache/
"""

README = """# .taste-design

由 taste-driven-web-design skill 管理的设计过程目录。

单期项目把 `record/`、`work/`、`media/`、`cache/` 放在本目录下。需要一期、二期、三期时，改用
`project.json` + `phases/<ID>/...` + `shared/...` 的多期布局，每个命令显式带 `--phase ID`。

| 目录 | 内容 | git |
|---|---|---|
| `record/` | 决策过程与结论：状态、范围、简报、每个决策的题目与答案、决策日志、待复核清单 | 提交 |
| `record/summary/` | 每个决策的摘要卡（选项、结论、备注、小缩略图），可直接在代码托管网站上浏览 | 提交 |
| `record/progress.md`、`record/notes.md` | 当前工作位置、对话补充与来源；恢复时先核对真实状态及产物 | 提交 |
| `work/` | 文本设计稿：灰模、方案页、原型、playground、令牌、资产规范、铺开清单、质检报告、交付说明 | 提交 |
| `media/` | 二进制素材：用户素材、决策样例图、基线与改造截图、关键帧、资产图 | 当前策略：**{policy}** |
| `cache/` | 运行时文件、源码快照、静态导出页 | 不提交 |

素材策略：`ignore`（不提交，只保留摘要卡里的小缩略图）、`lfs`（用 Git LFS 提交）、`commit`（直接提交）。
切换：`python3 <skill>/scripts/gate.py media <策略>`。

打开决策页：`python3 <skill>/scripts/decide_server.py serve`。

恢复工作：先用 `python3 <skill>/scripts/gate.py context --json --compact` 定位当前期和下一步；需要细节时再运行完整概览或 `--section` 分页。缺少 progress.md 时按事实补建，定位后运行 `gate.py next --json` 完整读取待落实答案。恢复协议见技能的 `references/continuity.md`。
"""


def write_git_files(root, policy):
    if policy not in MEDIA_POLICIES:
        raise ValueError(policy)
    lines = GITIGNORE_HEAD
    if policy == "ignore":
        lines += "media/\n"
    with open(p(root, ".gitignore"), "w", encoding="utf-8") as f:
        f.write(lines)
    ga = p(root, ".gitattributes")
    if policy == "lfs":
        with open(ga, "w", encoding="utf-8") as f:
            f.write("# 由 gate.py 生成：media/ 下的素材用 Git LFS 管理（需要先 git lfs install）\n"
                    "media/** filter=lfs diff=lfs merge=lfs -text\n")
    elif os.path.exists(ga):
        os.remove(ga)
    with open(p(root, "README.md"), "w", encoding="utf-8") as f:
        f.write(README.replace("{policy}", {"ignore": "不提交", "lfs": "Git LFS", "commit": "提交"}[policy]))
    cfg = load_config(root)
    cfg["media"] = policy
    os.makedirs(p(root, "record"), exist_ok=True)
    with open(p(root, CONFIG), "w", encoding="utf-8") as f:
        json.dump(cfg, f, ensure_ascii=False, indent=2)
