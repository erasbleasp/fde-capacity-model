"""Backtest runs end to end and scores every measure."""
import numpy as np

from analysis.backtest import CUTOFF, run_backtest


def test_backtest_scores_every_measure():
    res = run_backtest(n=200)
    s = res["summary"]
    assert len(s) == 7
    assert s.actual_percentile.between(0, 1).all()
    assert 0 <= res["coverage"] <= 1
    assert res["months"][0].date() > CUTOFF
    # the snapshot only sees data to the cutoff, so recalibrated inputs differ from the full-history ones
    assert (res["moved"].full_history != res["moved"].at_cutoff).any()
    assert np.isfinite(s[["p10", "p50", "p90"]].to_numpy()).all()
