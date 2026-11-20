"""Parsers para a saída CLI do Brocade FOS (switchshow, sfpshow -all, porterrshow, lscfg).

Os parsers são tolerantes: ignoram linhas que não reconhecem, para funcionar
com variações entre versões de FOS (7.x, 8.x, 9.x), switches fixos e directors
(com coluna Slot) e com a saída do `fosexec` em ambientes com Virtual Fabric.
"""
from __future__ import annotations

import math
import re

# Colunas do porterrshow (FOS 8.x/9.x). Versões antigas têm menos colunas no
# final (sem pcs_err / uncor_err) — o mapeamento é posicional e trunca.
ERR_COLS = [
    "frames_tx", "frames_rx", "enc_in", "crc_err", "crc_g_eof", "too_shrt",
    "too_long", "bad_eof", "enc_out", "disc_c3", "link_fail", "loss_sync",
    "loss_sig", "frjt", "fbsy", "c3timeout_tx", "c3timeout_rx", "pcs_err",
    "uncor_err",
]

_MULT = {"": 1, "k": 1e3, "m": 1e6, "g": 1e9, "t": 1e12}


def parse_count(tok: str) -> int | None:
    """'0' -> 0, '7.0k' -> 7000, '1.2m' -> 1200000."""
    m = re.fullmatch(r"([\d.]+)([kmgt]?)", tok.strip().lower())
    if not m:
        return None
    return int(round(float(m.group(1)) * _MULT[m.group(2)]))


def uw_to_dbm(uw: float) -> float:
    return -40.0 if uw <= 0 else round(10 * math.log10(uw / 1000.0), 2)


# --------------------------------------------------------------------------- #
# switchshow
# --------------------------------------------------------------------------- #
_KV = re.compile(r"^([A-Za-z][A-Za-z0-9 _/-]*?):\s*(.*?)\s*$")
_WWN = re.compile(r"\b([0-9a-f]{2}(?::[0-9a-f]{2}){7})\b", re.I)
_PTYPE = re.compile(r"\b((?:EX|VEX|VE|LB|[EFNGLUD])-Port)\b")
_PORT_HDR = re.compile(r"^Index\s+(Slot\s+)?Port\s+")


def parse_switchshow(text: str) -> tuple[dict, list[dict]]:
    info: dict[str, str] = {}
    ports: list[dict] = []
    lines = text.splitlines()

    hdr_i = None
    for i, line in enumerate(lines):
        s = line.strip()
        if _PORT_HDR.match(s):
            hdr_i = i
            break
        m = _KV.match(s)
        if m:
            info.setdefault(m.group(1).strip(), m.group(2))

    meta = {
        "switch_name": info.get("switchName"),
        "switch_state": info.get("switchState"),
        "switch_role": info.get("switchRole"),
        "switch_type": info.get("switchType"),
        "domain": _int(info.get("switchDomain")),
        "wwn": info.get("switchWwn"),
        "fabric_name": info.get("Fabric Name") or None,
        "fid": None,
    }
    m = re.search(r"FID:\s*(\d+)", info.get("LS Attributes", ""))
    if m:
        meta["fid"] = int(m.group(1))

    if hdr_i is None:
        return meta, ports

    header = lines[hdr_i].split()
    has_slot = "Slot" in header
    has_addr = "Address" in header
    cols = ["idx"] + (["slot"] if has_slot else []) + ["port"] + \
           (["address"] if has_addr else []) + ["media", "speed", "state", "proto"]

    for line in lines[hdr_i + 1:]:
        s = line.strip()
        if not s or not s[0].isdigit():
            continue
        parts = s.split(None, len(cols))
        if len(parts) < len(cols) - 1:  # proto pode faltar em alguns casos
            continue
        p = dict(zip(cols, parts))
        rest = parts[len(cols)] if len(parts) > len(cols) else ""
        p["idx"] = int(p["idx"])
        p["slot"] = int(p.get("slot", 0))
        p["port"] = int(p["port"])
        p.setdefault("address", None)
        p.setdefault("proto", None)
        p["info"] = rest.strip()
        mt = _PTYPE.search(rest)
        p["port_type"] = mt.group(1) if mt else None
        mw = _WWN.search(rest)
        p["remote_wwn"] = mw.group(1).lower() if mw else None
        p["disabled"] = int("Disabled" in rest)
        ports.append(p)
    return meta, ports


