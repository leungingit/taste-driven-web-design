# 运行、等待与答案确认协议

## 0.8.5 全流程循环

每次启动、上下文压缩后或会话交接，先按 [上下文与恢复协议](continuity.md) 运行 `gate.py context --json` 并核对当前记录与产物，再进入下述循环。工作记录不替代答案原文、精确版本确认或真实阶段判定。

默认在活跃智能体回合内接续，不依赖网页后台唤醒。每次启动、恢复、收到答案、通过闸门或工具出错后，运行：

```bash
python3 $SKILL/scripts/gate.py next --json
```

此命令交付当前阶段及并入阶段未确认的完整答案，包括 `id`、`ts`、`choice`、`note`、`other`、`value`、`setting`。它不会代替用户作答，不自动通过闸门。

```text
next → 当前阶段工作 → 建决策 → 对话通知地址与待决定项 → 分段等待
                  ↑                                  ↓
实际后继阶段 ← pass/skip ← 落实答案并 ack
```

**落实答案**：逐条处理备注、其他选项、数值和设置要求，更新 brief/traits、原型或下一轮样张。每项完成后确认原版本：

```bash
python3 $SKILL/scripts/decide_server.py ack D03-brush --ts '从答案原样取得的时间戳'
```

不能只为过闸而 ack。`ack` 拒绝未交付和版本已变化的答案。中断后再次收到相同答案时，先核对产物中已完成的变更，再补齐剩余工作并确认。旧版 `.agent-seen.json` 只表示尝试读取，不迁移为已落实，升级后会要求核对并重新确认当前阶段的答案。

当前阶段验收为 revise 时：落实备注、确认该答案，再建新 ID 的 gate 决策；保留原答案作为历史。通过验收后先确认答案，再按 next 指示 pass/skip，并在同一活跃回合 check 实际下一阶段、开始工作。

## web 通道：服务与分段等待

先后台启动决策服务（每项目一份），把实际地址告知用户；SSH 远程按 decisions.md 说明端口转发：

```bash
python3 $SKILL/scripts/decide_server.py serve
```

创建决策后，必须先完成以下步骤，再进入等待：

1. 运行 `gate.py next --json`，确认状态为 `waiting`，读取 `decision_notice`。使用实际服务地址，不猜测默认端口；检查服务可访问，核对页面实际开放的决策。只有排队或无效决策时先修复，不让用户去找尚未开放的题目。
2. **在用户可见的对话消息中**发送 `decision_notice.text`，至少包括当前阶段、可点击的决策页地址、当前可作答项的 ID 与标题、在哪里选择和提交、提交后如何继续。工具日志不算通知；不能只发送“等待你的决定”。SSH 远程场景还要说明端口转发，使用实际本地转发端口生成用户可打开的链接。
3. 更新 `record/progress.md` 的待答决策和当前入口，再在活跃回合运行下述 wait。这条通知是过程消息，不是最终交付，不要求用户再说“继续”。

通知示例（地址、阶段、题目必须换成实际值）：

```text
阶段 1 · 创意简报：本轮需要你确认以下内容。
决策页：[打开决策页](http://localhost:实际端口/)
- D01-reference：你更接近哪一种参考氛围？
- D02-direction：请选择本轮视觉方向。
请打开页面查看样张，逐项选择并点击提交；有修改意见可填写备注。
提交后我会读取答案并继续制作。
```

每批新题开放、同一 ID 的题目或选项发生变化、服务地址变化、恢复后尚未在当前对话交代入口时，都先发送更新通知。同一批题目与地址没有变化时，分段超时续等不重复刷屏。用户已经在通知后作答时直接读取答案，不为补通知而重新要求作答。

进入等待的命令：

```bash
python3 $SKILL/scripts/decide_server.py wait --chunk 45 --idle 0
```

