# 样例、动效、目录与设置规范

### 0.10 视觉样例怎么做
用 Python、SVG、canvas、CSS 画出来的"水彩""写实""蜡笔"示意图很粗糙，会误导判断。画面类（artwork）决策的样例必须是真实图像：

| 优先级 | 来源 | 做法 | origin |
|---|---|---|---|
| 1 | 用户素材 | 从 inbox 挑图，或 `samples.py crop` 裁局部、`samples.py shot <网址> --selector …` 截参考网站某个区块、`samples.py frames` 视频抽帧 | `inbox` |
| 2 | 检索素材 | 图片搜索/案例库，每个选项 2–3 张，或作品页截图 | `search` / `screenshot` |
| 3 | 生图工具 | constraints.yaml 的 `image_generation` 配置了工具时，固定主体与构图，只变风格 | `generated` |
| — | 代码绘制 | 只用于 code-native 决策 | `rendered` |

- inbox 里有能代表某选项的素材时必须优先用。
- **分辨率**：样例要经得起放大看细节。图片长边至少 1200px（能拿到原图就用原图）；检索结果里的小缩略图要点进去找原图，找不到再用并在 caveat 注明；网页截图用 `samples.py shot`（默认 2 倍像素密度）；需要比较笔触、纹理、线宽等细节时，额外放一张 `samples.py crop` 裁出的局部特写。决策页会给长边不足 1000px 的图片标「低分辨率」。
- 同一决策的样例使用相同内容，只让被比较的维度变化；做不到时用 `caveat` 写"只看笔触，配色与本选项无关"。连续谱用 `scale` 做 4–5 档。
- 检索图只用于做选择，不进入成品；出处记在 `media/samples/<ID>/sources.yaml` 和 `credit`。不用受保护的角色、品牌形象作样例。

#### 0.10.1 动效的固定说法
描述动效只用以下四个词，不用"呼吸""灵动"这类可以有多种理解的词：

| 说法 | 含义 | 例子 |
|---|---|---|
| 摆动 | 在两个状态之间来回 | 透明度 0.6↔1 往复、左右轻晃 |
| 流动 | 单向持续推进，不回头 | 纹理持续平移、粒子持续漂移、渐变持续旋转 |
| 脉冲 | 平时静止，按事件或间隔触发一次 | 数据刷新时闪一下、新消息时扩散一圈 |
| 交互触发 | 只响应用户操作 | 悬停、点击、拖拽、滚动 |

#### 0.10.2 动效的确认与验证
1. **选择**：`dimension: "motion"` 决策，每个选项是可播放样张，按真实速度播放至少一个完整周期。
2. **实现前复述**：在 traits.md 的动效规格里，用一句话写清：什么在动、用哪种说法动、周期多长、覆盖多大区域、什么不动。写进本阶段 gate 决策的 context，让用户确认后再实现。
3. **实现后交证据**：一段完整周期的录屏（或可播放的页面），加上实测数据：运动区域占画面的比例、实际周期、帧率。与第 2 步的规格对不上就不能过闸门。
4. 所有动效提供 `prefers-reduced-motion` 降级；页面不可见或窗口失焦时降低帧率或暂停。

### 0.11 目录结构与 git 管理
单期项目的所有文件都在项目下的 `.taste-design/`（可用环境变量 `TASTE_DESIGN_DIR` 改名），按 git 处理方式分四个区。`gate.py init` 会生成 `.taste-design/.gitignore`、`README.md`，LFS 策略时还有 `.gitattributes`。

多期项目使用 `.taste-design/project.json` 登记期，每期各自拥有完整的四区，跨期稳定内容单独放 `shared/`。每期的 `.gitignore` / `.gitattributes` 由该期的 `gate.py --phase ID media ...` 生成；不要用某一期的策略覆盖其他期。

```text
.taste-design/
  project.json
  phases/P1/{record,work,media,cache}/...
  phases/P2/{record,work,media,cache}/...
  shared/{brand.md,design-system/}
```

`shared/` 不是第五个阶段区，也不是历史归档：只放跨期仍有效、已由用户确认的品牌与设计系统。P2 的页面范围、答案、验收与当前工作必须留在 `phases/P2/`。

