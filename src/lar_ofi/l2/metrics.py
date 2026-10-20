"""L2 metrics computed from a validated event stream.

* ofi_contribution / ofi: Order Flow Imbalance at the best quotes as defined
  by Cont, Kukanov & Stoikov (2014): for consecutive best-quote states n-1, n

      e_n = 1{Pb_n >= Pb_n-1} qb_n - 1{Pb_n <= Pb_n-1} qb_n-1
          - 1{Pa_n <= Pa_n-1} qa_n + 1{Pa_n >= Pa_n-1} qa_n-1

  and OFI over an interval is the sum of e_n for events inside it.
* fit_price_impact: OLS of mid-price change on OFI per interval (the paper's
  linear model dP = beta * OFI + eps); beta is expected to scale inversely
  with depth. Here it is an estimate on the user's data, nothing more.
* queue_imbalance: (qb - qa) / (qb + qa) at the best quotes, as in Gould &
  Bonart (2016). Their result concerns the NEXT mid-price move on Nasdaq
  stocks; it is not a 5-minute BTCUSDT predictor.
* replenishment_times: PROJECT measure (not Large's 2007 Hawkes estimator):
  after an aggressive trade, seconds until best-level depth on the hit side
  returns to >= `fraction` of its pre-trade size at the same or better price.
"""

from __future__ import annotations

from lar_ofi.l2.book import BookTop, L2Stream


class L2Disabled(RuntimeError):
    pass


class L2DataUnavailable(RuntimeError):
    pass


class InsufficientL2Data(ValueError):
    pass


def ofi_contribution(prev: BookTop, cur: BookTop) -> float:
    e = 0.0
    if cur.bid_px >= prev.bid_px:
        e += cur.bid_sz
    if cur.bid_px <= prev.bid_px:
        e -= prev.bid_sz
    if cur.ask_px <= prev.ask_px:
        e -= cur.ask_sz
    if cur.ask_px >= prev.ask_px:
        e += prev.ask_sz
    return e


def ofi(tops: list[BookTop]) -> float:
    if len(tops) < 2:
        raise InsufficientL2Data("OFI needs at least two consecutive best-quote states")
    return sum(ofi_contribution(a, b) for a, b in zip(tops, tops[1:]))


