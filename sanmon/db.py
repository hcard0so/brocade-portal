"""Armazenamento em SQLite.

- switches       : 1 linha por switch lógico (host + FID), com status da última coleta
- ports_latest   : último estado de cada porta (usado pelas telas do portal)
- ports_history  : série temporal (RX/TX e deltas de erro) para gráficos
"""
from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta
from pathlib import Path

from .parsers import ERR_COLS

PORT_COLS = [
    ("idx", "INTEGER"), ("slot", "INTEGER"), ("port", "INTEGER"),
    ("address", "TEXT"), ("media", "TEXT"), ("speed", "TEXT"), ("state", "TEXT"),
    ("proto", "TEXT"), ("port_type", "TEXT"), ("remote_wwn", "TEXT"),
    ("disabled", "INTEGER"), ("info", "TEXT"),
    ("rx_dbm", "REAL"), ("tx_dbm", "REAL"),
    ("rx_low_warn_dbm", "REAL"), ("tx_low_warn_dbm", "REAL"), ("temp_c", "REAL"),
    ("sfp_vendor", "TEXT"), ("sfp_pn", "TEXT"), ("sfp_serial", "TEXT"),
    ("wavelength", "INTEGER"),
] + [(c, "INTEGER") for c in ERR_COLS] + [(f"d_{c}", "INTEGER") for c in ERR_COLS]

HIST_COLS = ["state", "rx_dbm", "tx_dbm"] + [f"d_{c}" for c in ERR_COLS]

SWITCH_COLS = ["host", "fid", "name_cfg", "site", "switch_name", "fabric_name",
               "domain", "switch_state", "switch_role", "switch_type", "wwn",
               "last_poll", "last_ok", "poll_error"]


def connect(path: str) -> sqlite3.Connection:
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path, timeout=30)
    conn.execute("PRAGMA journal_mode=WAL")  # leitor (Streamlit) não bloqueia o coletor
    init(conn)
    return conn


def init(conn: sqlite3.Connection) -> None:
    pcols = ", ".join(f"{n} {t}" for n, t in PORT_COLS)
    conn.executescript(f"""
    CREATE TABLE IF NOT EXISTS switches (
        host TEXT, fid INTEGER, name_cfg TEXT, site TEXT, switch_name TEXT,
        fabric_name TEXT, domain INTEGER, switch_state TEXT, switch_role TEXT,
        switch_type TEXT, wwn TEXT, last_poll TEXT, last_ok TEXT, poll_error TEXT,
        PRIMARY KEY (host, fid));
    CREATE TABLE IF NOT EXISTS ports_latest (
        host TEXT, fid INTEGER, ts TEXT, {pcols},
        PRIMARY KEY (host, fid, idx));
    CREATE TABLE IF NOT EXISTS ports_history (
        ts TEXT, host TEXT, fid INTEGER, idx INTEGER,
        {", ".join(f"{c} {'TEXT' if c == 'state' else 'REAL' if 'dbm' in c else 'INTEGER'}" for c in HIST_COLS)});
    CREATE INDEX IF NOT EXISTS ix_hist ON ports_history(host, fid, idx, ts);
    CREATE INDEX IF NOT EXISTS ix_hist_ts ON ports_history(ts);
    """)


def _delta(new, old):
    if new is None or old is None:
        return None
    return new - old if new >= old else new  # contador zerado (statsclear/reboot)


def save_switch_ok(conn, sw_cfg: dict, logicals: list, ts: str) -> None:
    host = sw_cfg["host"]
    fids = [ls.fid for ls in logicals]
    with conn:
        # remove FIDs que não existem mais (ou placeholder de falha anterior)
        q = ",".join("?" * len(fids))
        conn.execute(f"DELETE FROM switches WHERE host=? AND fid NOT IN ({q})", [host, *fids])
        conn.execute(f"DELETE FROM ports_latest WHERE host=? AND fid NOT IN ({q})", [host, *fids])

        for ls in logicals:
            prev = {r[0]: r[1:] for r in conn.execute(
                f"SELECT idx, {', '.join(ERR_COLS)} FROM ports_latest WHERE host=? AND fid=?",
                (host, ls.fid))}
            rows, hist = [], []
            for p in ls.ports:
                old = prev.get(p["idx"])
                for i, c in enumerate(ERR_COLS):
                    p[f"d_{c}"] = _delta(p.get(c), old[i] if old else None)
                rows.append([host, ls.fid, ts] + [p.get(n) for n, _ in PORT_COLS])
                hist.append([ts, host, ls.fid, p["idx"]] + [p.get(c) for c in HIST_COLS])

            conn.execute("DELETE FROM ports_latest WHERE host=? AND fid=?", (host, ls.fid))
            ncol = 3 + len(PORT_COLS)
            conn.executemany(f"INSERT INTO ports_latest VALUES ({','.join('?' * ncol)})", rows)
            conn.executemany(
                f"INSERT INTO ports_history VALUES ({','.join('?' * (4 + len(HIST_COLS)))})", hist)

            m = ls.meta
            conn.execute(f"""
                INSERT OR REPLACE INTO switches ({', '.join(SWITCH_COLS)})
                VALUES ({','.join('?' * len(SWITCH_COLS))})""",
                [host, ls.fid, sw_cfg.get("name"), sw_cfg.get("site"), m.get("switch_name"),
                 m.get("fabric_name") or sw_cfg.get("fabric"), m.get("domain"),
                 m.get("switch_state"), m.get("switch_role"), m.get("switch_type"),
                 m.get("wwn"), ts, ts, None])


def save_switch_fail(conn, sw_cfg: dict, error: str, ts: str) -> None:
    host = sw_cfg["host"]
    with conn:
        cur = conn.execute("UPDATE switches SET last_poll=?, poll_error=? WHERE host=?",
                           (ts, error, host))
        if cur.rowcount == 0:  # nunca coletado com sucesso: cria placeholder
            conn.execute("""INSERT INTO switches (host, fid, name_cfg, site, switch_name,
                            fabric_name, last_poll, poll_error) VALUES (?,?,?,?,?,?,?,?)""",
                         (host, 0, sw_cfg.get("name"), sw_cfg.get("site"),
                          sw_cfg.get("name") or host, sw_cfg.get("fabric"), ts, error))


def purge_history(conn, days: int) -> None:
    cutoff = (datetime.now() - timedelta(days=days)).isoformat(timespec="seconds")
    with conn:
        conn.execute("DELETE FROM ports_history WHERE ts < ?", (cutoff,))
