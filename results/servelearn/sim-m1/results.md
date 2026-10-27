seeds [0, 1, 2, 3, 4], 400 tasks, noise 0.0

| config | success | held-out | window 1 / 2 / 3 / 4 | tokens / task | KEEP / ROLLBACK | retention checks / vetoes | restarts |
|---|---|---|---|---|---|---|---|
| rsi, no retention (= legacy gated) | 63.4% | 64.0% | 53 / 76 / 56 / 68 | 8,377 | 12.0 / 7.8 | – | 0 |
| rsi + retention rho=0.05, decay 50 | 62.6% | 63.4% | 53 / 76 / 56 / 66 | 8,401 | 11.8 / 8.0 | 6.2 / 0.8 | 0 |
| rsi + retention rho=0.02, decay 100 | 62.5% | 62.9% | 53 / 76 / 55 / 66 | 8,498 | 11.8 / 8.4 | 6.8 / 1.2 | 0 |
| rsi + retention strict (rho=0, no decay) | 62.7% | 63.0% | 53 / 76 / 55 / 66 | 8,461 | 11.4 / 8.4 | 7.2 / 1.8 | 0 |

| config | FS run / base (regr / recov) | HD run / base | AULC10 run / base | AUC_E (repeat) | AUC_KA | accept rate | first-KEEP latency | replay execs / served | LLM tokens / USD |
|---|---|---|---|---|---|---|---|---|---|
| rsi, no retention (= legacy gated) | 61.7 / 31.1% (4.2 / 58.2) | 63.7 / 18.8% | 62.7 / 20.5% | 2.08 (0.18) | 71.1% | 0.61 | 11.0 | 12.86 | - / - |
| rsi + retention rho=0.05, decay 50 | 61.7 / 31.1% (4.2 / 58.2) | 62.3 / 18.8% | 61.0 / 20.5% | 2.11 (0.18) | 71.8% | 0.60 | 11.0 | 18.12 | - / - |
| rsi + retention rho=0.02, decay 100 | 61.7 / 31.1% (4.2 / 58.2) | 62.1 / 18.8% | 60.5 / 20.5% | 2.13 (0.18) | 69.8% | 0.59 | 11.1 | 18.58 | - / - |
| rsi + retention strict (rho=0, no decay) | 61.7 / 31.1% (4.2 / 58.2) | 62.4 / 18.8% | 60.7 / 20.5% | 2.11 (0.17) | 71.0% | 0.58 | 10.8 | 19.07 | - / - |
