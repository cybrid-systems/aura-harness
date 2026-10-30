# aura-harness 验证报告：RSI 与它依赖的 Aura 能力

2026-10-30（UTC+8）。Aura **main 69d360068**（CI 镜像 `ghcr.io/cybrid-systems/dev:v1.0.9` 构建，下称 main）。A/B 对照用仓库原 pin **a6c63aa19**（下称 pin）。机器：8 核 / 16 GB 的共享机器，负载 4–50 不等，所以延迟数字只在同一时段的 A/B 内比较。

全部脚本在本目录。`run_all.sh` 一键复跑，`ab.sh` 做 main/pin 对照，结果（JSON / 文本）在 `results/`。

| 文件 | 内容 |
|---|---|
| `rsi_validate.py` | RSI 深度验证：`invariants` / `improve <noise>` / `repro` / `faults` / `safety` |
| `harm_forward.py`, `harm_stat.py` | 有害但合法的候选：better() 门控与统计准入各放过多少，前向代价多大 |
| `protocol_probe.py` | TRIAL 与 VERDICT 之间插入另一个 APPLY：ws / snap 模式的 lost update |
| `audit_restart.py` | 进程重启后的审计 LOG 完整性 |
| `probes/*.aura` + `run_probes.sh` / `runone.py` | 直接测 Aura 原语（merge / restore / fiber worldline / 历史增长） |

## 1. RSI（重点）

RSI 循环（`aura_harness/rsi/loop.py`）的流程：提议候选 → `TRIAL`（子 worldline，ws 或 snapshot）→ 在留出任务上做成对回放门控 `better()` → `VERDICT` KEEP / ROLLBACK。守卫（符号白名单 + 解析器 + fuel + post-check）挡住越界改动。`SupervisedAura` 在进程崩溃后靠 host ledger 重放恢复状态。

### 1.1 声明 → 测试 → 结果

| # | 声明 | 测试 | 结果 |
|---|---|---|---|
| R1 | TRIAL 不改 root；ROLLBACK 后 root 不变；KEEP 后 root 等于被选中候选的 trial 表；版本号等于 ledger 长度；PROTECTED 边界不变；APPLY 只改自己的组件 | `invariants`：Checked 代理每次调用前后经原始管道读 TABLE / SOURCE / VERSION / GUARD；ws / snap / stat / pruner 4 种配置 × 5 个 seed | **PASS**：20 次运行，329 TRIAL、329 VERDICT、0 违例 |
| R2 | 迭代确实带来提升（README：63.4% vs 冻结 24.1%） | `improve 0.0`：5 seed × 400 任务 | **PASS**：RSI 63.35% vs 冻结 24.1%；第 2 个窗口 33.6→76.0%，第 4 个窗口 17.6→68.0%；4/5 个 seed 的学习曲线单调（允许 2 pt 回落） |
| R2b | 提升不是对评测流过拟合 | 最终表与种子表在**独立任务流**（`make_stream(s+1000)`）上对比 | **PASS**：分布漂移后 14.6%→71.3%，漂移前 28.5%→57.2% |
| R2c | 每个 KEEP 在未来任务上也有用 | 每个 KEEP 前后各用全新 Memory 跑接下来 100 个任务 | noise 0：45 个正向、12 个持平（其中 7 个更省）、**2 个负向（3%）**；noise 0.3：44 / 8 / **7（12%）**；noise 1.0：18 / 15 / **5（13%）** |
| R2d | 噪声下仍有提升（README：0.3→62.9%，1.0→37.8%） | `improve 0.3`、`improve 1.0` | **PASS**：62.9%、37.8%，与 README 一致 |
| R3 | 可复现 | `repro`：同一 seed 跑两次、ws vs snap、jobs 1 vs 2、对比仓库内 `results/rsi/rsi0.json` | **PASS**：5 个 seed 全部逐项相同（success / keep / rollback，如 seed 3 = 0.6825 / 12 / 5），与 rsi0.json 完全一致 |
| R4 | 迭代中途崩溃后状态可恢复且结果不变 | `faults`：在每个 backend 调用点注入 kill（27 个）、管道层随机 kill（单次 / 相邻两次）、ledger 重放中崩溃、异步 SIGKILL 线程（10 次运行，36–39 次 kill）、截断的 JSONL ledger | 修复前 **FAIL**：27 个调用点中 3 个报错（ValueError: closed file）；相邻两次 kill 时 30 次中 26 次报错、3 次结果不同；重放中崩溃直接中止；异步 kill 10 次中 2 次报错、1 次不同；截断的 ledger 无法加载。**修复后（本次提交）全部 PASS**：27/27、30/30、30/30、恢复成功、10/10、可加载 |
| R5 | 守卫挡住越界改动，并且 root 不受影响 | `safety`：20 个逃逸样本 × ws / snap | **PASS**：18 个越界全部被挡（string->symbol、apply、`*boundary*`、自递归 fuel、无限分配、make-vector、栈递归、追加 define、括号注入、转义引号、返回符号、net-raw 拼接、值域、大小写 / 空格名），2 个合法对照被放行，root 完好。fuel 拦截每次约 1–1.3 s |
| R6 | 门控不会接受有害改动 | proposer 混入 2 个合法但有害的候选（"compress all head/50"、"ttl all 0"） | **部分 FAIL**：better() 在 4/5 个 seed 中共 KEEP 了 8 次 "ttl all 0"。门控时留出集（约 40 任务）上多成功 1–4 个；前向 100 任务的成功数变化为 −4 / 0 / 0 / +2 / −2 / 0 / −1 / −2，**成本每次上升 5–23%**；seed 1 最终成功率 0.56（干净 0.59），seed 3 为 0.67（干净 0.6825）。这与 README 自己承认 better() 有 29–32% 误 KEEP 一致 |
| R6b | 统计准入（M5b）挡住有害候选 | `harm_stat.py` | 挡住了（0 次有害 KEEP），但 n=400 时总共只有 0–1 个 KEEP，成功率约 24%，与冻结相当：在模拟世界里太保守、太慢 |
| R7 | 审计 LOG 可追溯每个改动 | `audit_restart.py`：注入 2 次重启 | **FAIL（harness）**：verdict 序列不变，但 Aura 进程内 LOG 随进程丢失（keep 8→3，trial-ws 36→18）；重放的 5 个 KEEP 记成 "keep-ungated"，归因错误。持久可信的只有 host ledger |
| R8 | 多 actor 并发下 KEEP 不吞掉别人的改动 | `protocol_probe.py`：TRIAL compress → 另一个 actor APPLY route=rg-json → VERDICT KEEP | **ws 模式 FAIL**：KEEP 后 route 回到 grep，APPLY 丢失，而 LOG 里有 keep-ungated、版本号为 2；snapshot 模式正确。根因是 Aura #4776。当前 RSI 循环单线程、不交错，所以是潜在问题 |

