"""决策文件的校验规则，decide_server.py 和 gate.py 共用。"""

TYPES = {"single", "multi", "scale", "tune", "gate"}
VISUAL_TYPES = {"single", "multi", "scale"}

# 样例图的来源
#   inbox      用户提供的创意素材（原图、裁切、截图），需 ref 指向素材编号
#   search     检索到的参考图，需 credit
#   screenshot 外部参考网站/作品页的截图，需 credit
#              （本项目自己产出的页面截图算 rendered）
#   generated  生图工具产出（固定主体只改风格的对照图）
#   rendered   智能体用代码画/渲染的（HTML/CSS/SVG/Python 绘图）
ORIGINS = {"inbox", "search", "screenshot", "generated", "rendered"}
ARTWORK_ORIGINS = {"inbox", "search", "screenshot", "generated"}

# sample_kind
#   artwork      画面类：插画风格、笔触、写实程度、摄影风格、质感氛围、主题隐喻……
#                不允许 rendered，必须用真实素材/检索图/生成图
#   code-native  决策对象本身就是代码产物：配色、字体排印、版式骨架、图标/SVG、动效、方案页面
#                允许 rendered
SAMPLE_KINDS = {"artwork", "code-native"}

# 决策的角色，闸门会按角色检查
#   scope               阶段 0 的范围与自由度
#   reference-breakdown 影视/游戏/品牌类参考的拆解（每个参考一个）
#   direction           方向/方案选择（必须含「大胆」档）
#   asset-benchmark     为每类内容资产选定基准资产
#   pending-review      交付前集中复核智能体代定的事项
#   skip                有人值守时，跳过可选阶段前让用户点头（需 skip_stage）
ROLES = {"scope", "delivery-boundary", "documentation-sync", "reference-breakdown", "direction", "asset-benchmark", "pending-review", "skip"}

# dimension=motion 的决策：样例必须可播放（video 或 html），静态图片不能表达运动
PLAYABLE = {"video", "html"}
INTENSITIES = {"克制", "中等", "大胆"}

# 保真度：样例离最终效果有多近。决策里只要有 rough / proxy 样例，就必须写 asks（问的是什么）
#   rough     粗稿：线框、灰模、占位图、草图                   只能判断布局、构图、比例、镜头、信息层级
#   proxy     替身：现成素材或资产临时放进去                  同上，空间感和比例更接近真实
#   overlay   在粗稿上叠加或生成的近成品效果（绘制、生图、合成），布局不变
#   lookdev   在固定的标准画面里单独比较材质 / 灯光 / 风格 / 角色造型
#   final     成品品质（整页或一个代表性局部）
#   reference 外部参考图（只用于定方向）
FIDELITY = ["rough", "proxy", "overlay", "lookdev", "final", "reference"]
ROUGH = {"rough", "proxy"}
LAYOUT_ASKS = {"layout", "composition", "scale", "camera", "hierarchy"}
LOOK_ASKS = {"color", "typography", "illustration", "material", "lighting", "character", "style", "texture", "atmosphere"}
LOOK_OK = {"overlay", "lookdev", "final", "reference"}


def _check_media(where, media, kind, errs):
    for m in media or []:
        o = m.get("origin")
        if o not in ORIGINS:
            errs.append(f"{where} 的 media 缺少 origin（{'/'.join(sorted(ORIGINS))}）")
            continue
        if kind == "artwork" and o not in ARTWORK_ORIGINS:
            errs.append(f"{where} 是画面类决策（sample_kind=artwork），不得使用程序绘制的样例；"
                        f"请用 inbox 素材的截图/裁切、检索图、作品页截图或生图工具结果")
        if o == "inbox" and not m.get("ref"):
            errs.append(f"{where} 的素材样例需要 ref 指向 inbox 素材编号（如 I03、R1）")
        if o in ("search", "screenshot") and not m.get("credit"):
            errs.append(f"{where} 的检索图/截图需要 credit 写明来源")


