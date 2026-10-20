# 阶段、轨道与变更管理

## 多期项目

需要 P1、P2、P3 的同一产品，必须把每一期建成独立流程实例：

```bash
python3 "$SKILL/scripts/gate.py" init --phase P1 --name "第一期" --channel web
python3 "$SKILL/scripts/gate.py" phase add P2 --name "第二期" \
  --parent P1 --inherit shared/brand.md --inherit shared/design-system
python3 "$SKILL/scripts/gate.py" phase list --json
python3 "$SKILL/scripts/gate.py" --phase P2 context --json --compact
```

- 每期都在 `.taste-design/phases/<ID>/` 下拥有自己的 `record/state.json`、`scope.json`、决策、答案、`progress.md`、产物与运行态；P1 的 `passed` 不能自动成为 P2 的 `passed`。
- 多期项目存在多个实例时，未写 `--phase` 必须报错，不能默认选最新一期。只有一个实例时才允许唯一解析。
- `phase.json` 只记录 `parent_phase` 与 `inherits`。继承路径先核对实际文件；本期的范围、起点阶段和复用旧成果的方式仍需用户决定。`gate.py` 不读取父期状态来放行本期闸门。
- 多期用 `gate.py --phase ID ...`；`decide_server.py`、`summary.py`、`variants_check.py`、`theme_matrix.py` 同样接受 `--phase`。Hook 用 `TASTE_DESIGN_PHASE` 指定期；未设置时在多期项目中不会猜期或自动续跑。
- `--root` 支持项目、容器和具体期；显式 `--phase` 优先，未指定时可沿用当前目录所属期。`init` 的 `--phase` 可写在子命令前或后；普通非设计目录中的 hook 不拦截结束。
- `shared/brand.md`、`shared/design-system/` 只放跨期稳定的已确认基线。旧阶段的验收、待复核项、本期专属样张和未完成工作不得移入共享层。
- 从单期升级为多期不自动搬运状态。需要迁移时先备份原 `.taste-design/`，由用户确认映射关系；没有迁移前，原单期项目继续按单期运行。
- 本期起点在阶段 0 的 `scope.json` 中写明 `start_stage`（0 / 2 / 3 / 4 / 5 / 6），并通过 `phase_relation` 与 `inherit_mode` 说明来源。通过闸门 0 后进入轨道中从起点开始的首个有效阶段；起点为 0 时走完整起始流程。起点只表示从哪里制作，不表示旧期验收自动沿用。`source_dirs` 仍相对项目根目录，快照分别保存在各期 cache 中。

