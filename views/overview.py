import pandas as pd
import streamlit as st

from views.common import apply_filters, load_ports, load_switches, no_data, sidebar_filters

f = sidebar_filters()
sw = apply_filters(load_switches(), f)
ports = apply_filters(load_ports(f["ignore_no_light"]), f)
if sw.empty:
    no_data()

st.title("Visão geral da SAN")

# ---------------- KPIs ----------------
n_fail = int((sw["coleta"] != "🟢 OK").sum())
n_phys = sw["host"].nunique()
c = st.columns(6)
c[0].metric("Switches físicos", n_phys, help="Hosts no inventário")
c[1].metric("Switches lógicos", len(sw), help="Conta cada FID de Virtual Fabric separadamente")
c[2].metric("Coleta com problema", n_fail, delta=None if not n_fail else "verificar",
            delta_color="inverse")
if not ports.empty:
    online = int((ports["state"] == "Online").sum())
    c[3].metric("Portas online", f"{online} / {len(ports)}")
    c[4].metric("Offline (com SFP)", int(ports["is_offline"].sum()))
    c[5].metric("RX/TX baixo · Erros",
                f"{int(ports['is_low_power'].sum())} · {int(ports['has_errors'].sum())}")


def summarize(df: pd.DataFrame, by: list[str]) -> pd.DataFrame:
    return df.groupby(by, dropna=False).agg(
        portas=("idx", "size"),
        online=("state", lambda s: int((s == "Online").sum())),
        offline=("is_offline", "sum"),
        rx_tx_baixo=("is_low_power", "sum"),
        erros=("has_errors", "sum"),
        criticas=("severity", lambda s: int((s == 2).sum())),
    ).reset_index()


# ---------------- Por fabric ----------------
st.subheader("Por fabric")
if not ports.empty:
    fab = summarize(ports, ["fabric_name"])
    fab = fab.merge(sw.groupby("fabric_name").agg(switches=("host", "size")).reset_index(),
                    on="fabric_name", how="right").fillna(0)
    fab["saude"] = fab.apply(lambda r: "🔴" if r.criticas else "🟡" if r.rx_tx_baixo + r.erros else "🟢", axis=1)
    st.dataframe(
        fab[["saude", "fabric_name", "switches", "portas", "online", "offline", "rx_tx_baixo", "erros"]],
        hide_index=True, width="stretch",
        column_config={"saude": st.column_config.TextColumn("", width="small"),
                       "fabric_name": "Fabric", "rx_tx_baixo": "RX/TX baixo"},
    )

# ---------------- Por switch ----------------
st.subheader("Por switch")
st.caption("Clique em uma linha para abrir o detalhe do switch.")
tbl = sw[["host", "fid", "display_name", "fid_label", "fabric_name", "site", "domain",
          "coleta", "last_ok", "poll_error"]]
if not ports.empty:
    tbl = tbl.merge(summarize(ports, ["host", "fid"]), on=["host", "fid"], how="left")
tbl = tbl.sort_values(["criticas", "erros", "display_name"] if "criticas" in tbl else ["display_name"],
                      ascending=[False, False, True] if "criticas" in tbl else True)

event = st.dataframe(
    tbl.drop(columns=["fid"]), hide_index=True, width="stretch",
    on_select="rerun", selection_mode="single-row",
    column_config={
        "host": "IP", "display_name": "Switch", "fid_label": "FID", "fabric_name": "Fabric",
        "site": "Site", "domain": "Domain", "coleta": "Coleta", "last_ok": "Último sucesso",
        "poll_error": st.column_config.TextColumn("Erro de coleta", width="medium"),
        "online": st.column_config.ProgressColumn(
            "Online", format="%d", min_value=0, max_value=int(tbl.get("portas", pd.Series([1])).max() or 1)),
        "rx_tx_baixo": "RX/TX baixo", "criticas": "Críticas",
    },
)
if event.selection.rows:
    row = tbl.iloc[event.selection.rows[0]]
    st.session_state["sel_switch"] = (row["host"], int(row["fid"]))
    st.switch_page("views/switch.py")