def ofi_by_interval(tops: list[BookTop], interval_s: float) -> list[dict]:
    """Partition by fixed intervals from the first event. Each event's
    contribution is assigned to the interval containing the later state."""
    if len(tops) < 2:
        raise InsufficientL2Data("OFI needs at least two consecutive best-quote states")
    t0 = tops[0].ts
    buckets: dict[int, dict] = {}
    for prev, cur in zip(tops, tops[1:]):
        k = int((cur.ts - t0) // interval_s)
        b = buckets.setdefault(k, {"k": k, "t_start": t0 + k * interval_s, "ofi": 0.0, "n_events": 0,
                                   "mid_start": prev.mid, "mid_end": cur.mid})
        b["ofi"] += ofi_contribution(prev, cur)
        b["n_events"] += 1
        b["mid_end"] = cur.mid
    out = []
    for k in sorted(buckets):
        b = buckets[k]
        b["mid_change"] = b["mid_end"] - b["mid_start"]
        out.append(b)
    return out


def queue_imbalance(top: BookTop) -> float:
    total = top.bid_sz + top.ask_sz
    if total <= 0:
        raise InsufficientL2Data("empty best queues")
    return (top.bid_sz - top.ask_sz) / total


def fit_price_impact(ofi_values: list[float], mid_changes: list[float]) -> dict:
    n = len(ofi_values)
    if n != len(mid_changes) or n < 3:
        raise InsufficientL2Data("price-impact fit needs >= 3 paired intervals")
    mx, my = sum(ofi_values) / n, sum(mid_changes) / n
    sxx = sum((x - mx) ** 2 for x in ofi_values)
    if sxx == 0:
        raise InsufficientL2Data("OFI has no variation")
    sxy = sum((x - mx) * (y - my) for x, y in zip(ofi_values, mid_changes))
    beta = sxy / sxx
    alpha = my - beta * mx
    ss_res = sum((y - alpha - beta * x) ** 2 for x, y in zip(ofi_values, mid_changes))
    ss_tot = sum((y - my) ** 2 for y in mid_changes)
    return {"beta": beta, "alpha": alpha, "r2": 1 - ss_res / ss_tot if ss_tot else None, "n": n}


def average_best_depth(tops: list[BookTop]) -> float:
    if not tops:
        raise InsufficientL2Data("no book states")
    return sum((t.bid_sz + t.ask_sz) / 2 for t in tops) / len(tops)


def replenishment_times(stream: L2Stream, fraction: float, max_wait_s: float) -> list[dict]:
    """`fraction` and `max_wait_s` are UNCALIBRATED user parameters."""
    tops = stream.tops
    if len(tops) < 2:
        raise InsufficientL2Data("replenishment needs book states before AND after trades; "
                                 "a single snapshot cannot measure it")
    out = []
    for tr in stream.trades:
        before = [t for t in tops if t.ts <= tr.ts]
        after = [t for t in tops if tr.ts < t.ts <= tr.ts + max_wait_s]
        if not before:
            continue
        pre = before[-1]
        if tr.aggressor == "BUY":
            pre_px, pre_sz = pre.ask_px, pre.ask_sz
            ok = [t for t in after if t.ask_px <= pre_px and t.ask_sz >= fraction * pre_sz]
        else:
            pre_px, pre_sz = pre.bid_px, pre.bid_sz
            ok = [t for t in after if t.bid_px >= pre_px and t.bid_sz >= fraction * pre_sz]
        out.append({"trade_ts": tr.ts, "aggressor": tr.aggressor, "pre_level_px": pre_px,
                    "pre_level_sz": pre_sz,
                    "replenished_after_s": (ok[0].ts - tr.ts) if ok else None,
                    "observed_window_s": max_wait_s, "states_after": len(after)})
    return out


def compute_l2_metrics(stream: L2Stream | None, cfg: dict, interval_s: float = 10.0,
                       replenish_fraction: float | None = None, replenish_max_wait_s: float | None = None) -> dict:
    if not cfg.get("l2", {}).get("enabled", False):
        raise L2Disabled("MODE B is disabled (l2.enabled = false). No OFI / queue imbalance / resiliency "
                         "is computed without a real event-level L2 stream.")
    if stream is None:
        raise L2DataUnavailable("no L2 event stream supplied")
    if not stream.report.complete:
        raise L2DataUnavailable(f"L2 stream failed validation: {stream.report.as_dict()}")
    buckets = ofi_by_interval(stream.tops, interval_s)
    out = {
        "stream_report": stream.report.as_dict(),
        "interval_s": interval_s,
        "ofi_intervals": buckets,
        "queue_imbalance_last": queue_imbalance(stream.tops[-1]),
        "average_best_depth": average_best_depth(stream.tops),
        "labels": {"ofi": "OFI (Cont, Kukanov & Stoikov 2014 definition, best quotes)",
                   "queue_imbalance": "Queue imbalance (Gould & Bonart 2016 definition)",
                   "replenishment": "Project measure inspired by the resiliency concept (Large 2007); "
                                    "not Large's Hawkes impulse-response estimator"},
    }
    try:
        out["price_impact_fit"] = fit_price_impact([b["ofi"] for b in buckets], [b["mid_change"] for b in buckets])
    except InsufficientL2Data as exc:
        out["price_impact_fit"] = f"NOT_ESTIMATED: {exc}"
    if replenish_fraction is not None and replenish_max_wait_s is not None:
        out["replenishment"] = replenishment_times(stream, replenish_fraction, replenish_max_wait_s)
    else:
        out["replenishment"] = "NOT_COMPUTED: fraction/max_wait not configured (uncalibrated parameters)"
    return out
