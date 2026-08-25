# FX Signal Bot

Sends BUY/SELL alerts to Telegram based on an EMA(9/21) crossover + RSI
filter strategy, on a currency pair and timeframe you pick via buttons.

**This bot sends signal alerts only. It does not place trades for you.**
No strategy wins every time — use /backtest before trusting live
alerts with real money.

## Environment variables (required)
- BOT_TOKEN — your Telegram bot token from BotFather
- TWELVE_DATA_API_KEY — your Twelve Data API key

## Commands
- /start — pick currency pair and timeframe
- /backtest — see historical win rate for the current pair/timeframe
- /change — switch pair/timeframe
- /stop — stop alerts
