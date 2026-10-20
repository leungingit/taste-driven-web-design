## 7. 全站铺开（阶段 7；scope 为 single 时省略）

开始前：`gate.py check 7`。

先读取 `scope.json.delivery_mode`。`design-and-implement` 执行下面的逐页改造；`design-only` 在 `work/` 内抽取原型共享组件、覆盖本期全部页面并截图，不修改工程组件和路由。仅设计时 `pages.json` 的每一页增加 `prototype`，指向实际存在的 `work/` 内原型（相对本期设计目录）；`status=done` 只代表该页设计完成。总览展示原型的桌面/手机效果，并注明尚未实施。门禁会核对原型文件与工程指纹，不能用源码截图代替工作原型。

仅设计的页面记录示例：`{"name":"工作台","route":"/dashboard","components":["页头","空状态"],"order":1,"status":"done","prototype":"work/proto/v003.html"}`。

1. **盘点**：列出全部页面和共享组件，写 `work/rollout/pages.json`：
   ```json
   [{"name": "工作台", "route": "/dashboard", "components": ["页头", "统计卡", "空状态"], "order": 1, "status": "todo"}]
   ```
   页面名必须与 scope.pages 一致；status 为 todo / doing / done。
2. **先抽共享组件**（页头、导航、表格、弹窗、空状态、线框小图等），在组件层改好，再逐页套用。
3. **逐页改造**：每页完成后截桌面 1440 和手机 375，放 `media/shots/rollout/`，status 改为 done。
4. **对照表**：复制 `$SKILL/templates/rollout-overview.html` 为 `work/rollout/overview.html`，按页填入改造前（baseline）、桌面、手机三张图。gate 决策的 media 放这个页面（`display: "wide"`）。
5. 铺开过程中出现的次要取舍用 `gate.py assume` 记录。
6. **中途新增页面**：用 `gate.py add-page "页面名" --reason "…"`。它把页面加进 scope 和 pages.json，并标出该页需要补做的步骤（改版项目补基线截图、可重排时补灰模、应用类补状态）；只有这个页面补走流程，其他页面不回退。若已经过了阶段 7，会自动回到阶段 7。

**闸门 7**：所有页面 done，gate approve。
