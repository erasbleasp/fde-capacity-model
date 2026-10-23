"""Dashboard smoke test: every page renders without an exception, in Base and in another scenario."""
from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

APP = str(Path(__file__).resolve().parent.parent / "app" / "streamlit_app.py")
PAGES = {"views/scorecard.py": "Where capacity comes from", "views/supply.py": "Where FDE time goes",
         "views/outcomes.py": "The reuse flywheel"}


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
