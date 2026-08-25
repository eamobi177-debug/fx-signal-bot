"""
FX Signal Bot
- Pick currency pair & timeframe via tappable buttons
- Sends BUY/SELL signal alerts when EMA+RSI strategy fires on a closed candle
- /backtest shows historical win rate for the selected pair/timeframe
- This bot is for SIGNAL ALERTS ONLY. It does not place trades.
"""
import os
import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, CallbackQueryHandler,
    ContextTypes,
)

from data import fetch_closes, PAIRS, TIMEFRAME_MAP
from strategy import generate_signal
from backtest import run_backtest

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

BOT_TOKEN = os.environ.get("BOT_TOKEN")

POLL_SECONDS = {
    "1m": 20,
    "5m": 60,
    "15m": 120,
    "30m": 180,
    "1h": 300,
}

TIMEFRAMES = list(TIMEFRAME_MAP.keys())

chat_state = {}


def pair_keyboard():
    rows = [[InlineKeyboardButton(p, callback_data=f"pair:{p}")] for p in PAIRS]
    return InlineKeyboardMarkup(rows)


def timeframe_keyboard():
    rows = [[InlineKeyboardButton(tf, callback_data=f"tf:{tf}") for tf in TIMEFRAMES]]
    return InlineKeyboardMarkup(rows)


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = (
        "Welcome to your FX Signal Bot.\n\n"
        "This bot sends BUY/SELL alerts based on an EMA+RSI strategy on "
        "closed candles. It does NOT place trades for you — you act on "
        "the alerts yourself.\n\n"
        "No strategy wins every time. Use /backtest before trusting live "
        "alerts with real money.\n\n"
        "Pick a currency pair to begin:"
    )
    await update.message.reply_text(text, reply_markup=pair_keyboard())


async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    chat_id = query.message.chat_id
    data_str = query.data

    if data_str.startswith("pair:"):
        pair = data_str.split(":", 1)[1]
        chat_state.setdefault(chat_id, {})["pair"] = pair
        await query.edit_message_text(
            f"Pair set to {pair}.\n\nNow pick a timeframe:",
            reply_markup=timeframe_keyboard(),
        )

    elif data_str.startswith("tf:"):
        tf = data_str.split(":", 1)[1]
        state = chat_state.setdefault(chat_id, {})
        state["timeframe"] = tf
        state["last_len"] = None
        pair = state.get("pair", "GBP/USD")

        job_name = f"poll_{chat_id}"
        current_jobs = context.job_queue.get_jobs_by_name(job_name)
        for j in current_jobs:
            j.schedule_removal()
        interval = POLL_SECONDS.get(tf, 30)
        context.job_queue.run_repeating(
            poll_and_alert, interval=interval, first=5,
            data={"chat_id": chat_id}, name=job_name,
        )

        await query.edit_message_text(
            f"✅ Watching {pair} on {tf}.\n\n"
            f"You'll get an alert here when a signal fires.\n\n"
            f"Commands:\n"
            f"/backtest — see historical win rate for this pair/timeframe\n"
            f"/change — pick a different pair or timeframe\n"
            f"/stop — stop alerts"
        )


async def change(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Pick a currency pair:", reply_markup=pair_keyboard())


async def stop(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    job_name = f"poll_{chat_id}"
    jobs = context.job_queue.get_jobs_by_name(job_name)
    for j in jobs:
        j.schedule_removal()
    await update.message.reply_text("Alerts stopped. Send /start to begin again.")


async def backtest_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    state = chat_state.get(chat_id)
    if not state or "pair" not in state or "timeframe" not in state:
        await update.message.reply_text(
            "Pick a pair and timeframe first with /start."
        )
        return

    pair = state["pair"]
    tf = state["timeframe"]
    await update.message.reply_text(f"Running backtest for {pair} on {tf}... one moment.")

    closes, err = fetch_closes(pair, tf, outputsize=500)
    if err:
        await update.message.reply_text(f"Couldn't fetch data: {err}")
        return

    result = run_backtest(closes)
    if result["total_signals"] == 0:
        await update.message.reply_text(
            "No signals were generated in this historical window — "
            "try again later once more data is available."
        )
        return

    text = (
        f"📊 Backtest results — {pair} on {tf}\n"
        f"(last {len(closes)} candles)\n\n"
        f"Total signals: {result['total_signals']}\n"
        f"Wins: {result['wins']}\n"
        f"Losses: {result['losses']}\n"
        f"Win rate: {result['win_rate']}%\n\n"
        f"This is historical performance, not a guarantee of future "
        f"results. No strategy wins every trade — use this to decide "
        f"if the edge is big enough for your risk tolerance before "
        f"using live alerts with real money."
    )
    await update.message.reply_text(text)


async def poll_and_alert(context: ContextTypes.DEFAULT_TYPE):
    job = context.job
    chat_id = job.data["chat_id"]
    state = chat_state.get(chat_id)
    if not state:
        return

    pair = state["pair"]
    tf = state["timeframe"]

    closes, err = fetch_closes(pair, tf, outputsize=100)
    if err or not closes:
        return

    if state.get("last_len") == len(closes):
        return
    state["last_len"] = len(closes)

    signal, rsi_value = generate_signal(closes)
    if signal is None:
        return

    if signal == "UP":
        header = f"🟢⬆️ BUY SIGNAL — {pair}"
    else:
        header = f"🔴⬇️ SELL SIGNAL — {pair}"

    price = closes[-1]
    text = (
        f"{header}\n\n"
        f"Timeframe: {tf}\n"
        f"Price: {price}\n"
        f"RSI: {round(rsi_value, 1)}\n\n"
        f"Signal only — place the trade yourself if you choose to act on it."
    )
    await context.bot.send_message(chat_id=chat_id, text=text)


def main():
    if not BOT_TOKEN:
        raise RuntimeError("BOT_TOKEN environment variable is not set")

    app = Application.builder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("change", change))
    app.add_handler(CommandHandler("stop", stop))
    app.add_handler(CommandHandler("backtest", backtest_cmd))
    app.add_handler(CallbackQueryHandler(button_handler))

    logger.info("Bot starting...")
    app.run_polling()


if __name__ == "__main__":
    main()
