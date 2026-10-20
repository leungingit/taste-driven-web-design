## 阶段 0：启动与范围

开始前：`gate.py check 0`。这一阶段决定项目怎么走，**必须在出任何视觉方案之前完成**。

本技能的阶段和布局检查面向网站、落地页与应用界面；原生界面可按 constraints.yaml 的 target 约定移植。游戏场景美术、角色建模、绑定与动画制作不直接套用网页区块的布局相似度。涉及这些任务时先明确本轮可适用的界面设计范围和交付边界；无法映射时指出不适用的阶段与所需制作流程，不为满足闸门把目标替换为网页样张或三维基础体，也不承诺现有检查能验收此类成品。

### S0.1 第一个决策：范围与自由度（role=scope）
建一组非视觉决策（`visual: false`，同时开放），让用户一次回答：

| 问题 | 选项 | 写入 scope.json |
|---|---|---|
| 项目类型 | 从零新建 / 已有产品改版 | `mode`: new / redesign |
| 产品形态 | 网站/落地页（内容为主，滚动阅读）/ 应用界面（工具、后台、仪表盘、客户端） | `product_type`: site / app |
| 交付边界（独立决策，见下文） | 设计并修改当前工程实现 / 仅设计系统与工作原型，不修改当前工程实现 | `delivery_mode`: design-and-implement / design-only |
| 改动范围 | 只做一个页面 / 先做样张页、定稿后全站铺开（推荐）/ 全站同时做 | `scope`: single / sample-then-rollout / all-pages |
| 布局自由度 | 保留现有布局只换视觉 / 页内可重排 / 可重构页面结构（业务逻辑不变） | `layout_freedom`: keep / rearrange / restructure |
| 流程轨道 | 完整轨道 / 快速轨道（简报与方向合并验收，playground 可跳过） | `track`: full / fast |
| 外观是否开放 | 外观参数在设计期定死 / 也让最终用户在产品里调整（主题、配色、密度、动效开关等） | `user_customizable`: false / true；为 true 时 `customization_page` 填设置页名称，并列入本期页面。只有选 true，后续决策才能「做成设置项」（见 0.12） |

交付边界必须单独建一个阶段 0 的非视觉单选决策，不能藏在备注中或由智能体代选（无人值守也需用户选择）：

```json
{"id":"S0-delivery","stage":0,"role":"delivery-boundary","type":"single","visual":false,
 "title":"本期设计是否同时修改当前工程实现？",
 "context":"两种方式都提供可运行原型与设计规范。仅设计不修改当前工程，交付时可建议关联项目文档，是否更新由你另行决定。",
 "options":[
   {"id":"design-and-implement","label":"设计并修改当前工程实现","desc":"将确认的设计落实到本期实际源码，并做工程验证。"},
   {"id":"design-only","label":"仅设计系统与工作原型","desc":"生成原型、令牌、资产与规范，不修改当前工程实现。"}]}
```

用户选择后，将同名选项 ID 写入 `scope.json.delivery_mode`，按原答案版本落实并 ack；网页回顾、静态导出和摘要卡均保留此题及选择。闸门 0 检查题目格式、用户身份、答案与范围的一致性，并将决策 ID、模式、答案时间戳固定到状态中。后续只改范围字段、修改答案或删掉模式都不能扩大权限；改变边界先 `gate.py rollback 0 --reason …` 再重新作答，旧答案保留在回顾里。

- `design-and-implement`：闸门 0 通过后，可在已批准范围内修改工程实现。
- `design-only`：可以读取工程来确认真实约束；设计系统、工作原型、组件样例、最终设计资产都保存在本期设计目录。默认不改项目文档；交付最后建议用户是否将设计系统约束写入项目文档，得到独立的 `role=documentation-sync` 用户确认后，才允许编辑 `AGENTS.md`、`docs/design-system.md` 的关联说明（见阶段 9）。不能修改应用入口、业务组件、工程配置、依赖或生产资产。外观设置也只在原型里演示。
- 初始化每一期时自动生成 `record/implementation-baseline.json`，保存工程文件的路径、权限与 SHA-256 摘要，不复制文件内容；以初始化时实际工作区为基准，已有未提交改动也算现状。每次阶段 `check/pass/skip` 及流程判定会检查边界；仅设计发现工程文件新增、删除、内容或权限变化就拒绝放行。并发人工修改同样会被报告，先核对归属，不自动回滚、不刷新基线掩盖差异。
- 指纹不覆盖设计容器、`.git`、`node_modules`、Python 虚拟环境与缓存，以及项目根的 `dist/build/target/.next/coverage/.pytest_cache` 构建输出；这些排除目录不能用作源码交付位置。`stage_guard.py` 在已启用且验证有效的宿主上额外拦截写入；Shell 等未经过 hook 的修改由阶段指纹检查兜底。这是流程门禁，不是操作系统沙盒。
- 旧版已过闸门 0 且没有交付模式的项目可沿用原流程，不伪造历史选择；重新确认范围时必须补选。缺少初始化指纹的旧项目不能直接宣称仅设计检查通过，应核对工程现状后建立新设计期。跨期复用设计系统不继承交付授权，每期分别选择。

