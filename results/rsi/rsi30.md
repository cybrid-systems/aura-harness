seeds [0, 1, 2, 3, 4], 400 tasks, noise 0.3

| config | success | held-out | window 1 / 2 / 3 / 4 | tokens / task | KEEP / ROLLBACK | retention checks / vetoes | restarts |
|---|---|---|---|---|---|---|---|
| rsi, no retention (= legacy gated) | 62.9% | 64.6% | 51 / 77 / 56 / 68 | 8,193 | 12.0 / 8.4 | – | 0 |
| rsi + retention rho=0.05, decay 50 | 62.8% | 64.6% | 51 / 77 / 56 / 67 | 8,329 | 12.0 / 8.4 | 5.4 / 0.2 | 0 |
| rsi + retention rho=0.02, decay 100 | 62.3% | 64.1% | 51 / 77 / 55 / 66 | 8,247 | 11.8 / 8.6 | 6.0 / 1.0 | 0 |
| rsi + retention strict (rho=0, no decay) | 62.2% | 64.1% | 51 / 77 / 55 / 66 | 8,263 | 11.6 / 8.6 | 6.4 / 1.2 | 0 |
