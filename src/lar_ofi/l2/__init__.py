"""MODE B — event-level L2 analytics (optional, disabled by default).

Nothing here can be fed from screenshots. Every metric needs a replayed,
sequence-validated stream of order-book events (snapshot + deltas) and,
for replenishment, trades. Until such a stream exists and `l2.enabled` is
true in the configuration, `compute_l2_metrics` refuses to run.
"""

from lar_ofi.l2.book import (BookDelta, BookSnapshot, BookTop, L2Stream, SequenceGap, Trade,
                             replay)
from lar_ofi.l2.metrics import (InsufficientL2Data, L2DataUnavailable, L2Disabled, compute_l2_metrics,
                                fit_price_impact, ofi, ofi_by_interval, ofi_contribution,
                                queue_imbalance, replenishment_times)

__all__ = [
    "BookDelta", "BookSnapshot", "BookTop", "L2Stream", "SequenceGap", "Trade", "replay",
    "InsufficientL2Data", "L2DataUnavailable", "L2Disabled", "compute_l2_metrics", "fit_price_impact",
    "ofi", "ofi_by_interval", "ofi_contribution", "queue_imbalance", "replenishment_times",
]
