## 1. 创意简报（阶段 1）

开始前：`gate.py check 1`。快速轨道下本阶段同时包含阶段 3（视觉发散），两者一起验收。

### 1.1 收集：由谁、从哪里
- **主收集人是用户**。图片、视频等原始素材放 `media/inbox/`，素材登记表 `record/refs.yaml` 和文字描述 `record/notes.md` 放 record/；用户在对话里给的链接、图片，由智能体归档进去。
- **智能体可补充**，但必须标 `source: agent`；每次补充不超过 3 条；经用户确认后才进入特征表。
- **推荐的外部来源**：网站案例库（Godly、Awwwards、Land-book、Lapa Ninja、SiteInspire）、界面案例库（Mobbin）、视觉灵感（Dribbble、Behance、Are.na、Pinterest）、产品自身的品牌或美术资产。

### 1.2 参考拆解（每个整体参考必做）
用户用一部影视、一款游戏、一个品牌来描述想要的感觉时，这个参考往往包含多个风格不同的子世界（例如一部电影里同时有霓虹街头、太空舱室内和荒漠外景）。**在做任何方向之前**，为 scope.json 里的每个参考建一个 `role: "reference-breakdown"` 决策：
- 每个子世界一个选项，配 2–3 张真实画面（检索图或用户素材，`sample_kind: "artwork"`）。
- 允许多选组合（`type: multi`），用户在备注里写"要 A 的材质 + B 的色调"。
- 结论写进 traits.md，标注来源决策 ID。

### 1.3 数量上下限
| 素材类型 | 下限 | 推荐 | 上限 |
|---|---|---|---|
| 参考网站 | 2 | 3–5 | 8 |
| 情绪板图片 | 0 | 5–15 | 25 |
| 反面参考 | 0 | 1–3 | 5 |
| 动效视频 | 0 | 1–3 | 5（每个 ≤ 30 秒） |
| 已有原型 | 0 | — | 3 |

### 1.4 创意完整度
| 级别 | 必须包含 |
|---|---|
| L1 最低 | 一句话主题隐喻 + 3 个形容词 + ≥ 2 个带批注的参考 + 内容清单 |
| L2 标准（默认） | L1 + 情绪板 + 反面参考 + 约束文件 |
| L3 完整 | L2 + 动效视频 / 已有原型 / 品牌或美术资产 |

未达 L1 不开始。主题只是抽象形容词时，建决策提出 3 个具体隐喻，每个配真实参考图。

### 1.5 素材登记 record/refs.yaml
```yaml
- id: R1
  url: https://example.com
  source: user            # user | agent
  borrow: [color, layout] # color | layout | typography | texture | motion | illustration | tone | interaction
  like: "首屏大字压在插画上的层次感"
  avoid: "下半页卡片太模板化"
  weight: high            # high | mid | low
```
图片命名 `I03_粗颗粒纸张.jpg` 并用 `file` 登记；视频抽帧到 `media/keyframes/` 且用户补一句动效描述；品牌资产标明不可变项并写入 constraints.yaml。

### 1.6 特征表 record/brief/traits.md
| 编号 | 维度 | 特征描述 | 来源 | 权重 |
|---|---|---|---|---|
| T01 | color | 冷蓝主色配浅灰底 | D04-ref=B | high |
| T02 | layout | 不对称分栏、大面积留白 | D05-dir=V3 | high |

每个维度 2–5 条，列出冲突和缺口；冲突和缺口各建一个带样例的决策，不在对话里文字提问。文件末尾写 `同步至闸门：N`。

**图层表**（主题带质感或动效时必填，闸门 4 检查）：把画面分层，逐层定下有无质感、动不动，避免后期才发现"卡片该不该透明""卡面要不要动"。

| 图层 | 质感 | 动效（用 0.10.1 的说法） | 备注 |
|---|---|---|---|
| 背景 | 有：颗粒噪点 | 流动，周期 40s | 失焦时暂停 |
| 容器（卡片、面板） | 无，不透明 | 不动 | 保证数据可读 |
| 数据（图表、数值） | 无 | 脉冲：数值更新时 | — |
| 文字 | 无 | 不动 | — |

**动效规格**（有动效时必填）：每个动效一行，写什么在动、哪种说法、周期、覆盖区域、什么不动（见 0.10.2）。

### 1.7 内容清单 record/brief/content.yaml、约束 record/brief/constraints.yaml
```yaml
# content.yaml
page: home
sections:
  - {id: hero, required: true, priority: 1, purpose: "一句话说清产品是什么", headline: "...", cta: {label: "...", href: "..."}}
  - {id: features, required: true, priority: 2, items: 3-4}
# 应用类项目（product_type: app）必填：状态表。每个状态都要在原型里看得到
states:
  - {id: loading, where: "所有数据区", desc: "首次加载与刷新"}
  - {id: empty, where: "列表", desc: "没有数据时"}
  - {id: error, where: "全局", desc: "请求失败、断线、重连中"}
  - {id: threshold, where: "指标卡", desc: "数值超过阈值"}
  - {id: permission, where: "操作按钮", desc: "无权限"}
```
```yaml
# constraints.yaml —— 每条都要能追溯到用户原话或决策 ID（写在行尾注释）
output: single-html           # single-html | static-site | framework（注明框架）
breakpoints: [375, 768, 1440]
accessibility: { contrast: WCAG-AA, reduced_motion: true, keyboard: true }
performance: { max_page_kb: 1500, max_requests: 30 }
fonts: { allowed_sources: [google-fonts, self-hosted], license_checked: true }
immutable: [logo]             # 来源：用户原话或决策 ID
image_generation: none        # none | 工具名或工作流路径
target: web                   # web | webview（嵌入客户端）| native（原生/GPU 渲染）——非 web 时交付要附移植说明
deliver_to: site/              # 新建项目的成品写到项目里的哪个目录（改版项目填现有源码位置）
```
文案未定写 `TBD`；占位文案标 `draft: true`，交付前清零。

### 1.8 收集轮次（最多 3 轮）
1. 投放：用户放素材、给主题和形容词。
2. 整理与决策：产出四个文件初稿；参考拆解 → 冲突与缺口 → 风格问题，按依赖顺序逐个建决策。
3. 确认：更新文件、同步、建 gate 决策。仍未解决的写进 brief.md 的"待定项"，留给方向对比解决。

### 1.9 record/brief/brief.md 模板
```markdown
# 创意简报 v{n}
同步至闸门：{N}
## 范围（引用 scope.json：范围、布局自由度、轨道）
## 一句话主题
## 形容词（3 个）
## 参考拆解结论（附决策 ID）
## 目标受众与他们应该产生的感受
## 关键特征（引用 traits.md 中 high 权重编号）
## 明确不要
## 约束（每条附来源）
## 待定项
```

**闸门 1**：gate 决策 approve → `gate.py pass 1`。
