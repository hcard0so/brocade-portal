"""Funções compartilhadas pelas páginas: leitura do banco, filtros e formatação."""
from __future__ import annotations

import os
import sqlite3
import threading

import pandas as pd
import streamlit as st

from sanmon.collector import poll_all
from sanmon.config import load_config
from sanmon.health import classify

CACHE_TTL = 60


@st.cache_resource
def config() -> dict:
    return load_config()


def _conn():
    return sqlite3.connect(f"file:{config()['db_path']}?mode=ro", uri=True, timeout=10)


@st.cache_data(ttl=CACHE_TTL, show_spinner=False)
def load_switches() -> pd.DataFrame:
    try:
        with _conn() as c:
            df = pd.read_sql("SELECT * FROM switches", c)
    except sqlite3.OperationalError:
        return pd.DataFrame()
    df = df.astype(object).where(df.notna(), None)  # NaN -> None (evita "nan" na tela)
    df["fid"] = df["fid"].astype(int)
    df["display_name"] = df["switch_name"].fillna(df["name_cfg"]).fillna(df["host"])
    df["fid_label"] = df["fid"].map(lambda f: "—" if f in (0, None) else str(int(f)))
    df["fabric_name"] = df["fabric_name"].fillna("(sem fabric)")
    df["site"] = df["site"].fillna("—")
    def coleta(r):
        if pd.notna(r["poll_error"]) and r["poll_error"]:
            return "🔴 Falha"
        return "🟢 OK"

    df["coleta"] = df.apply(coleta, axis=1)
    df["_never_ok"] = df["last_ok"].isna()
    return df.sort_values(["_never_ok", "fabric_name", "display_name", "fid"]).reset_index(drop=True)


@st.cache_data(ttl=CACHE_TTL, show_spinner=False)
def _load_ports_raw() -> pd.DataFrame:
    try:
        with _conn() as c:
            return pd.read_sql("SELECT * FROM ports_latest", c)
    except sqlite3.OperationalError:
        return pd.DataFrame()


def load_ports(ignore_no_light: bool) -> pd.DataFrame:
    df = _load_ports_raw()
    sw = load_switches()
    if df.empty or sw.empty:
        return pd.DataFrame()
    th = {**config()["thresholds"], "ignore_no_light": ignore_no_light}
    df = classify(df, th)
    df = df.merge(sw[["host", "fid", "display_name", "fid_label", "fabric_name", "site", "coleta"]],
                  on=["host", "fid"], how="left")
    df["port_label"] = df.apply(
        lambda r: f"{int(r.slot)}/{int(r.port)}" if r.slot else str(int(r.port)), axis=1)
    return df


@st.cache_data(ttl=CACHE_TTL, show_spinner=False)
def load_history(host: str, fid: int, idx: int, since: str) -> pd.DataFrame:
    with _conn() as c:
        df = pd.read_sql("SELECT * FROM ports_history WHERE host=? AND fid=? AND idx=? AND ts>=? ORDER BY ts",
                         c, params=(host, fid, idx, since))
    df["ts"] = pd.to_datetime(df["ts"])
    return df


def sidebar_filters() -> dict:
    """Filtros globais (site / fabric / No_Light). Retorna dict com seleções."""
    sw = load_switches()
    with st.sidebar:
        st.subheader("Filtros")
        sites = sorted(sw["site"].unique()) if not sw.empty else []
        fabrics = sorted(sw["fabric_name"].unique()) if not sw.empty else []
        f = {
            "sites": st.multiselect("Site", sites, key="f_sites"),
            "fabrics": st.multiselect("Fabric", fabrics, key="f_fabrics"),
            "ignore_no_light": st.toggle(
                "Ignorar No_Light (porta livre com SFP)", key="f_nolight",
                value=config()["thresholds"]["ignore_no_light"]),
        }
        st.divider()
        th = config()["thresholds"]
        st.caption(f"RX: atenção ≤ {th['rx_warn_dbm']} dBm · crítico ≤ {th['rx_crit_dbm']} dBm  \n"
                   f"TX: atenção ≤ {th['tx_warn_dbm']} dBm · crítico ≤ {th['tx_crit_dbm']} dBm  \n"
                   f"Erros: delta entre coletas · crítico ≥ {th['error_crit_delta']}")
        if st.button("📡 Coletar agora", type="primary", width="stretch"):
            run_collection()
        if msg := st.session_state.pop("collect_msg", None):
            (st.success if "0 com falha" in msg else st.warning)(msg)
        if not sw.empty:
            st.caption(f"Última coleta: {sw['last_poll'].max()}")
    return f


@st.cache_resource
def _collect_lock() -> threading.Lock:
    return threading.Lock()  # um único lock para todos os usuários do portal


def run_collection():
    """Coleta manual disparada pelo botão. Impede duas coletas simultâneas."""
    lock = _collect_lock()
    if not lock.acquire(blocking=False):
        st.warning("Já existe uma coleta em andamento — aguarde.")
        return
    try:
        n = len(config()["switches"])
        with st.spinner(f"Coletando {n} switches… (pode levar alguns minutos)"):
            ok, fail = poll_all(config(), mock=os.environ.get("MOCK") == "1")
    finally:
        lock.release()
    st.session_state["collect_msg"] = f"Coleta concluída: {ok} ok, {fail} com falha."
    st.cache_data.clear()
    st.rerun()


def apply_filters(df: pd.DataFrame, f: dict) -> pd.DataFrame:
    if df.empty:
        return df
    if f["sites"]:
        df = df[df["site"].isin(f["sites"])]
    if f["fabrics"]:
        df = df[df["fabric_name"].isin(f["fabrics"])]
    return df


def no_data():
    st.info("Nenhum dado coletado ainda. Clique em **📡 Coletar agora** na barra lateral "
            "(ou rode `./collect.sh` no terminal).")
    st.stop()


PORT_TABLE_COLS = {
    "status": "Status", "display_name": "Switch", "fid_label": "FID", "fabric_name": "Fabric",
    "idx": "Index", "port_label": "Porta", "state": "Estado", "port_type": "Tipo",
    "speed": "Speed", "rx_dbm": "RX (dBm)", "tx_dbm": "TX (dBm)", "issues": "Problemas",
    "remote_wwn": "WWN remoto", "d_crc_err": "Δ CRC", "d_enc_out": "Δ enc_out",
    "d_link_fail": "Δ link_fail", "d_loss_sync": "Δ loss_sync", "d_c3timeout_tx": "Δ c3to_tx",
    "crc_err": "CRC (total)", "sfp_serial": "SFP serial", "temp_c": "Temp °C",
}


def port_table(df: pd.DataFrame, hide: tuple = (), height: int | str = "auto"):
    cols = [c for c in PORT_TABLE_COLS if c in df.columns and c not in hide]
    view = df[cols].rename(columns=PORT_TABLE_COLS)
    st.dataframe(
        view, hide_index=True, width="stretch", height=height,
        column_config={
            "RX (dBm)": st.column_config.NumberColumn(format="%.1f"),
            "TX (dBm)": st.column_config.NumberColumn(format="%.1f"),
            "Problemas": st.column_config.TextColumn(width="large"),
        },
    )
    st.download_button("⬇️ CSV", view.to_csv(index=False).encode(), "portas.csv", "text/csv",
                       key=f"dl_{id(df)}_{len(view)}")
