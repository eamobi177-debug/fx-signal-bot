"""
FX Signal Bot
- Pick one or more currency pairs (multi-select) and a timeframe via buttons
- Sends BUY/SELL signal alerts when EMA+RSI strategy fires on a closed candle
- Tracks win/loss outcome of each signal per pair, with a running tally
- /backtest shows historical win rate for a chosen pair/timeframe
- This bot is for SIGNAL ALERTS ONLY. It does not place trades.
"""
import os
import logging
from datetime import datetime, timezone
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


def pair_selection_keyboard(selected):
    rows = []
    all_selected = set(PAIRS).issubset(selected)
    all_mark = "✅ " if all_selected else ""
    rows.append([InlineKeyboardButton(f"{all_mark}All Pairs", callback_data="pairtoggle:ALL")])
    for p in PAIRS:
        mark = "✅ " if p in selected else ""
        rows.append([InlineKeyboardButton(f"{mark}{p}", callback_data=f"pairtoggle:{p}")])
    rows.append([InlineKeyboardButton("Done ➜", callback_data="pairsdone")])
    return InlineKeyboardMarkup(rows)


def timeframe_keyboard():
    rows = [[InlineKeyboardButton(tf, callback_data=f"tf:{tf}") for tf in TIMEFRAMES]]
    return InlineKeyboardMarkup(rows)


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    chat_state[chat_id] = {"selecting_pairs": set(), "timeframe": None, "pairs": {}}
    text = (
        "Welcome to your FX Signal Bot.\n\n"
        "This bot sends BUY/SELL alerts based on an EMA+RSI strategy on "
        "closed candles. It does NOT place trades for you — you act on "
        "the alerts yourself.\n\n"
        "No strategy wins every time. Use /backtest before trusting live "
        "alerts with real money.\n\n"
        "Tap to select one or more currency pairs, then tap Done:"
    )
    await update.message.reply_text(text, reply_markup=pair_selection_keyboard(set()))


async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    chat_id = query.message.chat_id
    data_str = query.data
    state = chat_state.setdefault(chat_id, {"selecting_pairs": set(), "timeframe": None, "pairs": {}})

    if data_str.startswith("pairtoggle:"):
        pair = data_str.split(":", 1)[1]
        selected = state.setdefault("selecting_pairs", set())
        if pair == "ALL":
            if set(PAIRS).issubset(selected):
                selected.clear()
            else:
                selected.update(PAIRS)
        elif pair in selected:
            selected.remove(pair)
        else:
            selected.add(pair)
        await query.edit_message_text(
            "Tap to select one or more currency pairs, then tap Done:",
            reply_markup=pair_selection_keyboard(selected),
        )

    elif data_str == "pairsdone":
        selected = state.get("selecting_pairs", set())
        if not selected:
            await query.answer("Pick at least one pair first.", show_alert=True)
            return
        await query.edit_message_text(
            f"Pairs selected: {', '.join(sorted(selected))}\n\nNow pick a timeframe:",
            reply_markup=timeframe_keyboard(),
        )

    elif data_str.startswith("tf:"):
        tf = data_str.split(":", 1)[1]
        selected_pairs = state.get("selecting_pairs", set())
        state["timeframe"] = tf
        state["pairs"] = {
            p: {"last_len": None, "pending_signal": None, "wins": 0, "losses": 0}
            for p in selected_pairs
        }

        for j in context.job_queue.jobs():
            if j.name and j.name.startswith(f"poll_{chat_id}_"):
                j.schedule_removal()

        n = max(1, len(selected_pairs))
        interval = POLL_SECONDS.get(tf, 30) * n
        for i, pair in enumerate(sorted(selected_pairs)):
            job_name = f"poll_{chat_id}_{pair}"
            context.job_queue.run_repeating(
                poll_and_alert,
                interval=interval,
                first=5 + i * 5,
                data={"chat_id": chat_id, "pair": pair},
                name=job_name,
            )

        pairs_list = ", ".join(sorted(selected_pairs))
        await query.edit_message_text(
            f"✅ Watching {pairs_list} on {tf}.\n\n"
            f"You'll get an alert here when a signal fires on any of them, "
            f"and a WIN/LOSS result with running tally after each one closes.\n\n"
            f"Commands:\n"
            f"/status — check the bot is alive and see what it's seeing\n"
            f"/backtest — see historical win rate (uses your first selected pair)\n"
            f"/change — pick different pairs or timeframe\n"
            f"/stop — stop all alerts"
        )


