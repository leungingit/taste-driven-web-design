## 5. 设计令牌定稿（阶段 5；快速轨道下可跳过，外观开放给最终用户时不可跳过）

开始前：`gate.py check 5`。
- 必做 `work/playgrounds/colors.html`（每个颜色变量取色器 + HSL 滑块，实时显示对比度）、`work/playgrounds/typography.html`；traits 中 high 权重的质感/空间/动效维度也要有 playground。
- 左侧控件、右侧实时预览原型中最相关的 2–3 个区块；每次数值变化执行 `parent.postMessage({type: "decide:value", value: "<CSS 变量文本>"}, "*")`。
- 每个 playground 一个 `tune` 决策。字体候选多时先用 `single` 粗选。
- **提交校验**：收到用户提交的数值后，**先对照 brief、traits 和 constraints 逐项检查，再写入**。发现冲突（例如字号低于"读数一眼可读"的下限、动画时长超过数据刷新间隔、对比度不达标）时，先建一个决策列出冲突和可选的修正，用户确认后再写，不要写完才提醒。
- 只提交了部分 playground 是允许的：没提交的参数明确记为"沿用当前值"，写进 record/decisions.md。
- 动效类参数定稿时，按 0.10.2 先复述规格、实现后交录屏与实测数据。
- **设置项定稿**（外观开放给最终用户，或已有 axes.json 时）：按 0.12 写 `work/theme/axes.json`，按三层令牌结构写 `work/tokens.css` 的覆盖；复制 `$SKILL/templates/theme-gallery.html` 为 `work/theme/gallery.html`；每套预设建一个验收决策（media 用 `@/work/proto/vNNN.html` 加 `attrs`）；阶段 5 的验收决策附上主题画廊（`{"type":"html","src":"@/work/theme/gallery.html","origin":"rendered","display":"wide","trusted":true}`），请用户确认所有组合仍是同一个产品。
- 快速轨道跳过（外观不开放时才允许）：先让用户在 `role: "skip"` 决策上点头，再 `gate.py skip 5 --reason "…"`。跳过时颜色和字体由智能体决定，自动进入待复核清单；把具体取值再用 `gate.py assume` 记一笔，并写进下一个闸门的验收决策。

**闸门 5**：tune 决策全部提交，写入 `work/tokens.css` 并生成新版原型；有设置项时 axes.json 通过校验、每套预设已验收；gate approve。