def validate_question(q):
    errs = []
    t = q.get("type")
    if t not in TYPES:
        errs.append(f"type 必须是 {sorted(TYPES)}")
    if not isinstance(q.get("stage"), int):
        errs.append("缺少整数 stage")
    visual = q.get("visual", True)
    kind = q.get("sample_kind", "artwork")
    if t in VISUAL_TYPES and visual:
        if kind not in SAMPLE_KINDS:
            errs.append(f"sample_kind 必须是 {sorted(SAMPLE_KINDS)}")
        opts = q.get("options") or []
        if len(opts) < 2:
            errs.append("至少 2 个选项")
        for o in opts:
            if not o.get("media"):
                errs.append(f"视觉决策的选项 {o.get('id')} 没有 media（禁止纯文字视觉选项；非视觉问题请设 \"visual\": false）")
            _check_media(f"选项 {o.get('id')}", o.get("media"), kind, errs)
    elif t in VISUAL_TYPES and len(q.get("options") or []) < 2:
        errs.append("至少 2 个选项")
    _check_media("题目", q.get("media"), kind if (visual and t in VISUAL_TYPES) else "code-native", errs)
    role = q.get("role")
    if role and role not in ROLES:
        errs.append(f"role 必须是 {sorted(ROLES)}")
    if role == "delivery-boundary":
        if q.get("stage") != 0 or t != "single" or visual is not False:
            errs.append("交付边界必须是阶段 0 的非视觉单选决策（type=single, visual=false）")
        ids = [o.get("id") for o in q.get("options") or []]
        if sorted(ids, key=str) != ["design-and-implement", "design-only"]:
            errs.append("交付边界的两个选项 ID 必须是 design-only / design-and-implement")
    if role == "documentation-sync":
        if q.get("stage") != 9 or t != "single" or visual is not False:
            errs.append("文档同步必须是阶段 9 的非视觉单选决策")
        if sorted([o.get("id") for o in q.get("options") or []], key=str) != ["defer", "update"]:
            errs.append("文档同步的两个选项 ID 必须是 update / defer")
    if role == "direction":
        ints = [o.get("intensity") for o in q.get("options") or []]
        if any(i not in INTENSITIES for i in ints):
            errs.append("方向决策的每个选项都要标 intensity：克制 / 中等 / 大胆")
        if "大胆" not in ints:
            errs.append("方向决策至少要有一个「大胆」档选项")
    if role == "reference-breakdown":
        if not q.get("reference"):
            errs.append("参考拆解决策需要 reference 字段（如 \"某部电影\"）")
        if kind != "artwork":
            errs.append("参考拆解决策的样例必须是真实画面（sample_kind=artwork）")
    if role == "skip" and not isinstance(q.get("skip_stage"), int):
        errs.append("role=skip 的决策需要整数 skip_stage")
    if q.get("dimension") == "motion" and t in VISUAL_TYPES:
        for o in q.get("options") or []:
            if not any(m.get("type") in PLAYABLE for m in o.get("media") or []):
                errs.append(f"动效决策的选项 {o.get('id')} 需要可播放的样例（video 或 html，按真实速度播放）")
            if not o.get("motion"):
                errs.append(f"动效决策的选项 {o.get('id')} 需要 motion 字段写明「什么在动、怎么动（摆动/流动/脉冲/交互触发）、周期、什么不动」")
    if q.get("allow_setting"):
        if t not in ("single", "scale"):
            errs.append("allow_setting 只能用在 single / scale 决策上")
        if role in ("scope", "delivery-boundary", "documentation-sync", "skip", "pending-review", "asset-benchmark", "reference-breakdown"):
            errs.append(f"role={role} 的决策不能做成设置项")
        if not q.get("setting_axis"):
            errs.append("allow_setting 的决策需要 setting_axis：如果做成设置，它属于哪个维度（如 density / mode / accent / preset）")
    asks = set(q.get("asks") or [])
    fids = {m.get("fidelity") for o in q.get("options") or [] for m in o.get("media") or []}
    if fids & ROUGH and not asks:
        errs.append("样例里有 rough / proxy（粗稿、替身），需要写 asks 说明问的是布局类还是观感类问题")
    if asks:
        bad = asks - LAYOUT_ASKS - LOOK_ASKS - {"motion"}
        if bad:
            errs.append(f"asks 里有未知项 {sorted(bad)}，可选：{sorted(LAYOUT_ASKS | LOOK_ASKS | {'motion'})}")
        if asks & LAYOUT_ASKS and asks & LOOK_ASKS:
            errs.append("一个决策不要同时问布局类（布局/构图/比例/镜头）和观感类（配色/字体/插图/材质/灯光/风格）：拆成两个决策，先定布局再定观感")
        for o in q.get("options") or []:
            for m in o.get("media") or []:
                fd = m.get("fidelity")
                if fd not in FIDELITY:
                    errs.append(f"选项 {o.get('id')} 的样例需要 fidelity：{'/'.join(FIDELITY)}")
                elif asks & LOOK_ASKS and fd not in LOOK_OK:
                    errs.append(f"选项 {o.get('id')} 问的是观感（{'/'.join(sorted(asks & LOOK_ASKS))}），{fd} 样例看不出区别："
                                "改用 overlay（在粗稿上叠加/生成近成品效果）、lookdev（固定画面单独比较）或 final（成品局部）")
    if t == "tune" and not q.get("playground"):
        errs.append("tune 决策需要 playground 字段")
    return errs
