"""Every assumption marked `calibrated_from` must still agree with the warehouse.

If the generator or views change and a calibrated value drifts outside its stated range,
this fails, so config/assumptions.yaml can't silently go stale."""
import math
import sys
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "warehouse"))
from build import build  # noqa: E402


def calibrated(node, path=()):
    """Yield (dotted path, spec) for every dict in the YAML that has `calibrated_from`."""
    if isinstance(node, dict):
        if "calibrated_from" in node:
            yield ".".join(path), node
        for k, v in node.items():
            yield from calibrated(v, path + (str(k),))


ASSUMPTIONS = yaml.safe_load((ROOT / "config" / "assumptions.yaml").read_text())
CASES = list(calibrated(ASSUMPTIONS))


@pytest.fixture(scope="module")
def calibration(tmp_path_factory):
    con = build(tmp_path_factory.mktemp("wh") / "fde.duckdb")
    return dict(con.execute("SELECT param, value FROM v_calibration").fetchall())


def test_cases_found():
    assert len(CASES) >= 15


@pytest.mark.parametrize("path,spec", CASES, ids=[c[0] for c in CASES])
def test_calibrated_value_in_range(path, spec, calibration):
    param = spec["calibrated_from"]
    assert param in calibration, f"{path}: v_calibration has no param '{param}'"
    sql = calibration[param] * spec.get("calibration_scale", 1.0)
    dist = spec.get("dist", "fixed")
    if dist == "triangular":
        assert spec["low"] <= sql <= spec["high"], f"{path}: SQL {sql:.3f} outside [{spec['low']}, {spec['high']}]"
    elif dist == "lognormal":
        assert abs(math.log(sql / spec["median"])) <= 0.25, f"{path}: SQL {sql:.1f} vs median {spec['median']}"
    elif dist == "beta":
        assert abs(sql - spec["mean"]) <= 2.5 * spec["sd"], f"{path}: SQL {sql:.3f} vs mean {spec['mean']}"
    else:
        assert sql == pytest.approx(spec["value"], rel=0.25), f"{path}: SQL {sql:.3f} vs value {spec['value']}"