- 每段不超过 45 秒，选择小于宿主工具时限的长度。工具提前返回进程/会话 ID 时，用工具提供的续接接口读取同一会话，不把“仍在运行”当作命令完成，不重复启动并行 waiter。
- 已有明确进程退出码后，再按下表处理。退出码非零不一概视为失败。最后一行 `RESULT` 是 JSON，`status` 是等待结果，`flow_status` 是统一流程状态。
- 命令在阻塞前刷新输出 `NOTICE` JSON，其中包含地址、题目和可转达文本，作为漏通知时的提示；它仍是工具输出，不能证明用户已收到对话通知。发现漏发时先补发消息，再续接同一等待会话，不重复启动 waiter。
- 超时后立即接续下一段；等待期间不做依赖用户答案的工作，不代答。不要用结束回合、固定 sleep 后读文件或让用户答完通知来替代等待。
- `--idle` 保留兼容，非零仅产生一次分段空闲提示，仍须续接。默认 0，不因空闲结束。

| 退出码 / `status` | 处理                                                         |
| ----------------- | ------------------------------------------------------------ |
| 0 / answered      | 落实完整答案并逐项 ack，再查询 next                          |
| 10 / timeout      | 立即再次 wait；单段到时不是暂停                              |
| 11 / paused       | 用户明确暂停，保留进度并结束本次执行                         |
| 12 / nothing      | 当前无可作答决策；按 next 继续工作、修复决策或过闸，不能收口 |
| 13 / idle         | 空闲提示；立即再次 wait                                      |
| 14 / no-server    | 检查服务错误、端口与根目录，恢复 serve 后再次 wait           |
| 15 / completed    | 整个流程完成，输出最终交付                                   |
| 16 / blocked      | 报告已经登记的具体阻塞与所需用户操作                         |

只有服务监听和后台 waiter 都不足以让已结束的智能体回合恢复。不能承诺网页提交自动唤醒，除非实际宿主已经完成下述接续验证。

## 宿主接续能力检查

1. 默认选择活跃回合内分段等待：确认命令执行工具能返回输出或运行会话，并能用其续接接口读取结果。
2. 只有需要让 hook 接手等待时才配置它。在临时项目做一次真实宿主试验：建立非视觉测试决策，触发实际 Stop，确认 hook 被调用、`block` 被接受、用户提交后智能体拿到答案并落实确认。手动执行脚本只验证脚本，不能证明宿主安装成功。
3. 未通过真实试验仍用活跃回合等待。不读取凭证或无关宿主配置来“自检”。宿主没有任何可靠等待/恢复能力时，登记具体能力阻塞并说明限制；不假装已经接通。
4. 每次等待都有明确接手方。若工具返回后台会话 ID，接手方仍是当前活跃智能体；若 hook 经验证有效，则可由 hook 接手。不凭“命令已经启动”结束回合。

## 0.9 Claude Code 的 hook（可选护栏）

项目确实选择此方式时，在项目 `.claude/settings.json` 合并以下配置（保留既有配置，把 `$SKILL` 替换为绝对路径）：

```json
{
  "hooks": {
    "PreToolUse": [
      {
        "matcher": "Write|Edit|MultiEdit|NotebookEdit",
        "hooks": [
          {
            "type": "command",
            "command": "python3 $SKILL/scripts/stage_guard.py"
          }
        ]
      }
    ],
    "Stop": [
      {
        "hooks": [
          {
            "type": "command",
            "command": "python3 $SKILL/scripts/wait_hook.py --max 45 --idle 0",
            "timeout": 60
          }
        ]
      }
    ]
  }
}
```

`timeout` 必须大于 `--max`。现有配置也应改为短段等待；增加无限等待时间不能解决接续问题。

Stop hook 读取同一 next：有未确认答案就重交；有待答决策就短段等待；超时交还智能体续接；无待答决策但仍有工作就阻止提前结束。服务失联不放行，而是要求检查恢复。多次无文件进展只触发诊断，不自动当作完成或用户暂停。无人值守仍遵循其可代答范围；inline/static 的必要用户交互允许结束当前交互回合。

PreToolUse 的 `stage_guard.py` 仍负责拦截越级写入、修改已通过阶段、手写答案/状态、方案拆成多个 HTML 等。它们是流程护栏，不是任意命令执行的安全边界。

## 故障、阻塞与恢复

相同服务故障先检查端口、错误输出、根目录并作有限恢复，不无限重复同一失败动作。状态查询或产物验证失败时先修复实际错误，不把“命令失败”直接当作整个流程结束。

