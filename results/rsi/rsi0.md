seeds [0, 1, 2, 3, 4], 400 tasks, noise 0.0

| config | success | held-out | window 1 / 2 / 3 / 4 | tokens / task | KEEP / ROLLBACK | retention checks / vetoes | restarts |
|---|---|---|---|---|---|---|---|
| rsi, no retention (= legacy gated) | 63.4% | 64.0% | 53 / 76 / 56 / 68 | 8,377 | 12.0 / 7.8 | – | 0 |
| rsi + retention rho=0.05, decay 50 | 62.6% | 63.4% | 53 / 76 / 56 / 66 | 8,401 | 11.8 / 8.0 | 6.2 / 0.8 | 0 |
| rsi + retention rho=0.02, decay 100 | 62.5% | 62.9% | 53 / 76 / 55 / 66 | 8,498 | 11.8 / 8.4 | 6.8 / 1.2 | 0 |
| rsi + retention strict (rho=0, no decay) | 62.7% | 63.0% | 53 / 76 / 55 / 66 | 8,461 | 11.4 / 8.4 | 7.2 / 1.8 | 0 |
