# validation/prod：Aura 生产化验证套件

`pNN_*.aura` 会拼接 `lib.aura` 后用 `$AURA_BIN --load` 运行，输出 `@@check.<id>=pass|FAIL ...`、`@@bench.*`、`@@info.*` 和 `@@done=ok`。

```
AURA_BIN=/path/aura VAL_TIMEOUT=240 scripts/in-docker.sh 'python3 validation/prod/run_prod.py --allow-known'
```

| 文件 | 覆盖 |
|---|---|
| p01_fiber | 20k 次顺序 spawn/join 的 RSS（#4821），64 个 spinner 的 cancel 竞态（#4841，已修），取消已结束 fiber，join 的错误传播（#4823，已修） |
| p02_orch | agent-join 对出错 body 的报告（#4822，已修），scope-join 的错误计数，ask/reply 往返，300 次 ask 的吞吐，recv 的 :wait（#4825，已修）；ask 循环中途崩溃已修；退出时 SIGSEGV（#4847）在 d44d1077e 上已修，#4831 的退出竞态在高负载下仍偶发（3/80） |
| p03_cow | 8 个 fiber 并发修改 overlay（重试，无丢失更新），200 轮 rollback，overlay report 的计数 |
| p04_gc | 20 轮 gc-heap（safepoint，#4816）后存活对象完整，gc-heap-stats，在 fiber 内调用 gc-heap |
| p05_fiber_stress | 500 个 fiber 混合 raise/error/返回值，嵌套 spawn，2000 并发，10k 条 channel 消息；catch handler 内再 raise（#4838，已修） |
| p06_fiber_hangs | 取消阻塞在 channel:recv 上的 fiber 后 join（#4840），同一个 fiber join 两次（#4839）；两者均已修，曾会挂住，所以单独成文件 |
| p07_orch_deep | join 报告字段与 docs/orch-join-report.md 对照（#4832），scope 超时、未知 agent、agent body 内嵌套 scope（#4842 / #4853 已修；报告里的 restart-exhausted / restart-max 未写进文档，#4861），200 个 agent，同名重新 spawn |
| p08_cow_edge | overlay 隔离，事务外误用（#4845，已修），raise/cancel 时事务不泄漏，写写冲突先提交者胜，5000 个 define 的提交耗时，32 个 fiber 写不相交的 key |
| p09_observe_concurrent | 48 个 agent 同时 join 的报告（键集一致、symbol 载荷 #4850），8 个 agent 各自 fan-out scope（#4853，已修），scope 之间隔离，agent 运行时 8 个 fiber 并发 stats:get（d44d1077e 上 5/6 次 double free，#4860） |
| p10_fiber_cow | fiber + overlay：16 个 fiber 计数器无丢失更新，子 fiber 不读到未提交值，rollback，悬空事务，agent 写不相交 key，取消 32 个事务中的 fiber |
| p11_orch_failure | 各种 error 载荷在 agent-join 中的样子（#4850），agent→agent→scope 三层错误冒泡、agent 内多轮重试（#4853），`:on-join-fail` cancel / 拼错（#4851，已修，拼错现在抛类型错误）/ restart（#4858，已修）/ restart-n 最终成功后的报告（仍报 ok #f，#4861） |
| p12_gc_fiber | fiber、agent、channel 持有的数据在并发 gc-heap 后完整；未提交 overlay 值在 GC 后完整（#4849，已修） |
| p13_leak | 每类操作 10 批的 RSS 斜率：fiber、agent、scope、overlay、channel、eval、string/hash、try/catch（agent/scope/eval 在 d44d1077e 上已有界；channel-create 仍每个约 0.77 KB，#4854） |
| p14_edsl_errloc | 常见错误（未绑定、类型、arity、越界、宏、rule）是否报错并点名出错位置（#4855 已修：类型错误点名运算符，hash-ref 缺键报错） |
| p15_soak | 混合负载（fiber/agent/scope/COW/channel/gc）跑 `SOAK_SEC` 秒（套件默认 60，10 分钟 soak 设 600）：无失败轮次、COW 计数 = 4×轮数、后半程 RSS 有界（#4854：735135de6 上 600 s 内 100 MB → 1.06 GB；d44d1077e 上 6115 轮 102 MB → 336 MB，约 38 KB/轮，每轮耗时 28 → 139 ms，仍未有界） |

`known_failures.json` 列出对应上游 open issue 的已知失败；用 `--allow-known` 时会被容忍。`file:<name>` 表示整个文件未跑完属于已知问题。跑到 `@@done` 之后退出时崩溃（#4847）不计为失败。结果写入 `results.json` 和 `results.md`（不入库）。

最近一次结果（aura `d44d1077e`，dev:v1.1.1，`AURA_PIPELINE_STRICT=0`）：15 个文件，128 项通过、3 项已知失败（#4861 两项、#4854 channel），p09 因 #4860 有 5/6 次在 `@@done` 前崩溃（跑完的那次 6/6 通过）。60 s soak 通过；600 s soak 仍未有界（见 p15）。
