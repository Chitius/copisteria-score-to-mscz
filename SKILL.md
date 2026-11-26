---
name: copisteria-score-to-mscz
description: >
  将印刷乐谱 PDF 转为经过核查的 MusicXML/MuseScore（.mscz）交付物。当用户要求
  “PDF 转 MusicXML”“PDF 转 MIDI”“OMR”“识谱”，或要求用 copisteria/copista
  校对 OMR 输出时使用。覆盖环境配置、逐页 OMR、scorepipe 修复、facts 注入、
  视觉复核和交付。
metadata:
  version: "0.2.1"
---

# Copisteria to MSCZ

本文是执行任务的 agent/运维操作契约；机械修复由 `scorepipe` 完成。用户指南见
[`README.md`](README.md)，架构说明见 [`docs/DEVELOPMENT.md`](docs/DEVELOPMENT.md)。

## 硬性规则

- **没有干净 verifier，不宣布交付**；有视觉交付时还必须重新渲染并打开检查。退出码为 0 不够。
- OMR 只是草稿。保留源 PDF 和 `work/copisteria/` 逐页输出，永不覆盖；始终以逐页目录作为流水线输入，不要把已合并的 `score.musicxml` 反向喂回 `review.py`。
- 不猜测音高、节奏或记号。结构修复必须可追溯；内容修正必须经过明确 reviewer 接受。
- facts、correction、patch 是证据驱动的数据，不是让 agent 直接改 MusicXML/mscz/mscx 的许可。
- 看不清的内容放入 `unresolved`。缺页、未决项或 proposed correction 不得被描述为完整复核。
- 未经用户同意，不下载模型、安装系统包或申请管理员权限。`preflight.py` 只探测环境。
- `env.local.json` 等本机路径配置不得提交或放入交付包。

## 快速路径

```bash
# 1. 环境检查：只报告和记录路径，不安装依赖。
python scripts/preflight.py --save env.local.json

# 2. PDF -> 逐页 OMR -> 修复 -> mscz/PDF；此时仍是初稿（可选 --device cuda / --detector 2m / --range）。
python scripts/convert.py "score.pdf" --env env.local.json --outdir "out/score" \
  --title "标题" --composer "作曲"

# 3. 有逐页 facts 时：复核、三棵交付树、交付版对照图和验收报告（同样自动读取 env.local.json，也支持 --env）。
python scripts/review.py "score.pdf" --pages out/score/work/copisteria \
  --facts-dir review/facts --outdir "review/score"
```

首次跑通、尚无 facts 时，第 3 步改用 `--skip-facts`，并按需重传 `--title` / `--composer`：

```bash
python scripts/review.py "score.pdf" --pages out/score/work/copisteria \
  --skip-facts --title "标题" --composer "作曲" --outdir "review/score"
```

这只是机械基线：报告会记录 `facts_skipped`，不能称为完整 reviewed edition。

已有符合页契约的其他 OMR 输出时，可直接进入流水线：

```bash
python -m scorepipe.cli path/to/pages -o out/score/score.musicxml \
  --mscz-out out/score/score.mscz --report out/report.json
```

## 交付物

| 产物 | 含义 |
|---|---|
| `score.musicxml` | 未截断的语义主文件 |
| `score.mscz` | 可编辑交付件；发生 forced 截断时是截断副本 |
| `score.pdf` | 与实际交付 `.mscz` 对应的渲染 |
| `review-sheets.pdf` | 全部逐页小节对照图，人工核对入口 |
| `report.json` / `review-report.json` | 修复轨迹、verifier、页覆盖、findings 和阻断项 |
| `review/confidence/` | 符号级 OMR 可疑度热图 |
| `mechanical/` | 不含 agent facts/patches 的机械基线，必须保留 |
| `forced-truncation/` | overfull voice 的可编辑收尾副本，不是语义权威 |
| `semantic/` | 实际截断时保存未截断 reviewed 树 |
| `work/copisteria/` | 逐页 OMR XML、reading JSON 和 HTML，审计证据 |

不要只交付 `.mscz`。给人看的入口依次是 `review-sheets.pdf` 和 `score.pdf`；完整目录约定见
[`references/delivery.md`](references/delivery.md)。

## 工作流

### 1. 检查输入与环境

先读 [`references/environment.md`](references/environment.md)，确认：

- Python 3.10+ 能导入本仓库 `scorepipe`；
- 独立的 copisteria 环境（Python 3.12+）、源码和模型权重可用；
- MuseScore 4 可用于 `.mscz`/PDF；只做 MusicXML 时可以不渲染；
- poppler 的 `pdfinfo`、`pdftoppm` 可用于页数统计和视觉复核。

确认 PDF 版本、页数、标题/作曲/编曲，以及是否为**单 `<part>` 乐谱**（双谱表钢琴或单行器乐/声乐；声乐+钢琴等多 `<part>` 乐谱目前会被 `scorepipe` 拒绝，遇到应先告知用户，不要盲跑），同时记录弱起、反复、移调乐器等已知信息。原始 PDF 只读。

### 2. 逐页 OMR 与机械修复

`convert.py` 通过内建 `scorepipe.copisteria` 适配器提取灰度页图并直接调用上游 `python -m copisteria.pipeline`（支持 `--detector 28m|2m`、`--device`、`--range`），再把**逐页目录**交给 scorepipe。页契约见 [`references/omr.md`](references/omr.md)。流水线按 structural → inject → display 运行到不动点，然后执行只读 verifier。

检查 `report.json`：所有阶段必须 `stable=true`，交付件的 `verifier` 必须为空；无法解释的
`measure-length`、hidden-rest 或导入差异都要追查。存在 ground truth 时再运行对应 comparator。