确有当前环境无法自行解决、必须由用户处理的阻塞时登记：

```bash
python3 $SKILL/scripts/gate.py block --reason '具体原因' --tried '已经尝试的措施和结果' --needs '用户需要完成的具体操作'
```

随后报告这些信息。不得把“需要用户说继续”“到下个阶段了”“等待太久”登记为真实外部阻塞。普通审美决策走决策页和 wait，不走 block。

解决后：

```bash
python3 $SKILL/scripts/gate.py unblock --reason '解除依据'
python3 $SKILL/scripts/gate.py next --json
```

只有用户明确暂停时运行 `decide_server.py pause`，或由用户在网页点“我先离开”。恢复意图到达后运行 `decide_server.py resume`，随后 next。网页解除暂停只改变标记，不承诺恢复已结束的智能体回合；主动暂停后的恢复与正常阶段推进不同。

## 验证本技能

```bash
python3 -B -m unittest discover -s $SKILL/tests -p 'test_*.py' -v
```

标准库测试使用临时项目和本机回环 HTTP，覆盖阶段连续推进、答案确认与重交、等待时限、暂停/阻塞及最终交付。测试宿主是否实际调用 hook，仍需执行上面的真实宿主试验。

上下文恢复测试另覆盖只读索引、过时或缺失工作记录、部分落实后的答案重交、合并阶段定位；独立会话的语义恢复按 continuity.md 人工验证，不能用脚本通过代替。

## 脚本与模板

路径相对技能根目录（SKILL.md 所在目录，下文写作 `$SKILL`）。脚本只依赖 Python 3 标准库；samples.py 的部分功能需要 playwright / Pillow / ffmpeg。

| 文件                                                        | 用途                                                                                                |
| ----------------------------------------------------------- | --------------------------------------------------------------------------------------------------- |
| `scripts/gate.py`                                           | 阶段状态机与统一 next 判定；**唯一**可以推进阶段的途径                                              |
| `scripts/decide_server.py`                                  | 本地网页决策服务，**默认**的决策交互方式                                                            |
| `scripts/paths.py`、`scripts/stages.py`、`scripts/rules.py` | 目录布局、阶段定义与轨道计算、决策校验规则（被其他脚本调用）                                        |
| `scripts/theme.py`、`scripts/theme_matrix.py`               | 设置项（主题/外观维度）的规格校验；按每个组合截图并检查对比度，生成 `work/qa/theme-matrix.json`     |
| `scripts/variants_check.py`                                 | 视觉发散的力度检查：渲染每个方案、量化布局相似度，确保克制 / 中等 / 大胆真正拉开（闸门 3 读取结果） |
| `scripts/summary.py`                                        | 作答后自动生成决策摘要卡（`record/summary/`），也可 `summary.py rebuild` 全部重建                   |
| `scripts/migrate.py`                                        | 由 `gate.py migrate` 调用：把旧版 `design/` 目录迁移到 `.taste-design/`                             |
| `scripts/samples.py`                                        | 从创意素材制作样例：网页截图、图片裁切、视频抽帧                                                    |
| `scripts/waitlib.py`                                        | 答案交付、落实确认与分段等待的公共逻辑（被 decide_server.py 和 wait_hook.py 调用）                  |
| `scripts/wait_hook.py`                                      | Claude Code 的停止护栏；实际验证生效后才可作为接续方式                                              |
| `scripts/stage_guard.py`                                    | Claude Code 的 PreToolUse hook，物理拦截越级写入                                                    |
| `templates/variants.html`                                   | 视觉发散：所有方案集中在一个页面                                                                    |
| `templates/progress.md`                                     | 当前工作记录模板；init 生成，旧项目缺失时按事实补建                                                 |
| `templates/rollout-overview.html`                           | 全站铺开：改造前 / 桌面 / 手机三栏对照表                                                            |
| `templates/asset-compare.html`                              | 质检：衍生资产与基准资产并排对照                                                                    |
| `templates/theme-gallery.html`                              | 主题画廊：把原型按所有设置组合并排渲染，实时显示对比度                                              |
