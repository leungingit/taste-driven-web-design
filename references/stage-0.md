## 阶段 0：启动与范围

开始前：`gate.py check 0`。这一阶段决定项目怎么走，**必须在出任何视觉方案之前完成**。

### S0.1 第一个决策：范围与自由度（role=scope）
建一组非视觉决策（`visual: false`，同时开放），让用户一次回答：

| 问题 | 选项 | 写入 scope.json |
|---|---|---|
| 项目类型 | 从零新建 / 已有产品改版 | `mode`: new / redesign |
| 产品形态 | 网站/落地页（内容为主，滚动阅读）/ 应用界面（工具、后台、仪表盘、客户端） | `product_type`: site / app |
| 改动范围 | 只做一个页面 / 先做样张页、定稿后全站铺开（推荐）/ 全站同时做 | `scope`: single / sample-then-rollout / all-pages |
| 布局自由度 | 保留现有布局只换视觉 / 页内可重排 / 可重构页面结构（业务逻辑不变） | `layout_freedom`: keep / rearrange / restructure |
| 流程轨道 | 完整轨道 / 快速轨道（简报与方向合并验收，playground 可跳过） | `track`: full / fast |
| 外观是否开放 | 外观参数在设计期定死 / 也让最终用户在产品里调整（主题、配色、密度、动效开关等） | `user_customizable`: false / true；为 true 时 `customization_page` 填设置页名称，并列入本期页面。只有选 true，后续决策才能「做成设置项」（见 0.12） |

再从用户已给的信息里整理以下清单（不确定就作为问题加进决策）：
- `pages`：**全部可导航的目的地**，不只是用户给的那一屏。从截图、现有代码、路由表里找出所有页面、分页（tab）、侧栏/顶栏入口、设置页及其分页、常用弹窗和抽屉，逐个让用户确认本期做不做。本期不做的也要列出：`{"name": "设置 → 账户", "in_scope": false, "reason": "下期"}`。
- `source_dirs`：生成页面所用的源码目录（生成脚本、组件、着色器、配置），每过一个闸门自动快照。
- `references`：用户提到的影视、游戏、品牌等**整体参考**（例如"像某部电影""像某款游戏"）。
- `asset_types`：改版会影响到的内容资产类型（头图、插画、图标、示意图、封面……）。主动列出，不要等用户提出。

```json
{"mode": "redesign", "product_type": "app", "scope": "sample-then-rollout",
 "layout_freedom": "rearrange", "track": "fast",
 "user_customizable": true, "customization_page": "设置 → 外观",
 "pages": ["总览", "详情", "设置 → 外观", {"name": "设置 → 账户", "in_scope": false, "reason": "下期"}],
 "references": ["某部复古科幻电影"], "asset_types": ["头图", "插画"], "source_dirs": ["src/ui", "tools/gen"]}
```

### S0.2 改版项目先截现状基线
`mode: redesign` 时，`media/baseline/` 里每个页面至少一张现状截图（`samples.py shot <页面地址> --out .taste-design/media/baseline/<页面>.png`，需要时加 `--width 375` 截手机）。这是**前置条件，不能跳过**：截图工具装不上或页面需要登录时，请用户提供截图或协助登录。

### S0.3 闸门 0
gate 决策的 media 放基线截图。通过后把 gate.py 打印的阶段序列告诉用户。
