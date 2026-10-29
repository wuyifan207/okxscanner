#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
OKX 山寨币扫描器核心逻辑 V3
- 只读行情，不下单
- 成交额优先用 volCcyQuote24h
- 最近 N 根已收盘K线内 EMA 金叉
- 1H 摆动结构 L1-H1-L2-H2（L2>L1, H2>H1）+ 最小波幅过滤
- 颈线状态、ATR 止损、1.5R/2R 止盈
"""

import os
import time
import math
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime

import requests
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.dates as mdates

BASE_URL = "https://www.okx.com"
TIMEOUT = 15
SESSION = requests.Session()
SESSION.headers.update({"User-Agent": "OKX-Altcoin-Scanner/3.0"})


def api_get(path, params=None, retries=3):
    last_err = None
    for attempt in range(retries):
        try:
            r = SESSION.get(BASE_URL + path, params=params, timeout=TIMEOUT)
            r.raise_for_status()
            j = r.json()
            if j.get("code") != "0":
                raise RuntimeError(f"OKX API error: {j.get('code')} {j.get('msg')}")
            return j.get("data", [])
        except Exception as e:
            last_err = e
            time.sleep(0.4 * (attempt + 1))
    raise RuntimeError(str(last_err))


def get_universe(min_turnover: float, max_turnover: float):
    instruments = api_get("/api/v5/public/instruments", {"instType": "SWAP"})
    tickers = api_get("/api/v5/market/tickers", {"instType": "SWAP"})
    tmap = {x["instId"]: x for x in tickers}
    rows = []
    for ins in instruments:
        inst = ins.get("instId", "")
        if not inst.endswith("-USDT-SWAP") or ins.get("state") != "live":
            continue
        t = tmap.get(inst)
        if not t:
            continue
        try:
            last = float(t.get("last") or 0)
            quote = t.get("volCcyQuote24h")
            if quote not in (None, "") and float(quote) > 0:
                turnover = float(quote)
                turnover_source = "OKX volCcyQuote24h"
            else:
                turnover = float(t.get("volCcy24h") or 0) * last
                turnover_source = "估算：volCcy24h×last"
            if last > 0 and min_turnover <= turnover <= max_turnover:
                rows.append({
                    "instId": inst,
                    "last": last,
                    "turnover24h": turnover,
                    "turnover_source": turnover_source
                })
        except (ValueError, TypeError):
            continue
    return rows


def get_candles(inst: str, bar: str, limit: int = 200) -> pd.DataFrame:
    data = api_get("/api/v5/market/candles", {
        "instId": inst,
        "bar": bar,
        "limit": str(min(limit, 300))
    })
    if not data:
        return pd.DataFrame()
    cols = ["ts", "open", "high", "low", "close", "vol", "volCcy", "volCcyQuote", "confirm"]
    df = pd.DataFrame(data, columns=cols)
    for c in ["open", "high", "low", "close", "vol", "volCcyQuote"]:
        df[c] = pd.to_numeric(df[c], errors="coerce")
    df["ts"] = pd.to_datetime(pd.to_numeric(df["ts"]), unit="ms", utc=True).dt.tz_convert("Asia/Shanghai")
    df = df.sort_values("ts").drop_duplicates("ts").reset_index(drop=True)
    return df[df["confirm"].astype(str) == "1"].copy().reset_index(drop=True)


def ema(s: pd.Series, n: int) -> pd.Series:
    return s.ewm(span=n, adjust=False).mean()


def cross_age(df: pd.DataFrame, fast: int, slow: int, lookback: int):
    if len(df) < slow + lookback + 3:
        return None
    f = ema(df.close, fast)
    s = ema(df.close, slow)
    for age in range(lookback):
        idx = len(df) - 1 - age
        if idx - 1 >= 0 and f.iloc[idx - 1] <= s.iloc[idx - 1] and f.iloc[idx] > s.iloc[idx]:
            return age
    return None


def calc_atr(df: pd.DataFrame, n: int = 14) -> float:
    pc = df.close.shift(1)
    tr = pd.concat([
        (df.high - df.low),
        (df.high - pc).abs(),
        (df.low - pc).abs()
    ], axis=1).max(axis=1)
    return float(tr.rolling(n).mean().iloc[-1])


def pivots(df: pd.DataFrame, r: int = 2):
    highs, lows = [], []
    h = df.high.to_numpy()
    l = df.low.to_numpy()
    for i in range(r, len(df) - r):
        if h[i] >= max(h[i - r:i + r + 1]) and any(h[i] > x for x in h[i - r:i]) and any(h[i] > x for x in h[i + 1:i + r + 1]):
            highs.append((i, float(h[i])))
        if l[i] <= min(l[i - r:i + r + 1]) and any(l[i] < x for x in l[i - r:i]) and any(l[i] < x for x in l[i + 1:i + r + 1]):
            lows.append((i, float(l[i])))
    return highs, lows


def get_structure(df: pd.DataFrame, min_sep: int = 3, max_sep: int = 45, min_amp_pct: float = 1.5):
    """寻找最近的 L1-H1-L2-H2 结构，增加最小波幅过滤"""
    d = df.tail(120).reset_index(drop=True)
    hs, ls = pivots(d, 2)
    events = sorted([(i, "H", v) for i, v in hs] + [(i, "L", v) for i, v in ls])
    merged = []
    for e in events:
        if merged and merged[-1][1] == e[1]:
            old = merged[-1]
            if (e[1] == "H" and e[2] > old[2]) or (e[1] == "L" and e[2] < old[2]):
                merged[-1] = e
        else:
            merged.append(e)

    for j in range(len(merged) - 4, -1, -1):
        seq = merged[j:j + 4]
        if [x[1] for x in seq] != ["L", "H", "L", "H"]:
            continue
        i1, h1i, i2, h2i = [x[0] for x in seq]
        l1, h1, l2, h2 = [x[2] for x in seq]
        if not (l2 > l1 and h2 > h1):
            continue
        if not (min_sep <= h1i - i1 <= max_sep and min_sep <= i2 - h1i <= max_sep and min_sep <= h2i - i2 <= max_sep):
            continue
        # 结构不能太旧
        if len(d) - 1 - h2i > 18:
            continue
        # 最小波幅过滤（L1→H1 和 L2→H2 至少要有一定幅度）
        amp1 = (h1 - l1) / l1 * 100 if l1 > 0 else 0
        amp2 = (h2 - l2) / l2 * 100 if l2 > 0 else 0
        if amp1 < min_amp_pct or amp2 < min_amp_pct:
            continue
        return {
            "l1": l1, "h1": h1, "l2": l2, "h2": h2,
            "l1_idx": i1, "h1_idx": h1i, "l2_idx": i2, "h2_idx": h2i,
            "l1_time": str(d.ts.iloc[i1]), "h1_time": str(d.ts.iloc[h1i]),
            "l2_time": str(d.ts.iloc[i2]), "h2_time": str(d.ts.iloc[h2i]),
            "neckline": h1,
            "amp1_pct": amp1, "amp2_pct": amp2
        }
    return None


def chart(inst: str, d15: pd.DataFrame, d1h: pd.DataFrame, s: dict,
          signal: str, stop: float, tp15: float, tp2: float, outdir: str) -> str:
    os.makedirs(outdir, exist_ok=True)
    fig, axs = plt.subplots(2, 1, figsize=(12, 8.5), constrained_layout=True)

    for ax, d, title, periods in [
        (axs[0], d15.tail(100), "15m", (9, 21)),
        (axs[1], d1h.tail(100), "1H", (21, 50))
    ]:
        if d.empty:
            continue
        xs = mdates.date2num(d.ts.dt.tz_localize(None).dt.to_pydatetime())
        mins = 15 if title == "15m" else 60
        w = mins / (24 * 60) * 0.62
        for x, o, h, l, c in zip(xs, d.open, d.high, d.low, d.close):
            color = "#16803c" if c >= o else "#c0392b"
            ax.vlines(x, l, h, color=color, linewidth=0.8)
            ax.add_patch(plt.Rectangle(
                (x - w / 2, min(o, c)), w,
                max(abs(c - o), max(h - l, 1e-12) * 0.002),
                facecolor=color, edgecolor=color, alpha=0.7
            ))
        for p in periods:
            ax.plot(xs, ema(d.close, p), label=f"EMA{p}", linewidth=1.15)

        if title == "1H":
            ax.axhline(s["neckline"], linestyle="--", color="#e67e22", label="颈线 (H1)", alpha=0.85, linewidth=1.3)
            ax.axhline(stop, linestyle=":", color="#c0392b", label="参考止损", alpha=0.9, linewidth=1.2)
            ax.axhline(tp15, linestyle=":", color="#27ae60", label="1.5R", alpha=0.8, linewidth=1.1)
            ax.axhline(tp2, linestyle=":", color="#1e8449", label="2R", alpha=0.8, linewidth=1.1)
            try:
                ax.scatter(
                    [mdates.date2num(pd.Timestamp(s["l2_time"]).tz_localize(None))],
                    [s["l2"]], marker="v", s=80, color="#2980b9", label="L2 更高低点", zorder=5
                )
            except Exception:
                pass

        ax.set_title(f"{title} + EMA", fontsize=11)
        ax.grid(alpha=0.25)
        ax.legend(loc="upper left", fontsize=8)
        ax.xaxis.set_major_formatter(mdates.DateFormatter("%m-%d %H:%M"))

    fig.suptitle(f"{inst}  |  {signal}", fontsize=12)
    path = os.path.join(outdir, f"{inst}.png")
    fig.savefig(path, dpi=120, bbox_inches="tight")
    plt.close(fig)
    return path


def scan_one(row: dict, args: dict) -> dict | None:
    inst = row["instId"]
    try:
        d15 = get_candles(inst, "15m", 200)
        d1h = get_candles(inst, "1H", 200)
        if len(d15) < 40 or len(d1h) < 70:
            return None

        age15 = cross_age(d15, 9, 21, args["cross_lookback"])
        age1h = cross_age(d1h, 21, 50, args["cross_lookback"])
        if age15 is None and age1h is None:
            return None

        s = get_structure(
            d1h,
            min_sep=args["min_swing_bars"],
            max_sep=args["max_swing_bars"],
            min_amp_pct=args.get("min_amp_pct", 1.5)
        )
        if not s:
            return None

        a = calc_atr(d1h, 14)
        if not math.isfinite(a) or a <= 0:
            return None

        last = float(d1h.close.iloc[-1])
        stop = s["l2"] - args["atr_buffer"] * a
        risk = last - stop
        if risk <= 0:
            return None
        risk_pct = risk / last * 100
        if risk_pct > args["max_stop_pct"]:
            return None

        if last > s["neckline"]:
            neck_state = "已突破颈线"
        elif s["neckline"] - last <= 0.5 * a:
            neck_state = "接近颈线"
        else:
            neck_state = "尚未到颈线"

        entry_low = max(last - 0.25 * a, stop + 0.05 * a)
        entry_high = last + 0.15 * a if neck_state == "已突破颈线" else min(s["neckline"], last + 0.15 * a)
        tp15 = last + 1.5 * risk
        tp2 = last + 2 * risk

        vol_confirm = False
        if len(d15) >= 21:
            vol_confirm = float(d15.vol.iloc[-1]) > float(d15.vol.tail(21).iloc[:-1].mean())

        signal_parts = []
        if age15 is not None:
            signal_parts.append(f"15m EMA9上穿EMA21（{age15}根前）")
        if age1h is not None:
            signal_parts.append(f"1H EMA21上穿EMA50（{age1h}根前）")
        sig = "；".join(signal_parts)

        status = "偏多候选" if neck_state in ("已突破颈线", "接近颈线") else "等待颈线确认"

        chart_path = chart(
            inst, d15, d1h, s, sig, stop, tp15, tp2, args["output"]
        )

        return {
            "instId": inst,
            "turnover24h_USDT": row["turnover24h"],
            "turnover_source": row["turnover_source"],
            "last_price": last,
            "signal": sig,
            "signal_status": status,
            "neckline_status": neck_state,
            "L1": s["l1"], "H1": s["h1"], "L2": s["l2"], "H2": s["h2"],
            "neckline": s["neckline"],
            "stop_loss_reference": stop,
            "stop_distance_pct": round(risk_pct, 2),
            "TP_1_5R_reference": tp15,
            "TP_2R_reference": tp2,
            "entry_watch_low": entry_low,
            "entry_watch_high": entry_high,
            "volume_above_20bar_avg_15m": vol_confirm,
            "amp1_pct": round(s["amp1_pct"], 2),
            "amp2_pct": round(s["amp2_pct"], 2),
            "last_15m_closed": str(d15.ts.iloc[-1]),
            "last_1h_closed": str(d1h.ts.iloc[-1]),
            "chart": chart_path
        }
    except Exception as e:
        return {"_error": inst, "error": str(e)}


def run_scan(args: dict, progress_callback=None) -> tuple[list, list]:
    """执行完整扫描，返回 (results, errors)"""
    universe = get_universe(args["min_turnover"], args["max_turnover"])
    universe.sort(key=lambda x: x["turnover24h"], reverse=True)
    if args.get("max_symbols"):
        universe = universe[:args["max_symbols"]]

    results = []
    errors = []
    total = len(universe)
    if total == 0:
        return results, errors

    with ThreadPoolExecutor(max_workers=max(1, args.get("workers", 4))) as ex:
        futures = {ex.submit(scan_one, r, args): r for r in universe}
        done = 0
        for f in as_completed(futures):
            done += 1
            x = f.result()
            if x and "_error" in x:
                errors.append(x)
            elif x:
                results.append(x)
            if progress_callback:
                progress_callback(done, total, len(results))
    return results, errors
