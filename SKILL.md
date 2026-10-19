---
name: taste-driven-web-design
description: 为网站、落地页和应用界面做有个人风格的视觉设计，也用于已有产品的视觉改版与全站铺开：范围与轨道→简报→灰模→视觉发散→原型与资产规范→令牌→打磨→全站铺开→质检→交付。脚本强制逐阶段准入，所有审美决策在带真实图片/样张的网页上由用户作答。
---

# 有品味的网站设计流程（规范版 v14）

一次调用覆盖已确认范围内的完整设计流程。用户提供素材、选择方向并验收；智能体负责阶段推进、等待接续、落实答案、验证与交付。用户不需要逐阶段发送“继续”。

路径约定：`$SKILL` 是本技能目录。命令在项目根目录运行；设计过程文件均位于项目的 `.taste-design/`，下文 `record/`、`work/`、`media/`、`cache/` 均相对此目录。

## 全流程执行契约（每次启动或恢复先读）

1. **阶段完成就推进**：阶段性成果用进度消息汇报；执行 `gate.py pass N` 或获批的 `skip N` 后，在同一活跃回合执行实际后继阶段的 `check` 并开始工作，不把阶段总结当作最终交付。
2. **等待有接手方**：默认在活跃回合内运行分段 `wait`。工具返回进程/会话 ID 时持续接续该会话；只有进程结束才解析退出码。不能启动后台等待后结束回合，也不能只发网页地址。
3. **超时不是暂停**：单段超时、空闲、暂无可答问题都不表示任务完成。续接等待，或读取 `next` 继续制作。只有用户明确要求才能登记 pause。
4. **答案落实后确认**：读取完整答案、备注和数值，落实到产物或下一轮决策，再逐项 `ack ID --ts 原版本时间戳`。交付失败或未确认会重交；先核对已完成的修改，避免重复落实。
5. **统一下一步**：CLI、网页、hook 共用 `gate.py next --json` 的判定。不凭“这个阶段看起来结束了”自行收口。
6. **正常收口条件**：`completed`；用户明确暂停；或已登记具体原因、已尝试措施和所需用户操作的真实外部阻塞。inline/static 通道可为等待真实答复结束交互回合，收到答复后继续原任务。等待属于流程中间状态。
7. **能力边界**：配置了 hook 不代表它已生效，HTTP 服务存活也不代表智能体会被唤醒。只有真实宿主试验确认 hook 被调用且 `block` 被接受后，才能依赖 hook 接手。没有可靠接续机制时保持活跃回合等待；无法保持时如实说明限制并记录具体阻塞，不承诺自动恢复。
8. **进度随事件落盘**：用户补充或纠正要求时立即记入 `record/notes.md`，标明来源、有效状态及替代关系；可验证的小步骤完成、进入等待或切换阶段时更新 `record/progress.md`。不等过闸门或上下文将满才整理。压缩后按恢复协议核对文件，不凭聊天摘要直接 ack 或过闸。

## 启动、恢复与主循环

1. 新项目运行 `python3 $SKILL/scripts/gate.py init`；有旧版 `design/state.json` 时先 `gate.py migrate`。已有项目保留现状，不重新初始化。
2. 阅读 [上下文与恢复协议](references/continuity.md)，运行 `gate.py context --json`，按固定顺序读取当前记录与相关产物；再按 [阶段、轨道与变更管理](references/workflow.md) 和 `gate.py next --json` 接续。用户明确恢复已暂停任务时，先 `decide_server.py resume`；外部阻塞解决后 `gate.py unblock --reason …`。
3. 按 [决策通道与文件协议](references/decisions.md) 自检展示能力，并把结果写进 `record/decisions.md`。按 [运行协议](references/runtime.md) 检查等待接续方式；默认使用活跃回合内 CLI 等待。
4. 只读当前阶段说明；涉及样例、动效、主题或素材管理时按下表阅读对应规范。运行 `gate.py check N` 后执行当前阶段工作。
5. 根据 `next` 结果循环，直到符合收口条件：

