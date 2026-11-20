"""Portal de monitoramento de portas Brocade SAN.

    streamlit run app.py
"""
import streamlit as st

st.set_page_config(page_title="SAN Port Monitor", page_icon="🛰️", layout="wide")

pg = st.navigation([
    st.Page("views/overview.py", title="Visão geral", icon="📊", default=True),
    st.Page("views/problems.py", title="Portas com problema", icon="🚨"),
    st.Page("views/switch.py", title="Switch / Fabric", icon="🔌"),
    st.Page("views/history.py", title="Histórico de porta", icon="📈"),
])
pg.run()