async def change(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    chat_state[chat_id] = {"selecting_pairs": set(), "timeframe": None, "pairs": {}}
    await update.message.reply_text(
        "Tap to select one or more currency pairs, then tap Done:",
        reply_markup=pair_selection_keyboard(set()),
    )


async def stop(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    for j in context.job_queue.jobs():
        if j.name and j.name.startswith(f"poll_{chat_id}_"):
            j.schedule_removal()
    await update.message.reply_text("Alerts stopped. Send /start to begin again.")


async def backtest_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    state = chat_state.get(chat_id)
    if not state or not state.get("pairs") or not state.get("timeframe"):
        await update.message.reply_text(
            "Pick your pairs and timeframe first with /start."
        )
        return

    tf = state["timeframe"]
    pair = sorted(state["pairs"].keys())[0]
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


async def status_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    state = chat_state.get(chat_id)
    if not state or not state.get("pairs"):
        await update.message.reply_text(
            "Not watching anything right now. Send /start to begin."
        )
        return

    tf = state.get("timeframe", "?")
    lines = [f"📡 Status — timeframe {tf}\n"]
    now = datetime.now(timezone.utc)
    for pair, pdata in sorted(state["pairs"].items()):
        last_checked = pdata.get("last_checked")
        if last_checked:
            secs_ago = int((now - last_checked).total_seconds())
            checked_str = f"{secs_ago}s ago"
        else:
            checked_str = "not checked yet"

        err = pdata.get("last_error")
        health = f"⚠️ {err}" if err else "OK"

        wins = pdata.get("wins", 0)
        losses = pdata.get("losses", 0)
        pending = "yes" if pdata.get("pending_signal") else "no"

        lines.append(
            f"{pair}: last checked {checked_str} — {health}\n"
            f"  Pending signal: {pending} | Record: {wins}W/{losses}L"
        )

    await update.message.reply_text("\n".join(lines))


async def poll_and_alert(context: ContextTypes.DEFAULT_TYPE):
    job = context.job
    chat_id = job.data["chat_id"]
    pair = job.data["pair"]
    chat = chat_state.get(chat_id)
    if not chat or pair not in chat.get("pairs", {}):
        return

    state = chat["pairs"][pair]
    tf = chat["timeframe"]

    state["last_checked"] = datetime.now(timezone.utc)

    closes, err = fetch_closes(pair, tf, outputsize=100)
    if err or not closes:
        state["last_error"] = err or "No data returned"
        return
    state["last_error"] = None

    if state.get("last_len") == len(closes):
        return
    state["last_len"] = len(closes)

    pending = state.get("pending_signal")
    if pending:
        exit_price = closes[-1]
        won = (
            (pending["direction"] == "UP" and exit_price > pending["entry_price"])
            or (pending["direction"] == "DOWN" and exit_price < pending["entry_price"])
        )
        if won:
            state["wins"] = state.get("wins", 0) + 1
            result_word = "✅ WIN"
        else:
            state["losses"] = state.get("losses", 0) + 1
            result_word = "❌ LOSS"

        action = "BUY" if pending["direction"] == "UP" else "SELL"
        wins = state.get("wins", 0)
        losses = state.get("losses", 0)
        total = wins + losses
        win_rate = round(wins / total * 100, 1) if total > 0 else 0

        result_text = (
            f"{result_word} — {action} {pending['pair']} ({pending['tf']})\n"
            f"Entry: {pending['entry_price']} → Exit: {exit_price}\n\n"
            f"📊 Running total for {pending['pair']}: {wins}W / {losses}L ({win_rate}% win rate)"
        )
        await context.bot.send_message(chat_id=chat_id, text=result_text)
        state["pending_signal"] = None

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

    state["pending_signal"] = {
        "direction": signal,
        "entry_price": price,
        "pair": pair,
        "tf": tf,
    }


def main():
    if not BOT_TOKEN:
        raise RuntimeError("BOT_TOKEN environment variable is not set")

    app = Application.builder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("change", change))
    app.add_handler(CommandHandler("stop", stop))
    app.add_handler(CommandHandler("backtest", backtest_cmd))
    app.add_handler(CommandHandler("status", status_cmd))
    app.add_handler(CallbackQueryHandler(button_handler))

    logger.info("Bot starting...")
    app.run_polling()


if __name__ == "__main__":
    main()