### 1.2 本次对 harness 的修复（`aura_harness/rsi/supervisor.py`、`ledger.py`）

- `table` / `source` / `log` / `prov` 重试时调用的是**旧进程的 bound method**（`self._call(self.h.table, …)`），重启后撞上已关闭的管道，抛出 ValueError，而 ValueError 又不在捕获范围内。改为 lambda，在调用时再解析 `self.h`，并把 "closed file" 视为崩溃。
- 重启后的 ledger 重放中再次崩溃时没有处理，整个 run 中止。现在 `_restart` 最多重试 3 次。`_call` 也最多重试 3 次（原来第二次崩溃就把候选当作 blocked，结果因此偏离）。
- 进程被 kill 时，读到的回复可能只剩半行 JSON（JSONDecodeError）。现在进程已退出时，这一情况同样按崩溃处理。
- Ledger 加载时丢弃被截断的**最后一行**（崩溃发生在追加途中），并记录在 `Ledger.torn`；文件中间有损坏则照样报错。
- 新增测试：`test_ledger_drops_torn_last_line`、`test_supervisor_restart_on_first_and_last_call`、`test_supervisor_crash_during_replay`。全量 135 + 3 个测试通过（main，`AURA_PATH=$AURA_LIB`）。

未修、留给后续：
- R7 的 LOG 归因：重放 APPLY 应带上原 actor 和 verdict，或把 host ledger 当作唯一审计来源；
- R6 better() 误 KEEP：建议默认加成本约束（成本上升 >5% 不 KEEP），或在门控之后做前向验证；
- R8：ws 模式的 KEEP 应校验 root 版本没有变化（类似 CAS），变化了就 ROLLBACK 或重做 TRIAL。

## 2. RSI 依赖的 Aura 原语（probes）

`results/probes-main.txt` 和 `results/probes-pin.txt` 是同一组脚本在两个构建上的输出。

