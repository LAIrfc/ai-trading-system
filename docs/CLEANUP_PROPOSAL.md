# 目录整理建议（已全部执行 2026-03-04）

以下为「可合并」「可删除」「小修复」三类；**已按「全做」执行完毕**。保留本文档供对照。

---

## 一、可合并的文档

| 编号 | 建议 | 说明 |
|------|------|------|
| **M1** | 合并 **DESKTOP_QUICKSTART** + **DESKTOP_TRADING_GUIDE** | 两篇都是桌面交易，前者 5 分钟快速开始，后者详细。合并为一篇《桌面交易指南》，前半快速开始、后半详细步骤。 |
| **M2** | 合并 **DUAL_MOMENTUM_WORKFLOW** 进 **DUAL_MOMENTUM_GUIDE** | WORKFLOW 作为 GUIDE 的一节「完整工作流」，避免两篇重复。 |
| **M3** | V33 文档合并为 2 篇 | 当前 4 篇：V33_DESIGN_SPEC、V33_IMPLEMENTATION_PLAN、V3_DESIGN_REVIEW、V33_落地与状态。建议：保留《V33 设计规格》（合并 SPEC+PLAN+REVIEW）+《V33 落地与状态》，共 2 篇。 |
| **M4** | 合并 **WINDOWS_README** 进 **README.md** | WINDOWS_README 实为「Windows 快速导航+链到 WINDOWS_GUIDE」。在 README 的 Windows 小节加一段 3 分钟快速步骤 + 链接到 docs/setup/WINDOWS_GUIDE.md，然后删除 WINDOWS_README.md。 |

**你选：** M1 / M2 / M3 / M4 中哪些执行？（可填「全做」或「M1,M3」等）

---

## 二、可删除或移走的项

| 编号 | 建议 | 说明 |
|------|------|------|
| **D1** | 删除 **docs/reports/** 目录 | 该目录下为示例/历史报告（如 daily_recommendation_2026-02-25.md、CROSS_VALIDATION_REPORT.md）。实际报告在 **mydate/daily_reports/** 生成。删除后可在 docs/analysis 或 README 中写一句「报告输出在 mydate/daily_reports」。 |
| **D2** | 精简 **examples** 桌面/同花顺示例 | 当前 3 个：desktop_trading_demo、desktop_trading_auto、tonghuashun_simulator。后两个都调桌面端，可能重叠。是否保留 1 个「桌面交易示例」即可？或保留 demo + auto 两个（一个演示、一个自动）？ |
| **D3** | 清理 **.gitignore** 中根目录 **data/** | 项目实际使用 mydate/、mycache/，根目录 data/ 已不用。是否删除 .gitignore 里对 data/ 及 data/market_data 等子目录的忽略规则？ |

**你选：** D1 / D2 / D3 是否执行？D2 若执行，选「保留 1 个」还是「保留 demo+auto」？

---

## 三、不删除、只整理/重命名

| 编号 | 建议 | 说明 |
|------|------|------|
| **R1** | **tools/testing** 改名为 **tools/validation** | 与 **tests/**（单元测试）区分开，表示「验证/手工测试工具」。需同步改 tools/README、DIRECTORY_OVERVIEW 中的引用。 |
| **R2** | **docs/STRATEGY_HOLD_REASONS.md** 移到 **docs/strategy/** | 与策略文档放一起，便于查找。 |

**你选：** R1 / R2 是否执行？

---

## 四、小修复（无需确认，可直接做）

- **WINDOWS_README.md** 中路径笔误：`scripts/scripts/start_windows.bat` → `scripts/start_windows.bat`。
- **DIRECTORY_OVERVIEW.md** 中「最后更新」日期、策略数量等若有出入，顺带更新。

---

请直接回复你的选择，例如：

- 「M1 M2 M4，D1 D3，R2，小修复都做」
- 「只做 M1 和 D1，其他都不动」
- 「全做」

我按你的选择执行合并/删除/重命名，并更新 DIRECTORY_OVERVIEW 与相关链接。
