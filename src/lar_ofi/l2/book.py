"""Order-book reconstruction from snapshot + incremental deltas with
sequence validation.

Generic rule (to be checked against the exchange's documentation by the
adapter that produces these events): a snapshot carries `update_id`; every
delta must carry `update_id == previous + 1`. Deltas with an id <= the
current one are stale and skipped; a larger jump is a GAP: the book is marked
unsynchronised and no top-of-book is emitted until the next snapshot.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class BookTop:
    ts: float          # epoch seconds, UTC
    bid_px: float
    bid_sz: float
    ask_px: float
    ask_sz: float

    @property
    def mid(self) -> float:
        return (self.bid_px + self.ask_px) / 2.0


@dataclass(frozen=True)
class BookSnapshot:
    ts: float
    update_id: int
    bids: tuple[tuple[float, float], ...]
    asks: tuple[tuple[float, float], ...]


@dataclass(frozen=True)
class BookDelta:
    ts: float
    update_id: int
    bids: tuple[tuple[float, float], ...] = ()   # size 0 removes the level
    asks: tuple[tuple[float, float], ...] = ()


@dataclass(frozen=True)
class Trade:
    ts: float
    price: float
    size: float
    aggressor: str  # "BUY" (lifted the ask) or "SELL" (hit the bid)


class SequenceGap(Exception):
    pass


@dataclass
class StreamReport:
    snapshots: int = 0
    deltas_applied: int = 0
    stale_deltas_skipped: int = 0
    gaps: list[tuple[int, int]] = field(default_factory=list)
    deltas_before_snapshot: int = 0
    out_of_order_ts: int = 0
    crossed_books: int = 0
    trades: int = 0

    @property
    def complete(self) -> bool:
        return (self.snapshots > 0 and not self.gaps and self.out_of_order_ts == 0
                and self.crossed_books == 0 and self.deltas_before_snapshot == 0)

    def as_dict(self) -> dict:
        return {"snapshots": self.snapshots, "deltas_applied": self.deltas_applied,
                "stale_deltas_skipped": self.stale_deltas_skipped, "gaps": self.gaps,
                "deltas_before_snapshot": self.deltas_before_snapshot,
                "out_of_order_ts": self.out_of_order_ts, "crossed_books": self.crossed_books,
                "trades": self.trades, "complete": self.complete}


@dataclass
class L2Stream:
    tops: list[BookTop]
    trades: list[Trade]
    report: StreamReport


class OrderBook:
    def __init__(self):
        self.bids: dict[float, float] = {}
        self.asks: dict[float, float] = {}
        self.update_id: int | None = None
        self.synced = False

    def apply_snapshot(self, snap: BookSnapshot) -> None:
        self.bids = {p: s for p, s in snap.bids if s > 0}
        self.asks = {p: s for p, s in snap.asks if s > 0}
        self.update_id = snap.update_id
        self.synced = True

    def apply_delta(self, delta: BookDelta) -> bool:
        """Returns True if applied, False if stale. Raises SequenceGap."""
        if not self.synced or self.update_id is None:
            raise SequenceGap("delta received before any snapshot")
        if delta.update_id <= self.update_id:
            return False
        if delta.update_id != self.update_id + 1:
            self.synced = False
            raise SequenceGap(f"expected {self.update_id + 1}, got {delta.update_id}")
        for book, levels in ((self.bids, delta.bids), (self.asks, delta.asks)):
            for p, s in levels:
                if s <= 0:
                    book.pop(p, None)
                else:
                    book[p] = s
        self.update_id = delta.update_id
        return True

    def top(self, ts: float) -> BookTop | None:
        if not self.synced or not self.bids or not self.asks:
            return None
        bp, ap = max(self.bids), min(self.asks)
        return BookTop(ts, bp, self.bids[bp], ap, self.asks[ap])


def replay(events) -> L2Stream:
    """Replay snapshots, deltas and trades in the given order."""
    book = OrderBook()
    rep = StreamReport()
    tops: list[BookTop] = []
    trades: list[Trade] = []
    last_ts = None
    for ev in events:
        if last_ts is not None and ev.ts < last_ts:
            rep.out_of_order_ts += 1
        last_ts = ev.ts if last_ts is None else max(last_ts, ev.ts)
        if isinstance(ev, Trade):
            rep.trades += 1
            trades.append(ev)
            continue
        if isinstance(ev, BookSnapshot):
            book.apply_snapshot(ev)
            rep.snapshots += 1
        elif isinstance(ev, BookDelta):
            if rep.snapshots == 0:
                rep.deltas_before_snapshot += 1
                continue
            expected = (book.update_id or 0) + 1
            try:
                applied = book.apply_delta(ev)
            except SequenceGap:
                if book.update_id is not None:
                    rep.gaps.append((expected, ev.update_id))
                continue
            if not applied:
                rep.stale_deltas_skipped += 1
                continue
            rep.deltas_applied += 1
        else:
            raise TypeError(f"unsupported event {type(ev).__name__}")
        top = book.top(ev.ts)
        if top is not None:
            if top.bid_px >= top.ask_px:
                rep.crossed_books += 1
            tops.append(top)
    return L2Stream(tops, trades, rep)