# --------------------------------------------------------------------------- #
# sfpshow -all
# --------------------------------------------------------------------------- #
_SFP_HDR = re.compile(r"^\s*(?:Slot\s+(\d+)/)?Port\s+(\d+):\s*$", re.M)


def _power(body: str, label: str) -> tuple[float | None, float | None]:
    """Retorna (valor_dBm, limite_warn_low_dBm_do_SFP)."""
    m = re.search(rf"^{label}:\s*(.*)$", body, re.M)
    if not m:
        return None, None
    rest = m.group(1)
    md = re.match(r"\s*(-?[\d.]+|-inf)\s*dBm\s*\(\s*([\d.]+)\s*uW\s*\)(.*)", rest)
    if md:
        dbm = -40.0 if md.group(1) == "-inf" else float(md.group(1))
        # Com `sfpshow -f`/alguns FOS: alarm_low alarm_high warn_low warn_high (uW)
        thr = re.findall(r"([\d.]+)\s*uW", md.group(3))
        warn_low = uw_to_dbm(float(thr[2])) if len(thr) >= 3 else None
        return dbm, warn_low
    mu = re.match(r"\s*([\d.]+)\s*uW", rest)  # FOS antigo: "501.2 uWatts"
    if mu:
        return uw_to_dbm(float(mu.group(1))), None
    return None, None


def _field(body: str, label: str) -> str | None:
    m = re.search(rf"^{label}:\s*(.*?)\s*$", body, re.M)
    return m.group(1) if m else None


def parse_sfpshow(text: str) -> dict[tuple[int, int], dict]:
    """Chave (slot, port) — slot=0 em switches fixos."""
    out: dict[tuple[int, int], dict] = {}
    heads = list(_SFP_HDR.finditer(text))
    for i, m in enumerate(heads):
        end = heads[i + 1].start() if i + 1 < len(heads) else len(text)
        body = text[m.end():end]
        slot = int(m.group(1)) if m.group(1) else 0
        port = int(m.group(2))
        if "Identifier" not in body and "RX Power" not in body:
            continue  # sem SFP
        rx, rx_wl = _power(body, "RX Power")
        tx, tx_wl = _power(body, "TX Power")
        temp = _field(body, "Temperature")
        wl = _field(body, "Wavelength")
        out[(slot, port)] = {
            "rx_dbm": rx,
            "tx_dbm": tx,
            "rx_low_warn_dbm": rx_wl,
            "tx_low_warn_dbm": tx_wl,
            "temp_c": _float(temp.split()[0]) if temp else None,
            "sfp_vendor": _field(body, "Vendor Name"),
            "sfp_pn": _field(body, "Vendor PN"),
            "sfp_serial": _field(body, "Serial No"),
            "wavelength": _int(wl.split()[0]) if wl else None,
        }
    return out


# --------------------------------------------------------------------------- #
# porterrshow
# --------------------------------------------------------------------------- #
_ERR_LINE = re.compile(r"^\s*(\d+):\s+(.+)$", re.M)


def parse_porterrshow(text: str) -> dict[int, dict]:
    """Chave = índice da porta. Valores são contadores cumulativos."""
    out: dict[int, dict] = {}
    for m in _ERR_LINE.finditer(text):
        vals = [parse_count(t) for t in m.group(2).split()]
        if not vals or any(v is None for v in vals):
            continue
        out[int(m.group(1))] = dict(zip(ERR_COLS, vals))
    return out


# --------------------------------------------------------------------------- #
# lscfg --show  (Virtual Fabric)
# --------------------------------------------------------------------------- #
def parse_lscfg_fids(text: str) -> list[int]:
    """'Created switches:  128(ds)  10  20' -> [128, 10, 20]. [] se VF desabilitado."""
    m = re.search(r"Created switches:\s*(.*)", text)
    if not m:
        return []
    return [int(x) for x in re.findall(r"\b(\d+)(?:\([a-z]+\))?", m.group(1))]


def _int(v):
    try:
        return int(v)
    except (TypeError, ValueError):
        return None


def _float(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None
