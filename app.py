"""SpeckleBem GUI - start with:  streamlit run app.py"""

import sys
from pathlib import Path

import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parent))

st.set_page_config(page_title="SpeckleBem", page_icon="🔬", layout="wide")

pages = [
    st.Page("sbgui/ui/pages/model.py", title="Modell", icon="🧩", default=True),
    st.Page("sbgui/ui/pages/run.py", title="Berechnung", icon="▶️"),
    st.Page("sbgui/ui/pages/results.py", title="Ergebnisse", icon="📈"),
]
st.navigation(pages).run()
