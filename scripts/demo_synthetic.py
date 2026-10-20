"""End-to-end demonstration on SYNTHETIC data.

Runs import -> observations -> analysis -> journal -> resolution ->
evaluation in a temporary directory. The screenshots are 1x1 placeholder
PNGs and the price bars are invented: the output demonstrates mechanics only
and is NOT evidence of any trading performance.

Usage: python scripts/demo_synthetic.py OUTPUT_DIR
"""

from __future__ import annotations

import json
import sys
from datetime import timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tests"))

from conftest import CONTINUATION_LONG_OBS, FAILED_AUCTION_SHORT_OBS, T0, Env  # noqa: E402
from lar_ofi.config import load_config  # noqa: E402
from lar_ofi.engine import assess  # noqa: E402
from lar_ofi.evaluation import evaluate, render_evaluation_markdown  # noqa: E402
from lar_ofi.journal import import_price_bars, record_prediction, resolve_predictions, verify_journal  # noqa: E402
from lar_ofi.report import build_report, write_report  # noqa: E402


def main(out_dir: str) -> None:
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    env = Env(out / "work")
    env.data_dir = out / "work" / "data"
    env.cfg = load_config(overrides={"evaluation": {"neutral_band_bps": 2.0}})
    scenarios = [("continuation_long", CONTINUATION_LONG_OBS, T0),
                 ("failed_auction_short", FAILED_AUCTION_SHORT_OBS, T0 + timedelta(minutes=30))]
    for name, obs, t in scenarios:
        ds = env.scenario(obs, name=name, t0=t, import_time=t + timedelta(minutes=1))
        inp = env.engine_input(ds, as_of=t)
        report = build_report(assess(inp, env.cfg), inp, env.cfg, env.data_dir)
        write_report(report, out, f"SYNTHETIC_{name}")
        rec = record_prediction(env.conn, report, inp, env.cfg, recorded_at=t + timedelta(seconds=20))
        print(f"{name}: decision={report['decision']} prediction_id={rec['prediction_id']}")
    lines = ["open_time_utc,open,high,low,close"]
    for i in range(120):  # invented path: up for 45 min, then down
        o = 68000 + (10 * i if i < 45 else 450 - 12 * (i - 45))
        c = o + (10 if i < 45 else -12)
        lines.append(f"{(T0 - timedelta(minutes=30) + timedelta(minutes=i)).strftime('%Y-%m-%dT%H:%M:%SZ')},"
                     f"{o},{max(o, c) + 3},{min(o, c) - 3},{c}")
    (out / "SYNTHETIC_bars.csv").write_text("\n".join(lines))
    print(import_price_bars(env.conn, str(out / "SYNTHETIC_bars.csv"), "user_csv_1m", T0))
    print(json.dumps(resolve_predictions(env.conn, T0 + timedelta(hours=2)), indent=1))
    summary = evaluate(env.conn, env.cfg, T0 + timedelta(hours=2))
    (out / "SYNTHETIC_evaluation.md").write_text(render_evaluation_markdown(summary))
    print("journal verification:", verify_journal(env.conn) or "OK")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "demo_output")
