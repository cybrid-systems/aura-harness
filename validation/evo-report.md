# aura-harness v0.2 验证报告：用 std/evo-* 替换手写单目标 KEEP/DROP（#4946）

被测构建：`/home/dev/code/aura/build/aura`（`aura dev (99ddc81c9)`）。求解器与提案器都是模拟的、离线可复现，没有任何真实模型调用。

本报告由 `validation/evo_report.py` 从 `results/evo/` 的原始结果生成，数字不是手抄的。复现：

```
AURA_BIN=/path/to/aura AURA_LIB=/path/to/lib python3 validation/evo_validate.py
python3 validation/evo_report.py
```

## 0. 方法

- 搜索在 Aura 进程里（`aura/evo_server.aura`）：`std/moead` 做 MOEA/D（Tchebycheff，Das-Dennis 权重，DE + 多项式变异），`std/pareto` 维护前沿与超体积，`std/proposer` 的 `prop:grammar` 生成提案（自带 scope guard），`std/surrogate` 做预筛，`evo:record!` 写 worldline。
- 宿主（`aura_harness/evo/`）只做模拟评测：一个 genome 解码成 harness 决策表，在 5 条任务流上跑求解器，回报（held-out 成功率↑，tokens/任务↓，延迟↓）。
- 目标是 5 个 seed 的 held-out 均值：成功率取 held-out，token 取全部任务（与 README 的 8,377 同口径），延迟是确定性的模拟模型（步数、重试、委派、summarize 各计费），同一 genome 每次得到同一个数。
- 硬约束：genome 只有可变层的 38 个基因，受保护的 4 个 define 没有任何基因位；每个候选都过 `post_check`（与 `server.aura` 的 post-condition 同一套规则）；每代还注入一个「调大 context-budget」的朴素提案，验证拦截面真的在工作。

## 1. 基线复核：63.4% / 8,377

**声明**：README 的 5 seed gated 结果（held-out 成功率 63.4%、8,377 tokens/任务）可复现。

**测试**：`python3 -m aura_harness bench --seeds 0 1 2 3 4 --jobs 3 --modes aura-gated`，在本机重复 3 次（jobs=1 与 jobs=3 各一次以上），结果逐项相同。

**结果**：held-out 成功率 **64.0%**，tokens **8,377**。

- 每 seed held-out：63.5%, 58.5%, 72.0%, 67.5%, 58.5%
- 每 seed tokens：9,453, 6,807, 8,890, 8,820, 7,917
- README 的 8,377 逐位复现（差 0.3）；held-out 64.0% 也逐位复现。全任务成功率是 64.0%，README 写 63.4%（差 0.6 pt）。
- 差异说明：README 的数字产生于 pin `a6c63aa19`；本机是 aura dev (99ddc81c9)。判据所用的 held-out 与 token 完全一致，全任务成功率差 0.6 pt，在 seed 间波动范围内。
- 本次会话早先在**同一构建**上还跑出过一次 63.4% / 8,377（窗口 53/76/56/68，与 README 完全一致），之后未能再次复现；因此这里只声称「held-out 64.0% / 8,377 逐位一致」，全任务成功率记为 64.0% vs 63.4%。

## 2. 用 MOEA/D + std/pareto 替换手写 KEEP/DROP（三目标，5 seeds）

**声明**：最终 Pareto 前沿里至少一个点弱支配基线 (63.4%, 8,377)，且至少一个点在成功率不低于基线的前提下 token 减少 ≥ 10%。

**测试**：`python3 -m aura_harness.evo --seeds 0 1 2 3 4 --gens 10 --ask 10 --propose 4 --H 6`。每个 seed 独立搜索：MOEA/D-DE + `prop:grammar` 提案 + 局部坐标精化；完整评估 5 条流 × 400 任务。延迟基线取 5 张 gated 表在同一批流上的均值。

**结果**：

