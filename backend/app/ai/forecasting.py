"""Demand forecasting (damped Holt) and suggested-order math. Plan.md §9.1-9.2."""
import math
import warnings

import numpy as np

HISTORY_WEEKS = 26
Z80 = 1.28  # 80% band
Z_SAFETY = 1.65  # ~95% service level


def _manual_holt(y: np.ndarray, h: int, alpha=0.4, beta=0.2, phi=0.9) -> tuple[np.ndarray, np.ndarray]:
    level, trend = y[0], y[1] - y[0]
    fitted = []
    for v in y:
        fitted.append(level + phi * trend)
        prev = level
        level = alpha * v + (1 - alpha) * (level + phi * trend)
        trend = beta * (level - prev) + (1 - beta) * phi * trend
    steps = np.cumsum(phi ** np.arange(1, h + 1))
    return level + steps * trend, y - np.array(fitted)


def forecast(y: list[float], h: int) -> dict:
    """Forecast h weeks ahead. Returns forecast, 80% band and residual std, all clipped at 0."""
    arr = np.asarray(y[-HISTORY_WEEKS:], dtype=float)
    try:
        from statsmodels.tsa.holtwinters import ExponentialSmoothing

        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            fit = ExponentialSmoothing(arr, trend="add", damped_trend=True, seasonal=None).fit()
        fc, resid = np.asarray(fit.forecast(h)), np.asarray(fit.resid)
        if not np.all(np.isfinite(fc)):
            raise ValueError("non-finite forecast")
    except Exception:
        fc, resid = _manual_holt(arr, h)
    sigma = float(np.std(resid, ddof=1)) if len(resid) > 1 else 0.0
    width = Z80 * sigma * np.sqrt(np.arange(1, h + 1))
    fc = np.clip(fc, 0, None)
    return {
        "forecast": fc.round(1).tolist(),
        "lower": np.clip(fc - width, 0, None).round(1).tolist(),
        "upper": (fc + width).round(1).tolist(),
        "sigma": sigma,
    }


def avg_weekly_demand(y: list[float]) -> float:
    """Average forecast demand over the next 4 weeks: the basis for weeks of cover."""
    return float(np.mean(forecast(y, 4)["forecast"]))


def severity(weeks_of_cover: float) -> str | None:
    if weeks_of_cover < 1:
        return "critical"
    if weeks_of_cover < 2:
        return "serious"
    if weeks_of_cover < 3:
        return "warning"
    if weeks_of_cover > 10:
        return "slow-moving"
    return None


def suggested_cartons(y: list[float], stock: float) -> dict:
    f = forecast(y, 2)
    next2 = sum(f["forecast"])
    safety = Z_SAFETY * f["sigma"] * math.sqrt(2)
    return {"forecast_2w": round(next2), "safety": round(safety), "stock": round(stock),
            "cartons": math.ceil(max(0.0, next2 + safety - stock))}
