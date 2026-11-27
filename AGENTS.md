# AGENTS.md

本文件面向**开发和维护本代码库**的 Coding Agent（快速约束、架构红线与实测踩坑备忘）。
如果你是**使用本工具将 PDF 转成乐谱交付**，请遵循 [`SKILL.md`](SKILL.md)，不要混用两份契约。

---

## 项目概览与文档入口

- 核心包：`scorepipe/`（MusicXML 结构修复、facts/patches 注入、`.mscz`/`.mscx` 显示层修复、只读 verifier、置信度热图、逐小节对照图、上游 `copisteria` 适配）。
- 运维脚本：`scripts/`（`preflight.py`、`convert.py`、`review.py`、`review_sheet.py`、`review_confidence.py`、`agent_facts.py`、`notation_patches.py`）。
- 架构与规范：[`docs/DESIGN.md`](docs/DESIGN.md)、[`docs/DEVELOPMENT.md`](docs/DEVELOPMENT.md)、[`references/`](references/)。
- 本地后续大项规划：[`TODO.md`](TODO.md)（本地私有，已在 `.git/info/exclude` 忽略，**不要提交**）。

---

## 架构红线（不可破坏）

1. **一属性一写手 + 单调不动点**：
   - 每个机械 pass 必须声明 `PassSpec.owns` 与单调指标 `measure`，同 phase 内不允许两个 pass 声明同一个 `owns` 属性（`scorepipe.core.registry.validate_all` 强制检查）。
   - 新增机械 pass 后，必须在 `tests/test_pass_sanity.py` 注册对应 fixture 与契约测试（验证发声不变式、幂等性、不新增 verifier 违规）。
   - Analysis pass 和 verifier 必须严格只读（禁止修改文档）。
2. **语义权威边界**：
   - `score.musicxml` 永远保持未截断的语义主文件；`truncate_overfull_mscx`（forced-truncation）仅作用于 `.mscx` 显示层，且必须诚实记录所有删除/缩短操作。
   - 机械 pass 不得凭猜测改音高；外部视觉信息只能通过带证据的 `facts` / 受限 `patches` 注入。
3. **对照图与 OMR 边界**：
   - `review-sheets.pdf`（`scorepipe/proof_sheet/`）左列默认渲染**最终交付乐谱**（优先 `score.mscz`，无 `.mscz` 时退回修复后的 `score.musicxml`），通过注入扫描页边界分页符（`<LayoutBreak><subtype>page</subtype></LayoutBreak>` / `<print new-page="yes"/>`）一次渲染整谱；原始逐页 OMR XML 仅在显式 `--raw-pages` 时用于调试。
   - OMR 调用由内建 `scorepipe/copisteria.py` 直接执行上游 `python -m copisteria.pipeline` 完成，**不要重新引入外部 `copisteria-to-musicxml` 包装脚本或 `music21` 依赖**。
4. **多 `<part>` 合并**（已实现，仍属实验性）：
   - `loader.merge_pages` 要求每页的 part id 序列与首页一致，不一致必须报错；**绝不能静默丢弃第 2 个 part**，也不能用空小节补造。
   - 多 part 修复/截断、架子鼓 GM 映射与 `facts.parts` 注入都属实验性能力，改动时同步跑 `tests/test_multipart.py`。
5. **印刷信息不得被显示层删改**：
   - 初始拍号交给 MuseScore 自己隐藏：`<time print-object="no">` 会被导成 `<TimeSig><visible>0</visible>`（实测 4.6.5）。**不要**为了"看起来没有拍号"删除 `<TimeSig>`——已移除的 `DropFirstTimeSignature` 就是这么毁掉原谱印刷的 4/4 的。
   - 速度记号文本统一走 `scorepipe.passes.tempo_text`：`q/e/h/w`（可带附点）在写入前展开成 `♩/♪/𝅗𝅥/𝅝`。`<words>` 会被 MuseScore 原样印刷，字母 `q` 会真的印在交付件上。

---

## 实测踩坑备忘

