"""Gera saída CLI simulada (no formato real do FOS) para testar o portal sem switches.

O texto gerado passa pelos mesmos parsers da coleta real.
"""
from __future__ import annotations

import random
import re
import time
import zlib


def mock_inventory() -> list[dict]:
    inv = []
    for site, fab in (("DC1", "A"), ("DC1", "B"), ("DC2", "A"), ("DC2", "B")):
        for n in range(1, 4):
            inv.append({"host": f"10.{1 if site == 'DC1' else 2}.{ord(fab)}.{n}",
                        "name": f"{site}-FAB{fab}-SW{n:02d}", "site": site, "_fab": fab,
                        "_kind": "director" if n == 1 else "fixed",
                        "_vf": n == 2})
    inv.append({"host": "10.9.9.9", "name": "DC2-LEGACY-SW", "site": "DC2", "_down": True})
    return inv


class MockRunner:
    def __init__(self, sw: dict):
        if sw.get("_down"):
            raise TimeoutError("timed out")  # simula switch inacessível
        self.sw = sw
        self.fids = [128, 10, 20] if sw.get("_vf") else []
        self.director = sw.get("_kind") == "director"
        # estado estável por switch + variação por coleta
        self.seed = zlib.crc32(sw["host"].encode())
        self.tick = int(time.time()) % 10**6  # cresce entre coletas (contadores cumulativos)

    def run(self, cmd: str) -> str:
        fid = None
        m = re.match(r'fosexec --fid (\d+) -cmd "(.+)"', cmd)
        if m:
            fid, cmd = int(m.group(1)), m.group(2)
        if cmd.startswith("lscfg"):
            if not self.fids:
                return "Virtual Fabric is not enabled\n"
            return "Created switches:  128(ds)  " + "  ".join(map(str, self.fids[1:])) + "\n"
        ports = self._ports(fid)
        if cmd == "switchshow":
            return self._switchshow(fid, ports)
        if cmd.startswith("sfpshow"):
            return self._sfpshow(ports)
        if cmd == "porterrshow":
            return self._porterrshow(ports)
        return ""

    # ------------------------------------------------------------------ #
    def _ports(self, fid):
        rnd = random.Random(self.seed + (fid or 0))
        if self.director:
            layout = [(s, p) for s in (1, 2, 3, 4) for p in range(48)]
        else:
            layout = [(0, p) for p in range(64)]
        if fid is not None:  # divide portas entre os FIDs
            k = self.fids.index(fid)
            layout = [x for i, x in enumerate(layout) if i % len(self.fids) == k]
        ports = []
        for i, (slot, port) in enumerate(layout):
            idx = (slot - 1) * 48 + port if self.director else port
            r = rnd.random()
            if r < 0.25:
                st = "No_Module"
            elif r < 0.33:
                st = "No_Light"
            elif r < 0.345:
                st = "No_Sync"
            else:
                st = "Online"
            p = {"idx": idx, "slot": slot, "port": port, "state": st,
                 "disabled": rnd.random() < 0.03 and st != "Online",
                 "isl": st == "Online" and i < 4,
                 "rx": rnd.gauss(-3.0, 1.2), "tx": rnd.gauss(-2.5, 0.5)}
            if st == "Online" and rnd.random() < 0.05:
                p["rx"] = rnd.uniform(-12.5, -7.5)       # RX baixo
            if st == "Online" and rnd.random() < 0.02:
                p["tx"] = rnd.uniform(-9.5, -5.5)        # TX baixo
            if st != "Online":
                p["rx"] = -40.0
            p["crc_base"] = rnd.choice([0] * 8 + [3, 50])
            p["err_rate"] = rnd.choice([0] * 30 + [1, 5, 200])
            ports.append(p)
        return ports

    def _switchshow(self, fid, ports):
        dom = self.seed % 200 + 1
        fab = self.sw.get("_fab", "X")
        name = self.sw["name"] + (f"_FID{fid}" if fid and fid != 128 else "")
        lines = [
            f"switchName:\t{name}", "switchType:\t165.0" if self.director else "switchType:\t162.0",
            "switchState:\tOnline", "switchMode:\tNative", "switchRole:\tPrincipal",
            f"switchDomain:\t{dom}", f"switchId:\tfffc{dom:02x}",
            f"switchWwn:\t10:00:c4:f5:7c:{dom:02x}:{(fid or 0):02x}:00",
            "zoning:\t\tON (cfg_prod)", "switchBeacon:\tOFF", "FC Router:\tOFF",
            f"Fabric Name:\tFAB_{fab}" + (f"_VF{fid}" if fid and fid != 128 else ""),
        ]
        if fid:
            lines.append(f"LS Attributes:\t[FID: {fid}, Base Switch: No, "
                         f"Default Switch: {'Yes' if fid == 128 else 'No'}, Ficon Switch: No, Address Mode 0]")
        lines.append("")
        if self.director:
            lines += ["Index Slot Port Address Media  Speed  State       Proto", "=" * 60]
        else:
            lines += ["Index Port Address  Media Speed   State       Proto", "=" * 55]
        for p in ports:
            media = "--" if p["state"] == "No_Module" else "id"
            addr = f"{dom:02x}{p['idx'] & 0xff:02x}00"
            tail = ""
            if p["state"] == "Online":
                if p["isl"]:
                    tail = f"E-Port  10:00:c4:f5:7c:aa:bb:{p['idx'] & 0xff:02x} \"peer_sw\" (upstream)"
                else:
                    tail = f"F-Port  10:00:00:10:9b:{dom:02x}:{p['slot']:02x}:{p['port']:02x}"
            elif p["disabled"]:
                tail = "Disabled (Persistent)"
            pre = f"{p['idx']:5d} {p['slot']:4d} {p['port']:4d}" if self.director \
                else f"{p['idx']:5d} {p['port']:4d}"
            lines.append(f"{pre}   {addr}   {media}    N32   {p['state']:<11s} FC  {tail}")
        return "\n".join(lines) + "\n"

    def _sfpshow(self, ports):
        out = []
        jitter = random.Random(self.tick)
        for p in ports:
            hdr = f"Slot {p['slot']:2d}/Port {p['port']:2d}:" if self.director else f"Port {p['port']:2d}:"
            out += ["=" * 13, hdr, "=" * 13]
            if p["state"] == "No_Module":
                out.append("SFP not present\n")
                continue
            rx = p["rx"] + (jitter.gauss(0, 0.1) if p["rx"] > -40 else 0)
            tx = p["tx"] + jitter.gauss(0, 0.05)
            rx_uw = 0.0 if rx <= -40 else 1000 * 10 ** (rx / 10)
            out += [
                "Identifier:  3    SFP", "Connector:   7    LC",
                "Transceiver: 7004404000000000 8,16,32_Gbps M5,M5E sw Short_dist",
                "Vendor Name: BROCADE", "Vendor PN:   57-1000485-01",
                f"Serial No:   ZTA1{self.seed % 10000:04d}{p['idx']:04d}",
                "Wavelength:  850  (units nm)",
                f"Temperature: {jitter.randint(30, 48)}       Centigrade",
                "Current:     7.414    mAmps", "Voltage:     3325.4   mVolts",
                (f"RX Power:    -inf     dBm (0.0 uW)" if rx_uw == 0
                 else f"RX Power:    {rx:.1f}     dBm ({rx_uw:.1f}uW)"),
                f"TX Power:    {tx:.1f}     dBm ({1000 * 10 ** (tx / 10):.1f} uW)", "",
            ]
        return "\n".join(out)

    def _porterrshow(self, ports):
        lines = [
            "          frames      enc    crc    crc    too    too    bad    enc   disc   link   loss   loss   frjt   fbsy  c3timeout    pcs    uncor",
            "       tx     rx      in    err    g_eof  shrt   long   eof     out   c3    fail    sync   sig                  tx    rx     err    err",
        ]
        t = self.tick
        for p in ports:
            crc = p["crc_base"] + p["err_rate"] * t // 10
            enc_out = p["err_rate"] * t // 20
            fr = "0" if p["state"] != "Online" else f"{(p['idx'] * 37 + t) % 900 + 1}.{t % 10}m"
            vals = [fr, fr, 0, crc, crc, 0, 0, 0, enc_out, 0, 1 if p["err_rate"] else 0,
                    2 if p["err_rate"] else 0, 1, 0, 0, 0, 0, 0, 0]
            lines.append(f"{p['idx']:4d}: " + " ".join(f"{v!s:>6}" for v in vals))
        return "\n".join(lines) + "\n"
