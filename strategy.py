"""
Strategy logic: EMA crossover + RSI filter.
Pure functions so they can be reused by both the live bot and the backtester.
"""

def ema(values, period):
    """Calculate EMA series for a list of closes."""
    k = 2 / (period + 1)
    ema_values = [values[0]]
    for price in values[1:]:
        ema_values.append(price * k + ema_values[-1] * (1 - k))
    return ema_values


def rsi(values, period=14):
    """Calculate RSI series for a list of closes."""
    if len(values) < period + 1:
        return [50] * len(values)

    deltas = [values[i] - values[i - 1] for i in range(1, len(values))]
    gains = [max(d, 0) for d in deltas]
    losses = [max(-d, 0) for d in deltas]

    rsi_values = [50] * (period)
    avg_gain = sum(gains[:period]) / period
    avg_loss = sum(losses[:period]) / period

    for i in range(period, len(deltas)):
        avg_gain = (avg_gain * (period - 1) + gains[i]) / period
        avg_loss = (avg_loss * (period - 1) + losses[i]) / period
        if avg_loss == 0:
            rsi_values.append(100)
        else:
            rs = avg_gain / avg_loss
            rsi_values.append(100 - (100 / (1 + rs)))

    while len(rsi_values) < len(values):
        rsi_values.append(rsi_values[-1])
    return rsi_values[:len(values)]


def generate_signal(closes, ema_fast=5, ema_slow=13, rsi_period=14,
                     rsi_upper=60, rsi_lower=40):
    """
    Given a list of closing prices (oldest -> newest), return:
      "UP", "DOWN", or None (no signal)
    based on the most recently closed candle.

    Logic: EMA5 crosses above/below EMA13 on the last candle,
    AND RSI confirms momentum in that direction (filters weak crossovers).
    """
    if len(closes) < ema_slow + 2:
        return None, None

    fast = ema(closes, ema_fast)
    slow = ema(closes, ema_slow)
    r = rsi(closes, rsi_period)

    prev_diff = fast[-2] - slow[-2]
    curr_diff = fast[-1] - slow[-1]

    signal = None
    if prev_diff <= 0 and curr_diff > 0 and r[-1] > rsi_upper - 10:
        signal = "UP"
    elif prev_diff >= 0 and curr_diff < 0 and r[-1] < rsi_lower + 10:
        signal = "DOWN"

    return signal, r[-1]