```
.taste-design/
  README.md  .gitignore  [.gitattributes]        # 由 gate.py 生成
  record/            ✅ 提交：决策过程与结论（小、可 diff、可审阅）
    state.json  scope.json  config.json
    decisions.md  pending-review.md  changelog.md  refs.yaml  notes.md  progress.md
    brief/{brief.md, traits.md, content.yaml, constraints.yaml}
    decisions/<ID>/{question.json, answer.json, answer.superseded-*.json}
    summary/{README.md, <ID>.md, thumbs/}         # 自动生成的决策总览与摘要卡（含约 360px 宽的缩略图）
  work/              ✅ 提交：文本设计稿
    wireframe/  variants/{variants.html, archive.md}  proto/  playgrounds/  tokens.css  theme/{axes.json, gallery.html}
    assets/spec.md  rollout/{pages.json, overview.html}
    qa/{report.md, manual-checks.md, asset-compare.html, theme-matrix.json}  handoff/{DESIGN.md, HANDOFF.md}
  media/             ⚙️ 按策略：二进制素材（默认不提交）
    inbox/{images, video, prototypes, brand}/  samples/<ID>/  baseline/
    shots/{rollout, qa, gates}/  keyframes/  assets/{benchmark, derived}/
  cache/             ❌ 永不提交：运行时与临时文件
    runtime/ (等待状态、服务端口)  snapshots/gate-N/  export/  以及其他临时文件
```

**放文件的规则**
- 决策过程文字、结论 → `record/`；设计稿（HTML、CSS、JSON、Markdown）→ `work/`；图片、视频、截图 → `media/`；用完即弃的东西 → `cache/`。
- 多期项目下的上述四个区均指 `phases/<当前 ID>/`；跨期稳定基线才写 `shared/`，且必须有来源。不要把某一期的 `record/` 或 `work/` 直接搬到共享层。
- 不要在 `.taste-design/` 根下另建目录；hook 会拦截。
- 不要把截图、样例图写进 `record/` 或 `work/`（work 里的页面通过相对路径 `../../media/...` 引用素材）。
- 成品代码不放在这里，写到项目源码里（见第 9 节）。

**素材策略**（`record/config.json` 的 `media`，用 `gate.py media <策略>` 切换，会重写 git 文件）

| 策略 | 效果 | 适合 |
|---|---|---|
| `ignore`（默认） | media/ 不提交；团队成员通过 `record/summary/` 的摘要卡和缩略图了解每个决策 | 大多数项目 |
| `lfs` | media/ 用 Git LFS 提交 | 需要完整保留素材、团队都装了 Git LFS |
| `commit` | media/ 直接提交 | 素材很少的小项目 |

**决策记录随仓库同步**：每次作答都会更新 `record/decisions/<ID>/answer.json`、`record/decisions.md` 和 `record/summary/`。建议每过一个闸门提交一次（例如 `git add .taste-design && git commit -m "design: 通过闸门 N"`），这样设计决策和代码改动在同一条历史里，评审时能看到"为什么这样做"。智能体只在用户要求时提交。

**旧项目迁移**：项目里有旧版 `design/`（含 `state.json`）时运行 `gate.py migrate`（先用 `--dry-run` 看计划）。它会把文件分到四个区、改写 question.json 和 work/ 页面里的素材路径、把旧 `dist/DESIGN.md`、`dist/HANDOFF.md` 搬到 `work/handoff/`、生成全部摘要卡；项目自己的 `design/` 中与本 skill 无关的文件不会动。

旧单期 `.taste-design/` 不会自动转换为多期。需要转换时先保留原目录作为单期项目，明确每一期对应的阶段、范围和已验收内容，再由用户决定是否复制或另建；脚本不会猜哪份历史属于 P1、P2。

### 0.12 设置项与主题一致性
用户难以在几个布局或样式之间取舍时，可以把它们做成最终产品里的设置项，但有代价：每多一个取值，就多一套要设计、维护、测试的界面；大多数用户从不改设置，**默认值仍然必须是选定的最佳方案**。

**什么能做成设置**
- 适合：不同用户会因自己的使用情境合理地偏好不同选项——明暗、密度（紧凑/宽松）、减弱动效、强调色、列表/网格视图。
- 不适合：设计者自己拿不定主意——方向气质、品牌感、主插画风格。这些决定"产品是什么"，选不出来就再出一轮对比或折中方案，而不是交给用户。
- 判断：能说出"哪类用户、在什么场景会选非默认值"（axes.json 的 `who`）吗？说不出来就不做成设置。

**流程**
1. 智能体在**可能**属于用户偏好的决策上设 `allow_setting: true` 和 `setting_axis`。范围、参考拆解、基准资产等决策不允许。
2. 决策页上出现「都要，做成设置项」：用户保留 2–4 个选项并指定默认值。阶段 0 选了外观不开放时，这个选项是灰的；服务和 `gate.py record` 也会拒绝。
3. 智能体收到这种答案后先分类：
   - **用户偏好** → 写进 `work/theme/axes.json` 的 `axes`（或作为 `presets`），填 `who`、`source_decision`。
   - **只是难以取舍** → 写进 `declined`（`reason`），并建一个决策（附推荐和理由）请用户选定一个，把它的 ID 填到 `resolved_by`。
4. 阶段 5 定稿规格、令牌、主题画廊，并为每套预设建一个验收决策（`approved_by`）。阶段 8 跑主题矩阵。

**`work/theme/axes.json`**（完整字段见 `scripts/theme.py` 顶部）