| `status` | 必须采取的下一步 |
|---|---|
| `working` | 继续当前阶段产物、验证或修复依赖；缺决策就创建决策 |
| `processing` | 落实 `new` 中的完整答案，逐项 ack，再查 next |
| `waiting` | web 通道建立分段 wait；其他通道展示样张并等待真实用户答复 |
| `gate-ready` | 执行 `action` 指定的 pass 或获批 skip，直接进入轨道后继 |
| `paused` | 用户明确暂停；保留状态，等待其恢复意图 |
| `blocked` | 报告已登记的具体阻塞与所需操作；解决后 unblock 并接续 |
| `completed` | 输出最终成品、验证结果及确需人工完成的交付步骤 |

`check` 失败表示不能执行所请求阶段的工作，应读取 next 修复当前阶段；不表示整个任务结束。运行中回答用户的状态问题、收到补充条件时，保留原目标并接着执行，除非用户明确暂停或取消。

## 必须保留的设计约束

- 主要审美选择和每阶段验收由用户在带真实图片/样张的决策页完成；不代答、不编造用户约束。次要事项用 `assume` 记录并随阶段验收。
- 所有阶段按轨道执行，只能用 `gate.py pass/skip` 前进。阶段 0 后把脚本输出的轨道、合并与省略原样告知用户。
- 不手改 `record/state.json`、`answer.json`、`record/summary/`、`.gitignore` / `.gitattributes`；答案交付和确认记录由脚本维护。
- 每过闸门前更新 brief.md、traits.md，删除被推翻内容、升版本并写“同步至闸门：N”；用户备注逐条落实。未 ack 的答案不能过闸。
- 变更已通过阶段先按 workflow.md 回退。当前阶段验收为 revise 时，按备注修改、确认该答案，再创建新 ID 的 gate 决策重新验收，保留旧答案。
- 画面类样例使用真实素材、检索图或生图；代码渲染只用于 code-native。按问题匹配样例保真度；粗稿不能用于评判成品观感。
- 成品写到项目实际源码位置；保留设计历史。只在用户要求时提交版本控制。

## 按当前工作读取

| 当前工作 | 阅读文件 |
|---|---|
| 全程：轨道、闸门、活文档、回退、无人值守 | [workflow.md](references/workflow.md) |
| 启动、压缩后恢复、会话交接、用户补充要求 | [continuity.md](references/continuity.md) |
| 开始等待、接续工具会话、宿主 hook、答案确认、故障 | [runtime.md](references/runtime.md) |
| 创建或展示决策、选择通道、JSON 与样例字段 | [decisions.md](references/decisions.md) |
| 生成样例、动效、管理素材与目录、主题设置、保真度 | [design-rules.md](references/design-rules.md)（按 0.10–0.13 相关小节读取） |
| 阶段 0：启动与范围 | [stage-0.md](references/stage-0.md) |
| 阶段 1：创意简报 | [stage-1.md](references/stage-1.md)；快速轨道同时读 stage-3 |
| 阶段 2：信息架构（灰模） | [stage-2.md](references/stage-2.md) |
| 阶段 3：视觉发散 | [stage-3.md](references/stage-3.md) |
| 阶段 4：原型与资产规范 | [stage-4.md](references/stage-4.md) |
| 阶段 5：设计令牌定稿 | [stage-5.md](references/stage-5.md) |
| 阶段 6：区块打磨 | [stage-6.md](references/stage-6.md) |
| 阶段 7：全站铺开 | [stage-7.md](references/stage-7.md) |
| 阶段 8：质量检查 | [stage-8.md](references/stage-8.md) |
| 阶段 9：交付 | [stage-9.md](references/stage-9.md) |

脚本只依赖 Python 3 标准库；截图、样张检查和主题矩阵按对应脚本需要使用 Playwright / Pillow / ffmpeg。附带的脚本职责与模板清单见 [运行协议](references/runtime.md)。