### 0.3 阶段与闸门
| # | 阶段 | 必需产物（gate.py 检查） | 特别检查 |
|---|---|---|---|
| 0 | 启动与范围 | record/scope.json；改版项目还要 media/baseline/ 每页一张现状截图 | role=scope 已答；role=delivery-boundary 用户选择与 delivery_mode 一致；pages 列全；外观是否开放已定 |
| 1 | 创意简报 | record/brief/ 下的 brief.md、traits.md、content.yaml、constraints.yaml | scope.references 里每个参考都有一个 role=reference-breakdown 决策 |
| 2 | 信息架构（灰模） | work/wireframe/*.html | — |
| 3 | 视觉发散 | work/variants/variants.html（只能有这一个页面） | 至少一个"大胆"档方案；role=direction 决策已答 |
| 4 | 原型与资产规范 | work/proto/v*.html、work/assets/spec.md | spec 覆盖每类资产；基准已选；应用类有状态表且原型可切换状态；带质感/动效时 traits 有图层表 |
| 5 | 设计令牌定稿 | work/playgrounds/*.html、work/tokens.css；有设置项时 work/theme/axes.json、gallery.html | 设置项规格通过校验（0.12）、每套预设已验收、每个「做成设置项」的答案都已归类 |
| 6 | 区块打磨 | work/proto/v*.html | — |
| 7 | 全站铺开 | work/rollout/pages.json、work/rollout/overview.html | scope.pages 每页都在清单里且 status=done；仅设计时每页 prototype 指向实际工作原型 |
| 8 | 质量检查 | work/qa/report.md、work/qa/manual-checks.md；有资产类型时还要 work/qa/asset-compare.html；有设置项时 work/qa/theme-matrix.json | 所有衍生资产逐条达标；所有设置组合对比度达标且有截图 |
| 9 | 交付 | work/handoff/DESIGN.md、work/handoff/HANDOFF.md | HANDOFF 写明边界与验证；待复核事项已答；仅设计在交付最后建议是否同步项目文档，不以同步作为完成条件 |

每个闸门还都要求：本阶段决策全部作答、有一个被用户 approve 的 `type: gate` 验收决策、所有决策通过校验、brief.md 和 traits.md 已同步到本闸门（见 0.6）、本阶段智能体代定的事项已逐条写进验收决策（见 0.8.1）。

设计并实施时，闸门通过会把 scope.json 里 `source_dirs` 列出的源码目录快照到 `cache/snapshots/gate-N/`（本地备份，不提交）。仅设计不复制工程源码；初始化时记录的工程指纹用于检查实现未变，规则见 [阶段 0](stage-0.md)。两种模式均保存真实用户选择，`next/context` 输出当前边界及已确认的决策版本。

多期项目额外检查：闸门 0 会核对 `phase.json.inherits` 的路径实际存在；继承不改变本期 `scope.pages`、页面范围和验收条件。没有 `phase.json` 的单期项目不做这项检查。

### 0.4 轨道：闸门 0 通过时按 record/scope.json 确定
| 条件 | 效果 |
|---|---|
| `layout_freedom: keep`（保留现有布局） | 省略阶段 2 |
| `scope: single`（只做一个页面） | 省略阶段 7 |
| `track: fast`（快速轨道） | 阶段 3 并入闸门 1（简报冻结和方向选择一起验收）；阶段 5 可跳过（外观开放给最终用户时除外）：有人值守时先建一个 `role: "skip"`、`skip_stage: 5` 的 gate 决策让用户点头，再 `gate.py skip 5 --reason …`，跳过自动进入待复核清单 |
| `track: full`（完整轨道） | 不合并、不可跳过 |

闸门 0 通过后，gate.py 会打印本项目的阶段序列。**必须把这条序列原样告诉用户**：走哪条轨道、哪些闸门合并、哪些阶段省略。不允许静默跳过任何阶段；要改轨道只能 `gate.py rollback 0` 重新定范围。

### 0.6 活文档：每过一个闸门都要同步
- 阶段中途也要按 [上下文与恢复协议](continuity.md) 及时记录用户补充和当前工作位置；过闸门前的同步是最终核对，不能替代随事件落盘。
- `record/brief/brief.md` 和 `record/brief/traits.md` 是活文档，任何阶段都可以改。每次过闸门前，必须把它们更新到最新结论：**删掉已被推翻的内容**（不是加一行"已变更"），升版本号，并写一行 `同步至闸门：N`。gate.py 不放行未同步的闸门。
- `record/decisions.md` 里标为"待定"的行，在结论出来后与结论行合并成一行，不要留两行。
- 简报中的每条约束都要能追溯到用户的原话或某个决策 ID。智能体想加的约束（例如"不改信息层级""保留现有配色"）**不能直接写进简报**，必须作为决策让用户选。
- brief/traits 只保留当前有效结论、尚待处理项和来源链接。回退后重新核对“当前完成状态”，不能保留已作废阶段仍通过的说法。旧阶段实现细节、失败尝试和收束过程移入 `record/history/` 的相关记录并保留链接，不在活文档重复展开；归档不删除原题目、答案或样张，也不把历史全部标成有效约束。

## 10. 变更管理
用户提出与已通过阶段不一致的要求时：
1. 指出它与哪一条冲突、影响范围。
2. 建一个 `single` 决策让用户确认是否回退（附当前状态截图）。
3. 确认后 `gate.py rollback N --reason "…"`：

| 变更类型 | 回退到 |
|---|---|
| 改动范围、布局自由度、轨道、新增资产类型、外观是否开放 | 阶段 0 |
| 新增页面 | 不回退，用 `gate.py add-page`（见阶段 7 第 6 条） |
| 主题/参考/方向 | 阶段 1（快速轨道）或阶段 3（完整轨道） |
| 增删区块、调整优先级 | 阶段 2（被省略时回到阶段 0 改布局自由度） |
| 颜色/字体/质感 | 阶段 5（被跳过时用 assume 记录新值） |
| 新增或删除设置项、预设、维度取值 | 阶段 5；更新 axes.json、令牌和画廊，重跑主题矩阵 |
| 改变交付边界（仅设计 / 设计并实施） | 阶段 0；原交付边界答案归档，用户重新选择后再验收，不能只改 delivery_mode 或重置工程指纹 |
| 动效行为（哪层动、怎么动、周期） | 阶段 5；先按 0.10.2 更新动效规格并让用户确认 |
| 图层质感划分（如卡片改透明） | 阶段 5，并同步 traits 的图层表 |
| 单个区块细节 | 阶段 6 |

4. 回退后该阶段及之后的验收作废，需要用户重新验收；brief 和 traits 按 0.6 同步。

---

## 11. 无人值守模式
以 `gate.py init --mode unattended` 初始化时：
- 阶段 0 的范围问题和阶段 1 未达 L1 时，建立用户决策并按 runtime.md 等待，不编造范围或创意。
- 其余决策照常生成（含样例），智能体按特征覆盖度选择，用 `gate.py record <ID> --choice X --by agent --via native --note "理由"` 登记，自动进入待复核清单。
- 仍然逐阶段 check / pass，不得跳阶段；代答也要通过 next 读取、落实并 ack。有人值守的审美决定仍由用户作答。
- 完成时明确告知用户哪些决策由智能体代定，建议从最早的一项开始复核。
