## 9. 交付（阶段 9）

开始前：`gate.py check 9`。
- **成品写到项目里它真正的位置**：改版项目直接改现有源码；新建项目写到 constraints.yaml 的 `deliver_to`（如 `site/`、`public/`、`src/pages/`）。不要默认写项目根的 `dist/`，那通常是构建输出目录。
- `work/handoff/DESIGN.md`：主题、令牌表（三层）、字体、组件清单、图层表与动效规格、资产规范摘要；有设置项时附维度、预设、默认值、不变项和每个维度的 `who`。`target` 不是 web 时附**移植说明**：令牌与配置 JSON 的含义、哪些效果依赖浏览器能力、目标平台上的对应实现建议。
- `work/handoff/HANDOFF.md`：**需要人工完成的步骤**，固定格式，每一步都写明验证方法：
  ```markdown
  ## 1. 替换线上的预置封面图
  - 目标位置：对象存储的封面目录（写明实际路径）
  - 文件：public/covers/*.png（写明数量）
  - 操作人：负责部署的同事
  - 验证：打开 /courses，14 张封面均为新版；抽查 3 张的 URL 返回 200
  ```
  涉及的外部系统（对象存储、CDN 缓存、后台配置、数据迁移、第三方账号）都要列出；没有则写"无"。
- **集中复核代定事项**：record/pending-review.md 非空时，建一个 `role: "pending-review"` 的 `multi` 决策，每条代定事项一个选项（能配图的配图），用户勾选"要推翻的"并在备注写新的决定。按结果修改后再验收。
- 保留 `.taste-design/` 全部历史；提交前确认 `git status` 里只有 record/、work/（和按策略的 media/）。

**闸门 9**：gate approve。
