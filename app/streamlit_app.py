"""FDE Capacity & Outcomes dashboard.

    .venv/bin/streamlit run app/streamlit_app.py

The filter row (scenario + three levers) sits above every page and scopes everything below it.
"""
import streamlit as st

import data
import ui

st.set_page_config(page_title="FDE Capacity & Outcomes", page_icon="📈", layout="wide")
ui.inject_css()

pages = [
    st.Page("views/scorecard.py", title="Scorecard", default=True),
    st.Page("views/supply.py", title="Supply"),
    st.Page("views/outcomes.py", title="Outcomes"),
    st.Page("views/confidence.py", title="Confidence"),
    st.Page("views/scenarios.py", title="Scenarios"),
    st.Page("views/definitions.py", title="Data & definitions"),
]
nav = st.navigation(pages, position="top")

ui.masthead("FDE planning · made-up data", "FDE capacity and outcomes",
            "History through September 2026 and a forecast to September 2028. Ranges are P10–P90 across "
            "2,000 Monte Carlo trials. The data are made up for a demo; none of it is Anthropic data.")

# ---------------------------------------------------------------- filter row (scopes every page)
names = list(data.scenarios())
cols = st.columns([1.2, 1, 1, 1, 1, 1])
scenario = cols[0].selectbox("Scenario", names, key="scenario",
                             help="; ".join(f"{n}: {s['description']}" for n, s in data.scenarios().items()))
levers = {}
for col, (path, spec) in zip(cols[1:], data.LEVERS.items()):
    default = data.lever_default(scenario, path)
    if path in data.PERCENT_LEVERS:
        v = col.slider(spec["label"], int(spec["min"] * 100), int(spec["max"] * 100), int(round(default * 100)),
                       step=int(round(spec["step"] * 100)), format="%d%%", key=f"{path}|{scenario}",
                       help=data.LEVER_HELP.get(path))
        levers[path] = v / 100
    else:
        levers[path] = col.slider(spec["label"], spec["min"], spec["max"], default, step=spec["step"],
                                  format=spec["fmt"], key=f"{path}|{scenario}")

overrides = {**data.scenarios()[scenario]["overrides"], **levers}
st.session_state["overrides"] = tuple(sorted(overrides.items()))

nav.run()