- **`.mscx` 拍号跨谱表继承**：MuseScore 通常只在顶谱表写 `<TimeSig>`。所有遍历 `.mscx` 小节并需要拍号的逻辑，**一律复用** `scorepipe.core.mscx_invariants.iter_measures_with_meter(doc)`，禁止手写 `meters.get(id(staff), Fraction(4, 4))`。
- **MusicXML 有效拍号**：单点查询某小节生效拍号时用 `doc.effective_time_signature(measure)`，不要用 `doc.time_signature(measure) or (4.0, 4.0)`。
- **MuseScore 多页导出排序**：超过 9 页时 MuseScore 输出 `-1.svg` .. `-10.svg`（不补零），必须用 `proof_sheet._page_sort_key` 数值排序，不能直接字典序 `sorted()`。
- **循环变量作用域**：在 `page_restore.py` 等多段循环同函数里注意避免沿用上一段循环变量（如 `pitch` vs `start_pitch`）；处理 `direction` cursor 时务必覆盖 `note`、`backup`、`forward` 三类标签。
- **环境配置一致性**：`preflight.py`、`convert.py`、`review.py` 均支持 `--env` 及自动读取 `env.local.json`，优先级为 `CLI 参数 > 环境变量 > env.local.json > 自动探测`。
- **Schema 同步**：修改 `scorepipe/agent_facts.py` 或 `scorepipe/notation_patches.py` 的字段/枚举时，同步更新 `schemas/facts.schema.json` / `schemas/notation-patches.schema.json`，并运行 `tests/test_schema.py` 验证同步。
- **Windows / 非 ASCII 路径**：向 OpenCV / `pdfimages` / `copisteria` 传递的提取图片名保持纯 ASCII（`copisteria.safe_page_stem`）。
- **控制台编码**：每个 operator 脚本入口都调用 `scorepipe.console.harden_stdout()`（`tests/test_console.py` 强制检查）；GBK 控制台下 `print` 到不可编码字符会抛 `UnicodeEncodeError`（`preflight.py` 曾因此在打印表格前崩掉）。只替换不可编码字符，不要改控制台编码，否则中文路径会变乱码。
- **长度类 verifier code**：`measure-length` / `mscx-measure-length` / `tuplet-length` / `mscx-tuplet-length` 都表示"这一小节写出来的时值不对"（同一处超拍病灶的两个层级）。需要分组时**一律用** `scorepipe.core.invariants.LENGTH_CODES`——放过门（`review/helpers._only_overfull_violations`）、`timing-report`、对照图 `≠` 三处共用，禁止再手写 code 列表。
- **review 报告的退出码口径**：`pipeline_exit` 是"产出根产物的那次运行"（forced 副本升为交付时即 forced 的退出码）；未截断 reviewed 运行的退出码在 `reviewed_pipeline_exit`，其 verifier code 在 `reviewed_verifier_codes`。两者不能互相覆盖。
- **CJK 字体选择**：`proof_sheet.compose._font` 先按文字脚本排序候选（Han → msyh/simsun、谚文 → malgun、假名 → YuGothic），再用 `.notdef` 位图比对拒绝"能加载但不含该字形"的字体；Malgun 会把简体中文画成方框（实测"红莲华"三个方框）。

---

## 测试与提交约定

- **全量测试**（Windows 推荐显式禁 cacheprovider）：
  ```bash
  python -m pytest tests -q -p no:cacheprovider
  ```
- **临时文件隔离**：所有测试必须使用 `tempfile.TemporaryDirectory()`（或 `mkdtemp` + 清理），**禁止**往仓库内固定目录 `tests/.runs/` 写测试输出。
- **视觉改动必看渲染图**：涉及 `.mscx` 显示、credits/tempo 排版或 `proof_sheet/` 的改动，除跑单测外，应用真实 `.mscz` 渲染并检查输出图。
- **禁止提交的文件**：`env.local.json`、`out/`、`tests/.runs/`、`TODO.md` 及任何本机绝对路径配置。
- **提交风格**：遵循仓库现有前缀（`fix:` / `feat:` / `test:` / `docs:` / `refactor:`），按主题拆分原子 commit。
