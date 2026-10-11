# Real-world export samples

These fixtures reproduce the **actual column layouts and value formats** that
trading platforms emit, so the importers are validated against reality rather
than documentation alone.

Source: sample rows from the open-source TradeTally project's test suite
(https://github.com/GeneBO98/tradetally), licensed Apache-2.0. Copyright the
TradeTally contributors. Used here unmodified as test data.

| File | Platform / export | Notable real-world traits |
|---|---|---|
| tradovate_position_history.csv | Tradovate → Position History (Apex account) | paired buy/sell rows, multiple pairs per position, P/L per pair |
| projectx_orders.csv | TopstepX / ProjectX → Orders | Bid/Ask sides, UTC offsets in timestamps, a Rejected row |
| projectx_trades.csv | TopstepX / ProjectX → Trades | one row per round trip, Fees + Commissions |
| ninjatrader_executions_eu.csv | NinjaTrader 8 → Executions (European locale) | semicolon delimiter, comma decimals, `0,62 $`, day-first dates, `MES JUN26` |
| ninjatrader_trades.csv | NinjaTrader 8 → Trades | round trips, `$` amounts, 12-hour clock, `MES 09-26` |
| tradingview_performance.csv | TradingView → Performance export | paired fills, `NASDAQ:AAPL` exchange prefix |
