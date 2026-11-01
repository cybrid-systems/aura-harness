# validation/prod：Aura 生产化验证套件

`pNN_*.aura` 会拼接 `lib.aura` 后用 `$AURA_BIN --load` 运行，输出 `@@check.<id>=pass|FAIL ...`、`@@bench.*`、`@@info.*` 和 `@@done=ok`。

```
AURA_BIN=/path/aura VAL_TIMEOUT=240 scripts/in-docker.sh 'python3 validation/prod/run_prod.py --allow-known'
```

| 文件 | 覆盖 |
|---|---|
| p01_fiber | 20k 次顺序 spawn/join 的 RSS（#4821），64 个 spinner 的 cancel 竞态，取消已结束 fiber，join 的错误传播（#4823） |
| p02_orch | agent-join 对出错 body 的报告（#4822），scope-join 的错误计数，ask/reply 往返，300 次 ask 的吞吐，recv 的 :wait（#4825）；ask 循环会间歇崩溃（#4831） |
| p03_cow | 8 个 fiber 并发修改 overlay（重试，无丢失更新），200 轮 rollback，overlay report 的计数 |
| p04_gc | 20 轮 gc-heap（safepoint，#4816）后存活对象完整，gc-heap-stats，在 fiber 内调用 gc-heap |

`known_failures.json` 列出对应上游 open issue 的已知失败；用 `--allow-known` 时会被容忍。`file:<name>` 表示整个文件未跑完属于已知问题。结果写入 `results.json` 和 `results.md`（不入库）。