| 原语 / 声明 | 探针 | main 69d360068 | pin a6c63aa19 | issue |
|---|---|---|---|---|
| `workspace :merge` 只合并子改过的 define | p1 | **FAIL**：fork 后 root 改的 g 被回退到 fork 时的值，结果里 g 也标成 "merged"，源码里也是旧值 | 同 main | [#4776](https://github.com/cybrid-systems/aura/issues/4776) |
| 双方都改同一个 define 时报冲突 | p2 | **FAIL**：静默取子的值 | 同 main | #4776 |
| merge 已删除的 workspace 时报错 | p3 | 静默返回 `#f` | 同 main | #4776 |
| merge 保留 mutation log / provenance（#4729） | p4 | PASS（root log 2→3） | FAIL（log 为空） | 已修 |
| merge 之后 `ast:restore` 能回滚 | p5 / p5b | **FAIL**：源码恢复了，运行时 f 仍是 merge 进来的值；只有 set-code 能修好 | 同 main | [#4777](https://github.com/cybrid-systems/aura/issues/4777) |
| 每个 fiber 驱动自己的子 worldline | p6 | **FAIL 5/5**：串扰，并改写 root | PASS 5/5 | [#4778](https://github.com/cybrid-systems/aura/issues/4778) |
| 3000 次 trial+merge 后 root rebind 不变慢（#4610） | p7c | **FAIL**：27→245 ms / 100 次 rebind，RSS **3716 MB** | PASS：25 ms 平坦，193 MB | [#4779](https://github.com/cybrid-systems/aura/issues/4779) |
| 3000 次只 trial（create / rebind / delete） | p7b | 28→110 ms | 27→40 ms | #4779 |
| 3000 次只 root rebind（#4583 线性部分） | p7d | 27→101 ms | 24→116 ms | #4779（两边都有，属于残留） |

p5 对 RSI 的影响：server.aura 的 `merge-root!` 在 post-check 失败时用 `ast:restore` 回滚。按 p5 的行为，SOURCE 会显示旧代码，运行时却还在执行没通过检查的新代码。p1 / p2 让 ws 模式在多 actor 下吞掉改动（R8）。p6 意味着 README Next steps 里"用并行 fiber 跑 worldline"在 main 上不安全。

## 3. 基准（同一时段 A/B，`results/ab-latency.txt`、`longrun600-*.json`）

| | main 69d360068 | pin a6c63aa19 | README（pin，低负载） |
|---|---|---|---|
| 守卫变更往返 | 17.1 ms | 11.3 ms | 8.4 ms |
| 进程内 guarded apply / trial ws | 14.5–16.0 / 14.7–15.5 ms | 9.9–10.3 / 10.8–11.5 ms | 6.9 / 7.9 ms |
| decision 往返 | 0.25 ms | 0.21 ms | 0.15 ms |
| 文件编辑 + 重启（对照） | 29.1 ms | 28.3 ms | 29.5 ms |
| longrun 600 步 APPLY p50 / TRIAL p50 / RSS | 115 ms / 229 ms / 288 MB | 69 ms / 210 ms / 350 MB | — |
| longrun 1000 步（main，`longrun-main.json`）step 900 | APPLY 218 ms / TRIAL 326 ms / RSS 385 MB | — | README：step 1000 APPLY 42 ms，"no restart advice needed" |

结论：在同等负载下 main 比 pin 慢约 1.5 倍；内存略好；两边的 APPLY / TRIAL 都随步数线性增长（README 说"不需要定期重启"，这在两个构建上都不成立）。绝对值受机器负载影响，比 README 高。

## 4. 风险

1. 多 actor / swarm / 用户回滚与 ws 模式 KEEP 交错时会静默丢改动（#4776，R8）。在 Aura 修复前，多 actor 场景请用 snapshot 模式，或在 KEEP 时校验 root 版本。
2. KEEP 的 post-check 失败后，restore 会造成"审计看到的不是实际在跑的"（#4777）。
3. 升级到 main 后长时间运行：merge 的内存与耗时增长（#4779），3000 次 KEEP 后 RSS 3.7 GB，需要定期重启。
4. better() 会 KEEP 有害但合法的改动（R6）；统计准入又太慢（R6b）。
5. 并行 fiber worldline 在 main 上不可用（#4778）。
6. 本机负载高，延迟绝对值偏大；main vs pin 的倍数来自同一时段，可信。
