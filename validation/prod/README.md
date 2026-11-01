# validation/prod：Aura 生产化验证套件

`pNN_*.aura` 会拼接 `lib.aura` 后用 `$AURA_BIN --load` 运行，输出 `@@check.<id>=pass|FAIL ...`、`@@bench.*`、`@@info.*` 和 `@@done=ok`。

```
AURA_BIN=/path/aura VAL_TIMEOUT=240 scripts/in-docker.sh 'python3 validation/prod/run_prod.py --allow-known'
```

| 文件 | 覆盖 |
|---|---|
| p01_fiber | 20k 次顺序 spawn/join 的 RSS（#4821），64 个 spinner 的 cancel 竞态（约 1/3 运行堆损坏，#4841），取消已结束 fiber，join 的错误传播（#4823，已修） |
| p02_orch | agent-join 对出错 body 的报告（#4822，已修），scope-join 的错误计数，ask/reply 往返，300 次 ask 的吞吐，recv 的 :wait（#4825，已修）；ask 循环中途崩溃已修，退出时的竞态仍开着（#4831） |
| p03_cow | 8 个 fiber 并发修改 overlay（重试，无丢失更新），200 轮 rollback，overlay report 的计数 |
| p04_gc | 20 轮 gc-heap（safepoint，#4816）后存活对象完整，gc-heap-stats，在 fiber 内调用 gc-heap |
| p05_fiber_stress | 500 个 fiber 混合 raise/error/返回值，嵌套 spawn，2000 并发，10k 条 channel 消息；catch handler 内再 raise（#4838） |
| p06_fiber_hangs | 取消阻塞在 channel:recv 上的 fiber 后 join（#4840），同一个 fiber join 两次（#4839）；会挂住，单独成文件 |
| p07_orch_deep | join 报告字段与 docs/orch-join-report.md 对照（#4832），scope 超时、未知 agent、agent body 内嵌套 scope（#4842），200 个 agent，同名重新 spawn |
| p08_cow_edge | overlay 隔离，事务外误用（#4845），raise/cancel 时事务不泄漏，写写冲突先提交者胜，5000 个 define 的提交耗时，32 个 fiber 写不相交的 key |

`known_failures.json` 列出对应上游 open issue 的已知失败；用 `--allow-known` 时会被容忍。`file:<name>` 表示整个文件未跑完属于已知问题。结果写入 `results.json` 和 `results.md`（不入库）。