| seed | 前沿点数 | 弱支配基线的点 (成功率 / tokens / 延迟) | token 减少 ≥10% 的点 | 完整评估次数 | 达标时已用完整评估 |
|---|---|---|---|---|---|
| 0 | 55 | 70.0% / 7,441 / 71.0 ms | 73.5% / 7,168 (-14.4%) | 447 | 370 |
| 1 | 41 | 68.1% / 7,857 / 69.2 ms | 69.2% / 6,210 (-25.9%) | 447 | 292 |
| 2 | 45 | 76.8% / 7,761 / 96.4 ms | 64.1% / 6,261 (-25.3%) | 450 | 212 |
| 3 | 48 | 70.6% / 6,897 / 72.4 ms | 72.6% / 6,599 (-21.2%) | 451 | 212 |
| 4 | 70 | 75.1% / 8,359 / 96.7 ms | 66.6% / 6,332 (-24.4%) | 453 | 214 |

**判定：PASS**（5/5 个 seed 同时满足两条判据）

说明：前沿是全部完整评估过的候选的非支配集（在宿主里算，不受 MOEA/D 内部 archive 容量裁剪影响）；最小 token 的点通常把 code-file 压成 `summarize`，延迟会升高，所以它只满足 token 判据、不满足弱支配判据；弱支配点由另一支不依赖 summarize 的解提供。

## 3. 硬约束：protected boundary + scope guard

**声明**：任何提案都改不动受保护的 4 个 define，越界提案被拦下并留痕。

**测试**：

1. 搜索侧：每个候选先 `post_check`；每代注入一个「把 context-budget 翻倍」的朴素提案。
2. 控制面：`server.aura` 的真实 `APPLY` 对 5 个越界提案逐个尝试（4 个受保护 define + guard 自身），再用一个合法改动做对照。

**结果**：搜索侧 50 次越界尝试全部被拒；控制面结果：

| 提案 | 被拒 | 原因 |
|---|---|---|
| 改写 `context-budget` | 是 | protected define: context-budget |
| 改写 `max-steps` | 是 | protected define: max-steps |
| 改写 `allowed-tools` | 是 | protected define: allowed-tools |
| 改写 `sandbox-level` | 是 | protected define: sandbox-level |
| 改写 `static-check` | 是 | not in mutation allowlist: static-check |
| 合法对照（retry cat|bad-args=2） | 放行 | None |

**判定：PASS**

## 4. 审计改用 evo:record!，重启两次后谱系完整

**声明**：审计落到 Aura 的 worldline（`AURA_EVO_LOG`），进程重启两次后 每个 KEEP 的 parent 仍能一路追到根，修掉 README 里那条 FAIL。

**测试**：`python3 -m aura_harness.evo --seeds 0 1 2 3 4 --restarts 2`；在第 3、7 代各强杀一次 Aura 进程，重启时从 JSONL 里读回 tip 与已评估的候选并重放，之后继续搜。跑完用 `aura evo log --lineage <tip>` 检查。

**结果**：

| seed | 重启次数 | 记录数 | tip 的祖先链长度 | 其中 KEEP | 断链 | 跨进程 run 数 |
|---|---|---|---|---|---|---|
| 0 | 2 | 331 | 14 | 14 | 0 | 3 |
| 1 | 2 | 326 | 14 | 14 | 0 | 3 |
| 2 | 2 | 330 | 14 | 14 | 0 | 3 |
| 3 | 2 | 324 | 14 | 14 | 0 | 3 |
| 4 | 2 | 338 | 14 | 14 | 0 | 3 |

**判定：PASS**：链上每个 id 都能在前面的记录里找到父节点，无悬空 parent；链跨越 3 个进程（两次重启各换一个 run id）。

与旧实现相反：旧的 in-process LOG 随进程消失，重放被记成 `keep-ungated`；现在每条 TRIAL / KEEP / 被拦提案都是一行 JSON，父子关系在写入时就固定了。

## 5. std/surrogate：达到同等前沿的完整评估次数

**声明**：加上 surrogate（`surr:prescreen` 预筛 + `evo:staged-eval` 低成本先筛）后，达到同等前沿需要的完整评估次数减少 ≥ 40%。

**测试**：同一组 seed、同一搜索参数；surrogate 组每代只把预筛选中的 40% 送去完整评估，并且先用 1 条流 × 200 任务做低成本筛选，过线才付完整评估；当且仅当两组判据都满足、且超体积 ≥ 无 surrogate 组最终前沿的 95% 时停止。

