# 决策通道与文件协议

### 0.7 交互通道
选通道看的是**宿主能否在提问的同一处把图片和样张展示给用户**，而不是它是不是命令行。命令行智能体、只有文字选项框的图形界面智能体、提问工具只能显示文字的编辑器插件，都属于"不能展示图片"，一律走 web。

能力自检（会话开始时回答，写进 record/decisions.md）：
1. 我能否运行一个本地后台进程，且用户能用浏览器打开它？（同一台电脑，或 SSH 远程可端口转发）
2. 我的提问/对话界面能否**内嵌显示**图片和 HTML 样张，并让用户看着它们作答？只能输出图片路径、Markdown 图片不渲染、只能发纯文字选项 → "否"。拿不准 → "否"。

| 通道 | 条件 | 做法 |
|---|---|---|
| **web**（默认） | 自检 1 为"是" | `decide_server.py serve`；SSH 远程时告诉用户在本地运行 `ssh -L 8765:localhost:8765 <主机>` |
| **inline** | 自检 1 "否"、自检 2 "是" | 把决策按 question.json 渲染为对话中可见的页面，图片与样张必须显示出来；用户回复"D03=B 备注…"；用 `gate.py record D03 --choice B --note … --quote "用户原话"` 登记 |
| **static** | 都不满足，但用户能在本机打开文件 | `decide_server.py export` 生成 `cache/export/index.html`，用户选好后点"复制回复文本"粘贴回对话；同样用 `gate.py record` 登记 |
| 纯文字 | — | **禁止用于视觉决策**。三种通道都不可用时停下来，告诉用户缺什么 |

- 自检 1 为"是"时**必须**用 web。
- 换通道：`gate.py channel inline|static --reason "…"`，并告诉用户原因。web 通道下 `gate.py record` 会拒绝对话作答；唯一例外是全部阶段已经通过后，用户在对话中明确答复可选文档同步建议，可用 `role=documentation-sync`、`--by user --via chat --quote "用户原话"` 登记，无需重复确认或切换通道。
- **所有通道都先通知再等待**：web 在对话中给实际可点击地址、本轮可作答 ID 与标题、页面提交方式；inline 先展示实际样张、题目和回复格式；static 先重新导出并提供可打开的文件链接、待答项及复制回复方法。详见 runtime.md。服务启动日志或浏览器自动打开不能代替对话消息。

### 0.8 决策协议

#### 0.8.1 什么走决策页，什么可以代定
- **主要决策**必须建成决策文件，在决策页作答：交付边界、方向/方案、主题隐喻、参考拆解、笔触/写实度/插画风格、主色与字体、布局自由度、基准资产、每个阶段的验收。交付边界和可选文档同步都必须由用户确认，无人值守也不得代答。
- **次要事项**（例如某个辅助色、旧资源如何归档）可以由智能体按推荐项直接执行，用 `gate.py assume --topic … --choice … --why …` 记录。它们进入 `record/pending-review.md`。
- **代定不等于跳过确认**：有人值守时，本阶段代定的每一项都必须逐条写进本阶段 gate 决策的 context（或作为 media 展示），让用户随验收一起点头；gate.py 会检查。影响流程结构的事（跳过阶段、省略灰模、沿用现有布局）不能用 assume，必须建决策。交付前再用 `role: "pending-review"` 决策集中复核一次。
- **对话回复的规则**：每条回复最多一个需要用户回答的问题，并且它应该指向决策页。**不要在回复末尾附带"顺便问一下"的问题**——用户通常只回答主问题，末尾的问题会被遗漏。次要问题要么用 assume 代定，要么建成决策。
- **仅设计最终交付的例外**：可以在交付说明最后建议用户是否将设计系统约束关联到项目文档；这是已完成交付后的可选后续工作，不需要等待答复或预先建题来阻塞收口。用户明确要求同步时再记录 `role=documentation-sync` 的真实确认，详见阶段 9。

#### 0.8.2 决策文件
每个决策的题目和答案在 `record/decisions/<ID>/`，样例文件在 `media/samples/<ID>/`。ID 用 `D` + 两位序号 + 短名。`question.json` 由智能体写；`answer.json` **只能**由决策服务或 `gate.py record` 写入，写入时会自动生成摘要卡 `record/summary/<ID>.md`。