多期项目还要确认**本期从哪里接续**，并在 `scope.json` 写入：

| 问题 | 选项 | 写入 scope.json |
|---|---|---|
| 本期关系 | 独立新建 / 在上一期基础上增量演进 / 重构上一期已交付范围 | `phase_relation`: independent / extend / rework |
| 复用基线 | 不继承 / 只复用品牌与设计系统 / 明确列出继承文件 | `inherit_mode`: none / shared / explicit；`inherits`: 相对 `.taste-design/` 的路径列表；决策需写成原题或答案的文件路径 |
| 起点 | 从阶段 0 完整开始 / 沿用已确认品牌与布局，从灰模或样张开始 / 从原型、令牌或区块打磨开始 | `start_stage`: 0 / 2 / 3 / 4 / 5 / 6（必须说明被跳过的验收来源） |

`start_stage` 只表示本期从哪里开始制作，不等于自动复用旧期验收。`phase_relation=extend` 或 `rework` 时，必须指出父期、被继承的产物和仍需重新验收的部分；不能把父期的 `passed` 直接抄成本期已通过。若继承基线被修改，先按变更管理确认影响范围。

再从用户已给的信息里整理以下清单（不确定就作为问题加进决策）：
- `pages`：**全部可导航的目的地**，不只是用户给的那一屏。从截图、现有代码、路由表里找出所有页面、分页（tab）、侧栏/顶栏入口、设置页及其分页、常用弹窗和抽屉，逐个让用户确认本期做不做。本期不做的也要列出：`{"name": "设置 → 账户", "in_scope": false, "reason": "下期"}`。
- `source_dirs`：生成页面所用的源码目录（生成脚本、组件、着色器、配置）；设计并实施时每过一个闸门自动快照。仅设计时读取以了解现状，不复制工程源码；工程指纹独立于此清单，不能通过漏列目录绕过检查。
- `references`：用户提到的影视、游戏、品牌等**整体参考**（例如"像某部电影""像某款游戏"）。
- `asset_types`：改版会影响到的内容资产类型（头图、插画、图标、示意图、封面……）。主动列出，不要等用户提出。

初始意向只有文字时，保留用户原话，进入阶段 1 后先按 1.1.1 邀请补充目标参考图，再做参考拆解或主题选项。现状基线截图只说明当前界面，不自动代表目标意向；用户明确表示希望保留其视觉特征时才作为目标参考。

```json
{"mode": "redesign", "product_type": "app", "scope": "sample-then-rollout",
 "layout_freedom": "rearrange", "track": "fast", "delivery_mode": "design-only",
 "user_customizable": true, "customization_page": "设置 → 外观",
 "phase_relation": "extend", "inherit_mode": "shared", "inherits": ["shared/brand.md", "shared/design-system"],
 "start_stage": 3,
 "pages": ["总览", "详情", "设置 → 外观", {"name": "设置 → 账户", "in_scope": false, "reason": "下期"}],
 "references": ["某部复古科幻电影"], "asset_types": ["头图", "插画"], "source_dirs": ["src/ui", "tools/gen"]}
```

单期项目不必填写上述接续字段。多期项目的 `phase.json.inherits` 与本期 `scope.json.inherits` 必须一致，空列表也参与比较；`shared` 模式只允许 `shared/` 下的路径。绝对路径、`..` 路径段和越出容器的符号链接都会被拒绝。起点仍受轨道裁剪约束：例如声明 2 但保留布局省略灰模时，进入后继有效阶段；以 `next --json` 和通过闸门后的实际阶段为准。

### S0.2 改版项目先截现状基线
`mode: redesign` 时，`media/baseline/` 里每个页面至少一张现状截图（`samples.py shot <页面地址> --out .taste-design/media/baseline/<页面>.png`，需要时加 `--width 375` 截手机）。这是**前置条件，不能跳过**：截图工具装不上或页面需要登录时，请用户提供截图或协助登录。

### S0.3 闸门 0
gate 决策的 media 放基线截图。通过后把 gate.py 打印的阶段序列告诉用户。
