import streamlit as st

from views.common import apply_filters, load_ports, no_data, port_table, sidebar_filters

f = sidebar_filters()
ports = apply_filters(load_ports(f["ignore_no_light"]), f)
if ports.empty:
    no_data()

st.title("Portas com problema — todos os switches")

q = st.text_input("Buscar (switch, WWN, porta, serial…)", placeholder="ex.: 10:00:00:10:9b ou SW01")
if q:
    mask = ports.astype(str).apply(lambda col: col.str.contains(q, case=False, regex=False)).any(axis=1)
    ports = ports[mask]

off = ports[ports["is_offline"]]
low = ports[ports["is_low_power"]].sort_values("rx_dbm")
err = ports[ports["has_errors"]].sort_values("severity", ascending=False)
crit = ports[ports["severity"] == 2]

t_all, t_off, t_low, t_err = st.tabs([
    f"🔴 Críticas ({len(crit)})", f"⛔ Offline ({len(off)})",
    f"📉 RX/TX baixo ({len(low)})", f"⚠️ Erros ({len(err)})",
])
order = ["display_name", "fid_label", "idx"]
with t_all:
    port_table(crit.sort_values(order))
with t_off:
    st.caption("Portas com SFP e não Online (No_Light, No_Sync, Laser_Flt, Mod_Inv…). "
               "Portas desabilitadas e sem SFP não entram aqui.")
    port_table(off.sort_values(order), hide=("rx_dbm", "tx_dbm", "d_crc_err", "d_enc_out"))
with t_low:
    port_table(low)
with t_err:
    st.caption("Considera apenas o incremento desde a coleta anterior (porterrshow é cumulativo).")
    port_table(err)
