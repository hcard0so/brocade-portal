from __future__ import annotations

import os
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent

DEFAULT_THRESHOLDS = {
    "rx_warn_dbm": -7.0,
    "rx_crit_dbm": -10.0,
    "tx_warn_dbm": -5.0,
    "tx_crit_dbm": -8.0,
    "use_sfp_thresholds": True,
    "error_counters": ["crc_err", "enc_out", "link_fail", "loss_sync", "loss_sig",
                       "disc_c3", "c3timeout_tx", "pcs_err", "uncor_err"],
    "error_crit_delta": 100,
    "ignore_no_light": False,
}


def load_config(path: str | os.PathLike | None = None) -> dict:
    path = Path(path or os.environ.get("SANMON_CONFIG", ROOT / "config.yaml"))
    if not path.exists():
        path = ROOT / "config.example.yaml"
    with open(path) as f:
        cfg = yaml.safe_load(f) or {}
    cfg.setdefault("ssh", {})
    cfg.setdefault("switches", [])
    cfg.setdefault("poll_interval", 300)
    cfg.setdefault("history_days", 30)
    db = Path(cfg.get("db_path", "data/sanmon.db"))
    cfg["db_path"] = str(db if db.is_absolute() else ROOT / db)
    cfg["thresholds"] = {**DEFAULT_THRESHOLDS, **(cfg.get("thresholds") or {})}
    return cfg