```json
{
  "prototype": "../proto/v003.html",
  "invariants": ["字号比例 1.25", "8px 间距网格", "线性图标 1.5px", "信息层级与元素顺序不变", "文案语气"],
  "presets": [{"id": "cool", "label": "冷色", "source_decision": "D04-dir", "approved_by": "D21-preset-cool"}],
  "axes": [
    {"id": "mode", "label": "明暗", "values": ["light", "dark"], "default": "light",
     "who": "夜间使用或长时间使用的用户", "source_decision": "D07-mode"},
    {"id": "density", "label": "密度", "kind": "layout", "area": "列表与表格",
     "values": ["comfortable", "compact"], "default": "comfortable", "who": "需要一屏看到更多信息的用户", "source_decision": "D08"}
  ],
  "default": {"preset": "cool", "mode": "light", "density": "comfortable"},
  "max_combinations": 12,
  "contrast_pairs": [["--color-text", "--color-bg", 4.5], ["--color-on-accent", "--color-accent", 4.5]],
  "declined": []
}
```

**一致性规则（闸门 5、6 检查）**
- **不变项**：`invariants` 至少 3 条。字号比例、间距网格、圆角体系、图标风格、信息层级与元素顺序、交互方式、文案语气不随主题变。
- **数量上限**：预设最多 3 套（每套都是完整设计、单独验收）；独立维度最多 4 个，每个 2–4 个取值；组合数（预设数 × 各维度取值数之积）默认不超过 12，最多 24。组合太多测不完，就说明设置太多了。
- **预设优先，单项次之**：先给几套整体设计好的预设，再加少数互相独立的开关（明暗、密度、动效）。不提供自由取色器；强调色只从精选色板里选。
- **三层令牌**：原始值层 → 语义层（背景、文字、强调、边框、间距等级）→ 组件层。**组件只引用语义层**，不直接写色值。`work/tokens.css` 里默认值写在 `:root`，每个非默认值写成 `[data-<维度>="<值>"]`，预设写成 `[data-preset="<id>"]`，需要时写组合选择器（如 `[data-preset="warm"][data-mode="dark"]`）。gate 会检查每个非默认值都有覆盖。
- **布局类设置只能是局部的**：`kind: "layout"` 的维度必须写 `area`，例如侧栏折叠、列表/网格、卡片密度。同一套组件、同一个元素顺序，只用 CSS（grid 区域、间距令牌）切换；不允许整页换结构，也不写两套模板。
- **插画与图片资产**：要么风格保持不变，通过色调令牌（单色、双色叠加）适应主题；要么每个预设配一整套资产，并各自有基准资产与细节规范（4.2、4.3）。
- **设置页本身**：`customization_page` 里预设用带实时预览的卡片，维度用分段控件，提供「恢复默认」；选择要持久保存，并尊重系统的明暗和减弱动效偏好作为初始值。

### 0.13 样例保真度要和问题匹配
粗稿（线框、灰模、占位图、草图）离成品太远，在它上面比较配色、插图、材质、灯光、角色或风格，几个选项看起来都差不多。所以**按问题选保真度**：布局类问题用粗稿，观感类问题用接近成品的样例。网页、应用、含 3D 或插画的场景都适用。

| 决策的 `asks` | 内容 | 可用的样例保真度（media 的 `fidelity`） |
|---|---|---|
| 布局类：`layout` `composition` `scale` `camera` `hierarchy` | 布局、构图、比例、镜头、信息层级 | 任意，`rough` 粗稿、`proxy` 替身即可 |
| 观感类：`color` `typography` `illustration` `material` `lighting` `character` `style` `texture` `atmosphere` | 配色、字体、插图、材质、灯光、角色造型、风格、氛围 | 只能用 `overlay`、`lookdev`、`final`、`reference` |

- 样例里用了 `rough` 或 `proxy`，决策就必须写 `asks`；观感类问题配粗稿会被校验拒绝。
- 一个决策不同时问两类：先在粗稿上定布局，再在定好的布局上比观感。
- 让观感类问题看得出区别的做法：
  1. **叠加（overlay）**：布局定下后，在同一个粗稿画面上叠加近成品效果（手绘、合成，或用生图工具在粗稿基础上生成），布局和镜头不变，只改被比较的观感。
  2. **单独比较（lookdev）**：把材质、配色、角色造型等放在一个固定的标准画面里比较，与布局解耦。
  3. **成品局部（final）**：先把一个代表性局部做到成品品质，作为基准，后续选项都在它上面比较差异。
  4. **替身（proxy）**：布局阶段就用现成素材或资产代替纯占位，让比例和空间感更接近真实（只用于布局类问题）。
- 选项之间的差异在当前保真度下看不出来时，不要硬问：合并选项，或等有更高保真度的样例再问。
- 叠加和生成的效果图只用于选择，实现以真实资产和代码为准；选定的效果图作为目标图写进资产规范（4.2）。