```json
{
  "id": "D03-brush",
  "stage": 1,
  "type": "single",
  "role": "reference-breakdown",
  "reference": "某部复古科幻电影",
  "title": "这部电影里你要的是哪一部分？",
  "context": "这部电影里有几个风格完全不同的场景，先选定再做方向。",
  "depends_on": ["D02-scope"],
  "sample_kind": "artwork",
  "options": [
    {"id": "A", "label": "霓虹街头", "desc": "雨夜、高饱和霓虹",
     "media": [{"type": "image", "src": "A1.jpg", "origin": "search", "credit": "https://…"}]},
    {"id": "B", "label": "太空舱室内", "recommended": true,
     "media": [{"type": "image", "src": "B1.jpg", "origin": "search", "credit": "https://…"},
               {"type": "image", "src": "B2.png", "origin": "inbox", "ref": "I04"}]}
  ]
}
```
字段：
- `type`：`single` 单选 / `multi` 多选 / `scale` 刻度 / `tune` 拖动调参（需 `playground`）/ `gate` 阶段验收（默认"通过/不通过"，不通过必须写原因）。
- `role`（可选）：`scope` / `delivery-boundary`（阶段 0，非视觉单选，固定选项 design-only / design-and-implement）/ `documentation-sync`（阶段 9，可选非视觉单选，固定选项 update / defer）/ `reference-breakdown`（需 `reference`）/ `direction`（每个选项需 `intensity`：克制/中等/大胆，且至少一个"大胆"）/ `asset-benchmark` / `pending-review` / `skip`（需 `skip_stage`）。闸门按角色检查。
- `dimension: "motion"`：动效类决策。每个选项必须有可播放的样例（`video` 或 `html`，按真实速度播放，至少一个完整周期），并有 `motion` 字段写清「什么在动、怎么动、周期多长、什么不动」（见 0.10.2）。
- `sample_kind`：`artwork`（画面类：插画风格、笔触、写实程度、摄影风格、氛围、主题隐喻、参考拆解）或 `code-native`（配色、字体、版式、图标/SVG、动效、整页方案）。
- `media[].type`：`image` / `html` / `video` / `link`。`src` 不带前缀时相对 `media/samples/<ID>/`；`@/` 开头相对 `.taste-design/`（如 `@/work/variants/variants.html#embed=V3`、`@/media/baseline/home.png`）；也可以是 http(s)。
- `media[].origin`（必填）：`inbox`（需 `ref`）/ `search`（需 `credit`）/ `screenshot` 外部页面截图（需 `credit`）/ `generated` 生图工具 / `rendered` 代码渲染（含本项目页面截图）。**artwork 决策禁止 rendered。**
- `media[].viewport`：html 样张按此宽度渲染再缩成缩略图；`display: "wide"` 占满整行大尺寸显示。
- `visual: false`：非视觉问题（范围、技术约束、文案），允许选项不带 media。
- `allow_setting: true` + `setting_axis`：允许用户回答「都要，做成设置项」（仅 single / scale；见 0.12）。答案里会多一个 `setting: {axis, values, default}`，`choice` 是默认值。
- `media[].attrs`：页面样张加载后在其 `<html>` 上设置 `data-*` 属性，例如 `{"mode": "dark", "preset": "warm"}`，用同一个原型预览不同主题。`media[].trusted: true`：允许样张页面与决策页同源（主题画廊需要）。
- 校验不通过的决策不会出现在决策页上，也过不了闸门。

#### 0.8.3 决策页上的查看方式（用户侧）
- 点卡片上的图片、页面样张或 ⤢ 按钮，进入全屏查看器；点卡片下方的文字选择。
- 查看器：滚轮或双指缩放、拖动平移、`1:1` 看原始像素、`←/→` 切换、`C` 并排对比两个选项（缩放和平移同步，适合比较笔触和纹理细节）、`Enter` 直接选择当前选项、`F` 全屏、`Esc` 关闭。页面样张可切换 375 / 768 / 1440 宽度并在里面滚动。
- **回顾**：页面顶部切到「回顾」标签，可以按阶段筛选、搜索，查看之前所有阶段已作答的决策：当时的题目、全部选项和样例（同样能全屏查看、对比）、选了什么、备注、作答时间，以及回退前作废的旧答案。回顾是只读的；要改已通过的决定，在对话里告诉智能体，它按第 10 节回退并重新请你确认。
- 这些是现成功能，智能体不需要另做大图页面；只需保证样例本身分辨率足够（见 0.10）。

#### 0.8.4 递进与节奏
- 只建当前阶段（含并入它的阶段）的决策。决策页只显示前置决策（`depends_on`）已答的决策，同时最多开放 3 个（互不依赖的一批决策可用 `serve --max-open N` 一次放出）。
- 每个决策的选项控制在 4 个以内；多选题没被勾选的候选统一记为放弃，不再追问。
- 后一个决策依赖前一个的结论时必须写 `depends_on`，并等前一个答完、按答案生成后一个的样例再建。
- 每个阶段的最后一个决策是 `gate` 决策，`depends_on` 本阶段其他所有决策，media 放本阶段成果。

答案提交后按 [运行协议](runtime.md) 读取、落实并精确 ack。所有阶段验收通过后直接推进，用户不需要另发继续指令。
