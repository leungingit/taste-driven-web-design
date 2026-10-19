# Taste-Driven Web Design

**Guide AI website design with your taste, and turn each choice into a result you can review.**

[中文](README.md) · English

`taste-driven-web-design` is a design skill for coding agents. It supports new websites, landing pages, application interfaces, visual redesigns, and rollouts across an existing product. Scope, creative briefs, visual exploration, prototypes, design tokens, implementation, and quality checks form a recorded workflow with stage approvals and recovery procedures.

You provide goals and references, review actual samples, choose a direction, and approve results. The agent produces the work, applies feedback, verifies outcomes, and advances through the agreed scope.

## Highlights

- **Make visual choices with visual evidence.** Major aesthetic decisions use a page with image, HTML, or video samples, including zoom, side-by-side comparison, responsive previews, and decision history.
- **Agree on scope before exploring.** Establish whether the work is a new build or redesign, one page or a full site, and whether the layout should stay or change.
- **Approve work stage by stage.** Scripts check artifacts, decisions, and answer acknowledgements before advancing to the next stage in the selected track.
- **Turn references into concrete specifications.** Break film, game, or brand references into discussable traits, then translate them into typography, color, layers, assets, and motion requirements.
- **Keep decisions with the project.** Preserve original answers, notes, summary cards, briefs, and verification results. Record the source of new requirements and which earlier requirements they replace.
- **Recover long workflows.** A current-work record and a read-only recovery index locate the stage, outstanding answers, relevant files, and next action, reducing dependence on the full chat history.
- **Carry the direction through to delivery.** Cover representative-page refinement, site-wide rollout, asset consistency, optional appearance settings, and handoff instructions.

## The workflow

| Stage | Work |
|---|---|
| 0 · Scope | Agree on pages, layout freedom, track, and appearance settings; capture the baseline for redesigns |
| 1 · Creative brief | Define goals, content, constraints, and reference traits |
| 2 · Information architecture | Use wireframes to review layout and information priorities |
| 3 · Visual exploration | Compare directions at different intensities, including at least one bold option |
| 4 · Prototype and asset specification | Build prototypes and establish asset benchmarks, layers, and interface states |
| 5 · Design tokens | Finalize typography, color, and other tokens; approve appearance presets and axes when applicable |
| 6 · Section refinement | Bring representative sections to finished quality |
| 7 · Site-wide rollout | Apply the approved design to all pages in scope |
| 8 · Quality checks | Review responsiveness, accessibility, assets, motion, project builds, and other agreed checks |
| 9 · Delivery | Deliver source changes, design documentation, and manual handoff steps with verification methods |

The track adapts to the approved scope. Keeping the existing layout omits wireframes; a single-page project omits site-wide rollout. The fast track merges visual exploration into the brief approval, and the token stage can be skipped when eligible and approved. See [stages and change management](references/workflow.md) for the exact rules.

## Get started

You need an agent that can read skill files, edit a project, and execute commands, plus Python 3. The stage controller and decision server use only the Python standard library. Screenshots, sample checks, and theme matrices use Playwright, Pillow, or ffmpeg as needed. Image search or generation requires corresponding capabilities from the host.

Place this repository in a skill directory supported by your host. For example, environments using `~/.agents/skills/` can run:

```bash
git clone https://github.com/leungingit/taste-driven-web-design.git \
  ~/.agents/skills/taste-driven-web-design
```

Skill discovery and activation depend on the host. Once it can read [SKILL.md](SKILL.md), explicitly invoke the skill in your target project and describe your goals, scope, and references. For example:

```text
Use taste-driven-web-design to redesign this project.
Start with a homepage sample, then roll out the approved direction to other pages.
Preserve the existing business logic. Aim for a warm editorial feel.
Confirm scope and references with me first, and show samples for major aesthetic choices.
```

The agent initializes the project records, creates decisions, and follows the workflow. The default channel is a local decision webpage. Before waiting on each new batch, the agent must send a chat message with the actual page address, the decisions awaiting your input, and submission instructions. When a local server is unavailable, the protocol selects an inline or static channel according to the host's capabilities. You answer decisions and approve results; you do not need to send a separate “continue” message after each stage.

## Project records and recovery

Design process files live in `.taste-design/` inside the target project. Finished code goes into the project's actual source locations.

```text
.taste-design/
├── record/   # State, scope, briefs, decisions, new requirements, and current work
├── work/     # Wireframes, directions, prototypes, tokens, QA, and handoff documents
├── media/    # Images, videos, samples, and screenshots
└── cache/    # Runtime files, source snapshots, and temporary output
```

`record/` and `work/` are intended to stay with the project. `media/` is ignored by default and can instead use Git LFS or ordinary commits. `cache/` is not committed. Committing requires the user's authorization.

To recover, run the following from the target project's root, replacing the example path with the actual skill location:

```bash
skill_dir="/path/to/taste-driven-web-design"
python3 "$skill_dir/scripts/gate.py" context --json
```

This command only returns a recovery index. It does not acknowledge answers or advance stages. The agent must read the relevant records, inspect actual artifacts, and then obtain complete answers through `next --json` before continuing. See the [context and recovery protocol](references/continuity.md).

## Repository guide

| Entry | Contents |
|---|---|
| [SKILL.md](SKILL.md) | Agent entry point and execution contract |
| [references/](references/) | Stage instructions, decision protocol, runtime rules, and recovery procedures |
| [scripts/](scripts/) | Stage gates, decision server, validation, and media tools |
| [templates/](templates/) | Direction page, theme gallery, asset comparison, and current-work templates |
| [tests/](tests/) | Regression tests for progression, answer replay, waiting, and recovery |

Run tests from this repository's root:

```bash
python3 -B -m unittest discover -s tests -p 'test_*.py' -v
```

## Operating boundaries

This skill supplies a workflow, tools, and recording protocols. Results depend on the agent, available assets, and verification environment. Stage checks do not replace reviewing the design itself. Whether a fresh session correctly recovers design trade-offs must be verified on a real project using the recovery protocol.

By default, the agent waits for answers in bounded segments within an active turn. A running local server does not automatically wake an agent whose turn has ended. Optional Claude Code hooks must be validated in the actual host before relying on them. Checks that require a physical device must be explicitly listed at handoff. See the [runtime protocol](references/runtime.md).

The skill specification, built-in decision interface, and detailed reference documents are currently primarily in Chinese. This page is an English introduction to the project.
