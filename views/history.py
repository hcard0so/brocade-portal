from datetime import datetime, timedelta

import altair as alt
import pandas as pd
import streamlit as st

from views.common import config, load_history, load_ports, load_switches, no_data, sidebar_filters

f = sidebar_filters()
sw = load_switches()
ports = load_ports(f["ignore_no_light"])
if sw.empty or ports.empty:
    no_data()

st.title("Histórico de porta")

c1, c2, c3 = st.columns([3, 2, 1])
keys = list(zip(sw["host"], sw["fid"].astype(int)))
labels = {k: f"{r.display_name} · FID {r.fid_label}" for k, r in zip(keys, sw.itertuples())}
default = st.session_state.get("sel_switch")
key = c1.selectbox("Switch", keys, format_func=labels.get,
                   index=keys.index(default) if default in keys else 0)
p = ports[(ports["host"] == key[0]) & (ports["fid"] == key[1])].sort_values("idx")
if p.empty:
    st.warning("Switch sem portas coletadas.")
    st.stop()
plabels = {r.idx: f"{r.port_label} (idx {r.idx}) — {r.state} {r.status}" for r in p.itertuples()}
idx = c2.selectbox("Porta", list(plabels), format_func=plabels.get)
days = c3.selectbox("Período", [1, 7, 30], format_func=lambda d: f"{d} dia(s)", index=1)

h = load_history(key[0], key[1], int(idx), (datetime.now() - timedelta(days=days)).isoformat())
if h.empty:
    st.info("Sem histórico no período.")
    st.stop()

cur = p[p["idx"] == idx].iloc[0]
st.caption(f"Estado atual: **{cur['state']}** · {cur['port_type'] or ''} · WWN remoto: "
           f"{cur['remote_wwn'] or '—'} · SFP {cur['sfp_vendor'] or ''} {cur['sfp_serial'] or ''}"
           + (f"  \nProblemas: {cur['issues']}" if cur["issues"] else ""))

th = config()["thresholds"]

# ---- Potência óptica (mesma unidade → um único eixo) ----
st.subheader("Potência óptica (dBm)")
pw = h.melt(id_vars="ts", value_vars=["rx_dbm", "tx_dbm"], var_name="sinal", value_name="dBm")
pw["sinal"] = pw["sinal"].map({"rx_dbm": "RX", "tx_dbm": "TX"})
pw = pw[pw["dBm"] > -40]
rules = pd.DataFrame({"y": [th["rx_warn_dbm"], th["rx_crit_dbm"]],
                      "limite": [f"RX atenção ({th['rx_warn_dbm']})", f"RX crítico ({th['rx_crit_dbm']})"]})
base = alt.Chart(pw).mark_line(strokeWidth=2, point=alt.OverlayMarkDef(size=30)).encode(
    x=alt.X("ts:T", title=None),
    y=alt.Y("dBm:Q", scale=alt.Scale(zero=False)),
    color=alt.Color("sinal:N", scale=alt.Scale(domain=["RX", "TX"], range=["#2a78d6", "#7a5bd0"]),
                    legend=alt.Legend(orient="top", title=None)),
    tooltip=[alt.Tooltip("ts:T", title="Coleta"), "sinal:N", alt.Tooltip("dBm:Q", format=".1f")],
)
lines = alt.Chart(rules).mark_rule(strokeDash=[4, 4], color="#9a9a9a").encode(
    y="y:Q", tooltip=["limite:N"])
st.altair_chart(base + lines, width="stretch")

# ---- Erros por coleta (delta) ----
st.subheader("Incremento de erros por coleta")
err_cols = [f"d_{c}" for c in th["error_counters"] if f"d_{c}" in h]
e = h.melt(id_vars="ts", value_vars=err_cols, var_name="contador", value_name="delta").fillna(0)
e = e[e["delta"] > 0]
e["contador"] = e["contador"].str.removeprefix("d_")
if e.empty:
    st.success("Nenhum incremento de erro no período. ✅")
else:
    st.altair_chart(
        alt.Chart(e).mark_bar(cornerRadiusEnd=4).encode(
            x=alt.X("ts:T", title=None),
            y=alt.Y("sum(delta):Q", title="Δ erros"),
            color=alt.Color("contador:N", legend=alt.Legend(orient="top", title=None)),
            tooltip=[alt.Tooltip("ts:T", title="Coleta"), "contador:N", "delta:Q"],
        ),
        width="stretch",
    )

with st.expander("Dados brutos"):
    st.dataframe(h, hide_index=True, width="stretch")
