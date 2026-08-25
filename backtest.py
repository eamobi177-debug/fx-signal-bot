"""
Backtest the EMA+RSI strategy against historical closes so the user
can see real win-rate numbers before trusting live alerts.
"""
from strategy import generate_signal


def run_backtest(closes, ema_fast=9, ema_slow=21, rsi_period=14):
    """
    Walk forward through historical closes, generating a signal at each
    point using only data available up to that point, then checking
    whether the NEXT candle moved in the predicted direction.

    Returns a dict with total signals, wins, losses, and win rate.
    """
    wins = 0
    losses = 0
    total = 0

    min_bars = ema_slow + 2
    for i in range(min_bars, len(closes) - 1):
        window = closes[:i + 1]
        signal, _ = generate_signal(window, ema_fast, ema_slow, rsi_period)
        if signal is None:
            continue

        next_close = closes[i + 1]
        this_close = closes[i]
        actual_direction = "UP" if next_close > this_close else "DOWN"

        total += 1
        if signal == actual_direction:
            wins += 1
        else:
            losses += 1

    win_rate = (wins / total * 100) if total > 0 else 0
    return {
        "total_signals": total,
        "wins": wins,
        "losses": losses,
        "win_rate": round(win_rate, 1),
    }