### 3. 收集 facts 与受限 patch

文字层只是 producer，不是 ground truth。添加 facts 前读
[`references/facts.md`](references/facts.md)。每条 credit/mark 必须有 `page`、`evidence` 和
`bbox`/`crop`；`rit.`、`rall.`、`accel.` 等渐进速度术语还必须提供 `gradual`。

```bash
python scripts/agent_facts.py prepare --pdf "score.pdf" --outdir review/facts
python scripts/agent_facts.py validate --facts review/facts/agent-page01.json --pages 2
python scripts/agent_facts.py merge --parts review/facts/agent-page*.json --pages 2 \
  -o review/facts/facts.json
```

`merge --pages N` 检查页覆盖，并另外写出 `facts-corrections.json` 和 `facts-report.json`。
音高/时值 correction 不会自动应用；接受后须通过专门编辑流程修改并重新渲染。

8va/8vb、受限 tuplet 和 clef 使用音符锚点 patch，不用像素范围直接改谱：

```bash
python scripts/notation_patches.py map --input out/score/score.musicxml -o review/score-map.json
python -m scorepipe.cli path/to/pages -o out/score/score.musicxml \
  --mscz-out out/score/score.mscz --patches review/patches.accepted.json
```

起止点必须落在真实 staff/measure/beat 上，patch 必须先被接受。渲染后检查实际覆盖范围；不确定就保留
`unresolved`。完整约束见 [`references/notation-patches.md`](references/notation-patches.md)。

### 4. 运行 review 与视觉复核

```bash
python scripts/review.py "score.pdf" --pages path/to/omr-pages \
  --facts-dir review/facts --patches review/patches.accepted.json --outdir review/score
```

缺页、`unresolved`、proposed correction 或 patch 校验失败会默认阻断 reviewed pipeline。
`--allow-unresolved` / `--allow-corrections` 只用于临时试跑，覆盖项仍留在报告中。

review 自动生成两类辅助图：

- `review/confidence/`：符号级热图。红色表示上下文改写，橙色表示存在性不确定，琥珀表示属性概率偏低；
  编号只是建议查看顺序。
- `review/sheets/` + 根目录 `review-sheets.pdf`：左侧为**最终交付乐谱**（优先 `score.mscz`，无 `.mscz` 时用修复后的 `score.musicxml`）按扫描页边界分页渲染的结果，右侧为原始扫描，同一小节同色同号，`≠` 表示时值不符；`review_sheet.md` 给出跨页核对顺序。验收时检查 `review/sheets/review_sheet_summary.json` 的 `render_mode` 应为 `score-mscz` 或 `score-musicxml`（若退回 `raw-pages` 或出现 `score_measure_count_mismatch` 需明确报告，不要当成正常对齐；`--raw-pages` 仅用于调试原始 OMR）。

两者都是审查辅助，失败记录为 finding，不代替 verifier，也不证明未标色内容正确。对齐与分档细节见
[`references/review.md`](references/review.md)。

至少重新渲染并检查：首尾系统、页缝、弱起和小节号、密集钢琴系统、跨页 tie/slur、patch 覆盖范围、
文字/credit 位置。没有新渲染，不得声称视觉问题已经修复。

### 5. 理解三棵交付树

- `mechanical/` 是无 agent facts/patches 的对照基线。基线不干净会记入 findings，但不阻止后续
  forced 修复；真正验收门是实际交付件。
- 根目录 `score.*` 是 reviewed 交付。根 `score.musicxml` 始终保持未截断的语义主文件。
- `forced-truncation/` 对 overfull voice 强制收尾以便 MuseScore 编辑，必须标记
  `semantic_authority: false`。`truncation-report.json` 列出每个删除或缩短操作，agent 必须转告用户。
- 实际发生截断时，根 `score.mscz` / `score.pdf` 来自 forced 副本，`rendered/` 与 `review-sheets.pdf` 也均基于该交付 `.mscz` 生成；未截断 reviewed 树移入 `semantic/`。不要把截断称为语义修复。

### 6. Agent 提案边界

Agent 是 producer，不是最终改谱者：

1. 对照源 PDF 页图和 `score-map.json`，不以修复后的乐谱代替原页。
2. 每个实际查看的页面都产出 `agent-pageNN.json`，并准确声明 `producer.pages`。
3. 音高/节奏疑点放入 `corrections`，8va/tuplet 等放入 `patches`，初始均为 `status: proposed`。
4. 不在提案阶段直接编辑乐谱，也不自行接受提案；validate/merge、reviewer 接受、apply、重新渲染，
   这个顺序不可省略。

完整协议见 [`references/agent-review.md`](references/agent-review.md)。

## 交付前验收

- [ ] 所有阶段 `stable=true`，实际交付件 verifier 为空。
- [ ] 页覆盖完整；`unresolved`、correction、override 和已知 OMR 缺陷均已说明。
- [ ] `mechanical/` 与 reviewed 树均保留；发生截断时 `semantic/` 和截断报告齐全。
- [ ] `score.musicxml`、`.mscz`、`score.pdf`、`review-sheets.pdf` 与报告均存在。
- [ ] 对照图已打开检查，首尾、至少一个密集页和一个页缝已人工复核。
- [ ] 已知缺陷按小节列出；保留源 PDF、`work/copisteria/` 和审查证据，不附带本机配置。

按 [`references/delivery.md`](references/delivery.md) 完成交付。若 MuseScore 不可用，只交付
MusicXML 与报告，并明确说明未生成 `.mscz`/PDF；不要伪造渲染或视觉验收结论。
