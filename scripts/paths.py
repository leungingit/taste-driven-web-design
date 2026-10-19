"""目录布局：所有脚本只从这里取路径。

项目根目录下的隐藏目录 .taste-design/（可用环境变量 TASTE_DESIGN_DIR 改名），按 git 处理方式分四个区：

  record/   提交   决策过程与结论：状态、范围、简报、每个决策的题目与答案、决策日志、决策摘要卡（含小缩略图）
  work/     提交   文本设计稿：灰模、方案页、原型、playground、令牌、资产规范、铺开清单、质检报告、交付说明
  media/    可选   二进制素材：用户素材、决策样例图、基线截图、改造截图、关键帧、资产图（默认不提交，可改 Git LFS）
  cache/    不提交 运行时文件：等待状态、服务端口、源码快照、静态导出页、临时文件
"""
import json, os

DIRNAME = os.environ.get("TASTE_DESIGN_DIR", ".taste-design")
ZONES = ("record", "work", "media", "cache")
MEDIA_POLICIES = ("ignore", "lfs", "commit")

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
    """从 start 向上查找 <项目>/.taste-design（以 record/state.json 为准）。"""
    d = os.path.abspath(start)
    while True:
        if os.path.basename(d) == DIRNAME and os.path.exists(os.path.join(d, STATE)):
            return d
        cand = os.path.join(d, DIRNAME)
        if os.path.exists(os.path.join(cand, STATE)):
            return cand
        nd = os.path.dirname(d)
        if nd == d:
            return None
        d = nd


def default_root():
    return find_root() or os.path.abspath(DIRNAME)


def p(root, rel):
    return os.path.join(root, rel)


def runtime(root, name):
    return os.path.join(root, RUNTIME, name)


def decision_dir(root, did):
    return os.path.join(root, DECISIONS, did)


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

恢复工作：`python3 <skill>/scripts/gate.py context --json`，按清单读取当前记录，再运行 `gate.py next --json`。恢复协议见技能的 `references/continuity.md`。
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
