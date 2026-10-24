"""Dashboard smoke test: every page renders without an exception, in Base and in another scenario."""
from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

APP = str(Path(__file__).resolve().parent.parent / "app" / "streamlit_app.py")
PAGES = {"views/scorecard.py": "Where capacity comes from", "views/supply.py": "Where FDE time goes",
         "views/outcomes.py": "The reuse flywheel",
         "views/confidence.py": "Engagement planner", "views/scenarios.py": "What each scenario buys",
         "views/definitions.py": "Everything on this dashboard traces back"}


@pytest.mark.parametrize("page,heading", PAGES.items())
def test_page_renders(page, heading):
    at = AppTest.from_file(APP, default_timeout=60)
    at.run()
    at.switch_page(page).run()
    assert not at.exception, at.exception
    assert any(heading in m.value for m in at.markdown), f"{page} did not render its last section"


def test_scenario_change_updates_levers():
    at = AppTest.from_file(APP, default_timeout=60)
    at.run()
    at.selectbox(key="scenario").set_value("Hire-heavy").run()
    assert not at.exception, at.exception
    assert at.slider(key="supply.hires_per_month|Hire-heavy").value == pytest.approx(4.6)


def test_excel_export_has_every_sheet():
    import io
    import sys

    import pandas as pd

    sys.path.insert(0, str(Path(APP).parent))
    from export import build_workbook
    from model.engine import run_model
    from model.montecarlo import run_mc
    from model.params import load_assumptions, point_params

    tree = load_assumptions()
    point, (mc, _) = run_model(point_params(tree)), run_mc(tree, n=200)
    assumptions = pd.DataFrame({"Input": ["demand.requests_per_month"], "Value": ["13"]})
    xlsx = build_workbook({"Scenario": "Base"}, assumptions, point, mc, pd.DataFrame({"scenario": ["Base"]}),
                          pd.DataFrame({"param": ["x"], "value": [1.0]}))
    book = pd.read_excel(io.BytesIO(xlsx), sheet_name=None)
    assert set(book) == {"README", "Assumptions", "Plan (single value)", "Monte Carlo", "Scenarios", "SQL calibration"}
    assert len(book["Plan (single value)"]) == tree["horizon"]["months"]
    assert {"P10", "P50", "P90"} <= set(book["Monte Carlo"].columns)
