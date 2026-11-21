---
name: copisteria-to-mscz
description: >
  将印刷乐谱 PDF 转为经过核查的 MusicXML/MuseScore（.mscz）交付物。当用户要求
  “PDF 转 MusicXML”“PDF 转 MIDI”“OMR”“识谱”，或要求用 copisteria/copista
  校对 OMR 输出时使用。覆盖环境配置、逐页 OMR、scorepipe 修复、facts 注入、
  视觉复核和交付。
metadata:
  version: "0.2.1"
---

# Copisteria to MSCZ

本 skill 是 **操作层**，真正的机械修复由 `scorepipe` 子模块完成。skill 负责环境配置、OMR
调用、证据收集、视觉复核和交付。

## 硬性规则

- 不要因为命令退出码为 0 就宣布交付。必须有干净的 verifier；有视觉交付时还必须重新渲染检查。
- OMR 只是草稿。保留源 PDF 和逐页输出，永不覆盖。
- OMR 的音高/节奏错误不能由 pipeline 静默“修正”。facts 和人工修正必须可追溯。
- PDF 文字层不是 ground truth。没有文字层或文字层乱码时，走 agent/视觉 facts 路径
  （见 `references/facts.md`）。
- 不要在用户未决定时下载模型权重、安装系统包或申请管理员权限。`scripts/preflight.py`
  只报告缺项和选项。

## 快速路径

```bash
# 1. 每台机器做一次环境检查；只报告缺项，不安装。
python scripts/preflight.py --save env.local.json

# 2. OMR + 修复 + MuseScore + PDF 一次完成。
python scripts/convert.py "score.pdf" --env env.local.json --outdir "out/score" \
  --title "标题" --composer "作曲"

# 3. 检查 report 和渲染页，再交付。
```

如果用户已有别的 OMR 前端，不用 `scripts/convert.py`，直接把逐页目录交给 pipeline：

```bash
python -m scorepipe.cli path/to/pages -o out/score.musicxml --mscz-out out/score.mscz \
  --report out/report.json
```

## 产物

| 产物 | 含义 |
|---|---|
| `score.musicxml` | 修复、合并后的 MusicXML，语义主文件 |
| `score.mscz` | display fixpoint 之后的 MuseScore 容器 |
| `score.pdf` | 用于复核的渲染版 |
| `report.json` | 阶段轮数、pass trace、analysis、verifier |
| `delivery.json` | `scripts/convert.py` 记录的命令、路径和产物清单 |
| `work/copisteria/` | 逐页 OMR MusicXML、reading JSON、HTML；保留用于审计 |
| `facts.json` | 显式文字/视觉事实（使用 facts producer 时） |

不要只交付 `.mscz`。MusicXML 才是修复 pipeline 拥有的主文件。

## 工作流

### 0. 配置环境

先读 `references/environment.md`，再运行 `preflight.py`。必需项：

- Python 3.10+，能 import 本仓库的 `scorepipe`；
- 单独的 OMR Python 环境，含 copisteria 和 music21；
- copisteria 源码和模型权重；
- MuseScore 4，用于 `.mscz`/PDF（只做 MusicXML 时可无）；
- poppler（`pdfinfo`、`pdftoppm`），用于页数和视觉复核。

`preflight.py --save env.local.json` 会记录路径；不要提交这个文件。

### 1. 确认输入

- 确认 PDF 是目标版本，记录页数。
- 记录标题、作曲、编曲，以及已知弱起、反复、移调乐器。
- 先复制到交付工作目录，再运行 OMR。

### 2. 运行 OMR

`scripts/convert.py` 调用外部 copisteria，然后把 **逐页目录** 交给 scorepipe。不要用旧
converter 最终合并的 MusicXML 作为 pipeline 输入：逐页上下文是页级 tie/slur/pedal 恢复
所必需的。

页契约和排查见 `references/omr.md`。

### 3. 修复与验证

pipeline 按 structural → inject → display 跑到不动点，再跑只读 verifier。检查
`report.json`：

- 每个阶段 `stable=true`；
- `verifier` 为空；
- 没有无法解释的 `measure-length` 或 hidden-rest；
- 有 ground truth 时做对比（`--compare-golden` 或 Lieder comparator）。

### 4. Facts 与视觉复核

文字层可以提供标题、作曲、速度文字、排练号和说明文字。添加 facts 前先读
`references/facts.md`。facts 是数据：在注入 pass 应用前不会改谱，每个已应用 fact 必须可追溯。

Agent/视觉 facts 的流程：

```bash
# 渲染源 PDF，生成逐页图片和 agent 指令
python scripts/agent_facts.py prepare --pdf "score.pdf" --outdir review/facts

# agent 逐页看图，写出带 page/evidence/bbox 的 JSON
python scripts/agent_facts.py validate --facts review/facts/agent-page1.json --pages 2
python scripts/agent_facts.py merge --parts review/facts/agent-page*.json -o review/facts/facts.json

# 注入并重新渲染
python scripts/convert.py "score.pdf" --pages path/to/omr-pages \
  --facts review/facts/facts.json --outdir "out/score"
```

看不清的内容放进 `unresolved`，不要猜。视觉复核至少渲染 `.mscz` 为 PDF 并栅格化，检查：

- 首尾系统、页缝；
- 弱起和小节编号；
- 密集钢琴系统和加线八度；
- 跨页 slur/tie；
- 文字/credit 位置。

没有新渲染，不要说视觉问题已修复。

### 5. 交付

按 `references/delivery.md` 执行。交付 MusicXML + `.mscz` + PDF + report，说明 verifier
结果和已知 OMR 缺陷，并保留 work 目录。

## 仓库结构

```text
SKILL.md                 本操作契约
scripts/preflight.py     只读环境探测，不安装
scripts/convert.py       PDF -> OMR pages -> scorepipe -> mscz/pdf
scripts/agent_facts.py   prepare/validate/merge agent 视觉 facts
schemas/                 facts JSON schema
scorepipe/               Python pipeline（子模块，含 agent_facts 校验）
tests/                   回归测试和 Lieder corpus
docs/                    架构、验收证据、归档计划
references/              skill 操作参考
SANITY.md                pass 契约审计
```

## 当前状态（2026-11）

- `unittest`：185 个测试；`pytest`：265 个测试。
- Gute Nacht：sounding notes 98.94% / 99.0%（vocal/piano），verifier clean。
- `aus_meinen_traenen`：91.38% / 90.10%；`die_wetterfahne`：98.97% / 97.75%。
- `der_lindenbaum` P2 仍是 OMR 质量异常项（约 51%）。
- 已知交付阶段缺口：agent/视觉 facts 已有 prepare/validate/merge 和证据校验；真实交付还需要
  逐页视觉复核和人工确认 unresolved 项。
