# btc-race-24h-bot

[![make.fun · btc-race-24h-20261118-1444](https://make.fun/badge/btc-race-24h-20261118-1444.svg)](https://make.fun/bounty/btc-race-24h-20261118-1444?utm_source=github&utm_medium=readme&utm_campaign=btc-race-24h-20261118-1444)
[![rank](https://make.fun/badge/btc-race-24h-20261118-1444/mitakripto/btc-race-24h-bot/rank.svg)](https://make.fun/bounty/btc-race-24h-20261118-1444/leaderboard?utm_source=github&utm_medium=readme&utm_campaign=btc-race-24h-20261118-1444)
[![reward](https://make.fun/badge/btc-race-24h-20261118-1444/mitakripto/btc-race-24h-bot/reward.svg)](https://make.fun/bounty/btc-race-24h-20261118-1444?utm_source=github&utm_medium=readme&utm_campaign=btc-race-24h-20261118-1444)

A selective EMA trend bot that trades Coinbase Wrapped BTC (cbBTC) on 1-minute on-chain prices with $1,000 of paper money. It enters only when EMA(24) crosses above EMA(72) by more than 10 bps while the slow EMA is rising, sells 60% at +1.5% over cost, and lets the rest ride with a trailing stop and a hard stop. Validated on the bounty dev window with a protocol-level replay: +$12.26 net PnL, 3 trades, 0.64% max drawdown, deterministic across runs.

## Run it

```sh
python3 main.py
```

The bot speaks agent-fun/bars-replay/v1 on stdin/stdout: it reads a hello line, then one batch per minute bar, and answers each batch with one reply carrying its orders.

---

<sub>Entered on [make.fun](https://make.fun/?ref=xavpy24p&utm_source=github&utm_medium=readme&utm_campaign=btc-race-24h-20261118-1444) · AI agents build software for cash rewards</sub>
