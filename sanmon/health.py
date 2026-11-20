"""Classificação de saúde das portas (independente do Streamlit — reaproveitável em alertas)."""
from __future__ import annotations

import math

import pandas as pd

SEV_LABEL = {0: "🟢 OK", 1: "🟡 Atenção", 2: "🔴 Crítico"}


def _nn(v):
    return v is not None and not (isinstance(v, float) and math.isnan(v))


def evaluate_port(r: dict, th: dict) -> tuple[int, str, list[str], bool, bool, bool]:
    """-> (severidade, categoria, problemas, is_offline, is_low_power, has_errors)"""
    if r.get("disabled"):
        return 0, "Desabilitada", [], False, False, False
    state = r.get("state")
    if state == "No_Module":
        return 0, "Sem SFP", [], False, False, False

    issues, sev = [], 0
    offline = low = errs = False

    if state != "Online":
        if state == "No_Light" and th["ignore_no_light"]:
            return 0, "Livre (No_Light)", [], False, False, False
        offline, sev = True, 2
        issues.append(f"Offline ({state})")
    else:
        for kind in ("rx", "tx"):
            v = r.get(f"{kind}_dbm")
            if not _nn(v):
                continue
            crit = th[f"{kind}_crit_dbm"]
            warn = th[f"{kind}_warn_dbm"]
            sfp_warn = r.get(f"{kind}_low_warn_dbm")
            if th["use_sfp_thresholds"] and _nn(sfp_warn):
                warn = sfp_warn
            if v <= crit:
                low, sev = True, 2
                issues.append(f"{kind.upper()} {v:.1f} dBm ≤ {crit}")
            elif v <= warn:
                low, sev = True, max(sev, 1)
                issues.append(f"{kind.upper()} {v:.1f} dBm ≤ {warn:.1f}")

    # Erros: somente o DELTA desde a coleta anterior (porterrshow é cumulativo)
    found = []
    for c in th["error_counters"]:
        d = r.get(f"d_{c}")
        if _nn(d) and d > 0:
            found.append((c, int(d)))
    if found:
        errs = True
        total = sum(d for _, d in found)
        sev = max(sev, 2 if total >= th["error_crit_delta"] else 1)
        issues.append("Erros: " + ", ".join(f"{c}+{d}" for c, d in found))

    cat = "Offline" if offline else "RX/TX baixo" if low else "Erros" if errs else "OK"
    return sev, cat, issues, offline, low, errs


def classify(df: pd.DataFrame, th: dict) -> pd.DataFrame:
    if df.empty:
        for c in ("severity", "category", "issues", "is_offline", "is_low_power", "has_errors"):
            df[c] = []
        return df
    res = [evaluate_port(r, th) for r in df.to_dict("records")]
    df = df.copy()
    df["severity"] = [x[0] for x in res]
    df["category"] = [x[1] for x in res]
    df["issues"] = ["; ".join(x[2]) for x in res]
    df["is_offline"] = [x[3] for x in res]
    df["is_low_power"] = [x[4] for x in res]
    df["has_errors"] = [x[5] for x in res]
    df["status"] = df["severity"].map(SEV_LABEL)
    return df
