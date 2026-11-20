import streamlit as st

from views.common import apply_filters, load_ports, load_switches, no_data, port_table, sidebar_filters

f = sidebar_filters()
sw = apply_filters(load_switches(), f)
if sw.empty:
    no_data()

st.title("Switch / Fabric")

mode = st.segmented_control("Visualizar por", ["Switch", "Fabric"], default="Switch")

ports_all = load_ports(f["ignore_no_light"])

if mode == "Fabric":
    fab = st.selectbox("Fabric", list(dict.fromkeys(sw["fabric_name"])))
    sel = sw[sw["fabric_name"] == fab]
    ports = ports_all.merge(sel[["host", "fid"]], on=["host", "fid"]) if not ports_all.empty else ports_all
    st.caption(f"{len(sel)} switch(es) lógico(s): " + ", ".join(sel["display_name"]))
else:
    keys = list(zip(sw["host"], sw["fid"].astype(int)))
    labels = {k: f"{r.display_name}  ·  {r.host}  ·  FID {r.fid_label}  ·  {r.fabric_name}"
              for k, r in zip(keys, sw.itertuples())}
    default = st.session_state.get("sel_switch")
    key = st.selectbox("Switch", keys, format_func=labels.get,
                       index=keys.index(default) if default in keys else 0)
    st.session_state["sel_switch"] = key
    row = sw[(sw["host"] == key[0]) & (sw["fid"] == key[1])].iloc[0]
    ports = ports_all[(ports_all["host"] == key[0]) & (ports_all["fid"] == key[1])] \
        if not ports_all.empty else ports_all

    c = st.columns(5)
    c[0].metric("Coleta", row["coleta"])
    c[1].metric("Domain", "—" if row["domain"] is None else int(row["domain"]))
    c[2].metric("Role", row["switch_role"] or "—")
    c[3].metric("Estado", row["switch_state"] or "—")
    c[4].metric("WWN", row["wwn"] or "—")
    if row["poll_error"]:
        st.error(f"Última coleta falhou ({row['last_poll']}): {row['poll_error']}. "
                 f"Dados abaixo são da última coleta com sucesso ({row['last_ok'] or 'nunca'}).")
    # outros FIDs do mesmo chassi
    siblings = sw[(sw["host"] == key[0]) & (sw["fid"] != key[1])]
    if len(siblings):
        st.caption("Outros FIDs neste chassi: " +
                   ", ".join(f"{r.display_name} (FID {r.fid_label})" for r in siblings.itertuples()))

if ports.empty:
    st.warning("Sem portas coletadas.")
    st.stop()

c = st.columns(5)
c[0].metric("Portas", len(ports))
c[1].metric("Online", int((ports["state"] == "Online").sum()))
c[2].metric("Offline (c/ SFP)", int(ports["is_offline"].sum()))
c[3].metric("RX/TX baixo", int(ports["is_low_power"].sum()))
c[4].metric("Com erros", int(ports["has_errors"].sum()))

flt = st.pills("Mostrar", ["Todas", "Problemas", "Offline", "RX/TX baixo", "Erros", "Online", "Sem SFP"],
               default="Problemas")
view = {
    "Problemas": ports[ports["severity"] > 0],
    "Offline": ports[ports["is_offline"]],
    "RX/TX baixo": ports[ports["is_low_power"]],
    "Erros": ports[ports["has_errors"]],
    "Online": ports[ports["state"] == "Online"],
    "Sem SFP": ports[ports["state"] == "No_Module"],
}.get(flt, ports)

hide = () if mode == "Fabric" else ("display_name", "fid_label", "fabric_name")
port_table(view.sort_values(["display_name", "fid", "idx"]), hide=hide, height=600)