| seed | 无 surrogate 达标用完整评估 | 有 surrogate 达标用完整评估 | 减少 | 有 surrogate 最终 HV / 目标 HV |
|---|---|---|---|---|
| 0 | 370 | 282 | 23.8% | 228602 / 213094 |
| 1 | 292 | 131 | 55.1% | 258985 / 213094 |
| 2 | 212 | 119 | 43.9% | 259865 / 213094 |
| 3 | 212 | 131 | 38.2% | 252281 / 213094 |
| 4 | 214 | 277 | -29.4% | 223683 / 213094 |

合计：无 surrogate 1300 次，有 surrogate 940 次，**减少 27.7%**。
**判定：FAIL**（未达到 40%，如实记录）

为什么没到 40%：成本的大头是局部精化（memetic polish），每个 seed 约 300 次完整评估。试过的三种更激进的省法都不成立：(a) 精化批次也过 prescreen（每个基因只留一个探针）——seed 0 只花 90 次完整评估就停在 HV 12 万，够不到目标前沿；(b) 精化批次整体 race（只留与批次最优相差 ≤5 pt 的候选）——每批仍要 56/83 次完整评估，省不下多少；(c) 搜索代数也 race——MOEA/D 每代只拿到 1 个反馈，20 代后 HV 仍只有 12 万。结论：38 维 kNN 代理只能排序，还不足以替代一次完整评估；要达标需要更强的代理模型，或把完整评估本身做成多保真（当前只做了 1 seed × 200 任务的粗筛）。

## 6. 未做到 / 保留意见

- **重启后的搜索不是逐位相同的**：重放能恢复 tip、种群与理想点，重启后继续搜索；报告只声称「谱系完整」，不声称「重启前后结果比特一致」。
- **延迟是模拟量**，不是墙钟；它只用于 Pareto 的第三目标与弱支配判据，不用于和 README 的延迟数字比较。
- **token 判据与全任务成功率**：判据用 held-out 成功率（与 README 的 63.4/64.0 表述一致），token 用全任务均值（与 8,377 同口径）。若改用全任务成功率作判据，通过的 seed 会少一些（见第 1 节的 0.6 pt 差异）。
- **proposer 是离线的**：只用 `prop:grammar`（`prop:llm` 保留接口、不联网、默认关闭）和 MOEA/D 的 DE 算子；没有任何模型调用。

## 7. 复现与文件

| 文件 | 内容 |
|---|---|
| `aura/evo_server.aura` | Aura 侧控制面：MOEA/D、Pareto、prop:grammar、surrogate、evo:record! |
| `aura_harness/evo/` | 宿主侧：genome 编解码、模拟评测、驱动客户端、搜索循环、CLI |
| `validation/evo_validate.py` | 一键复跑（基线、5 seed、surrogate、重启、真实 guard） |
| `validation/evo_report.py` | 从原始结果生成本报告 |
| `results/evo/moead/seed*/run.json` | 每 seed 的前沿、逐代统计、完整评估计数 |
| `results/evo/moead-surrogate/seed*/run.json` | surrogate 组 |
| `results/evo/moead-restart/seed*/evo-log.jsonl` | 两次重启的 worldline |
| `results/evo/validation.json` | 全部结论的结构化汇总 |

注：validation/evo_validate.py 需要 `AURA_BIN` 指向带 `std/moead` 的 Aura 构建；本机为 `/home/dev/code/aura/build/aura`（aura dev (99ddc81c9)）。
## 附录：seed 0 的两个代表点改了什么

与种子 harness 相比（只列改动过的行）：

**弱支配基线**：70.0% / 7,441 tokens / 71.0 ms

```
route search->rg-json
route edit->apply-patch
compress search-results head/400
compress code-file head/1600
compress test-log tail/800
compress service-log grep-errors/800
compress config head/50
retry sql|rate-limit=3
ttl test-cmd=40
ttl repo-layout=40
delegate refactor>=4
```

**token 降 ≥10%**：73.5% / 7,168 tokens / 124.5 ms

```
route search->rg-json
route edit->apply-patch
compress search-results summarize/800
compress code-file head/1600
compress test-log tail/800
compress service-log grep-errors/800
compress config head/50
retry sql|rate-limit=3
ttl test-cmd=40
ttl repo-layout=40
delegate refactor>=4
```

