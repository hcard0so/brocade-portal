"""Coletor: conecta via SSH em todos os switches (em paralelo), roda
switchshow / sfpshow -all / porterrshow (por FID quando há Virtual Fabric)
e grava no SQLite.

Uso:
    python -m sanmon.collector              # uma coleta
    python -m sanmon.collector --loop       # coleta contínua (poll_interval)
    python -m sanmon.collector --mock       # dados simulados, sem switches
"""
from __future__ import annotations

import argparse
import logging
import os
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from datetime import datetime

from . import db
from .config import load_config
from .parsers import parse_lscfg_fids, parse_porterrshow, parse_sfpshow, parse_switchshow

log = logging.getLogger("sanmon")


@dataclass
class LogicalSwitch:
    fid: int
    meta: dict
    ports: list[dict] = field(default_factory=list)


class SSHRunner:
    """Executa comandos não-interativos (exec channel) — FOS suporta `ssh sw cmd`."""

    def __init__(self, host: str, username: str, password: str | None,
                 key_file: str | None = None, timeout: int = 30, port: int = 22):
        import paramiko

        self.timeout = timeout
        self.client = paramiko.SSHClient()
        self.client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        self.client.connect(host, port=port, username=username, password=password,
                            key_filename=key_file, timeout=timeout, banner_timeout=timeout,
                            auth_timeout=timeout, look_for_keys=False, allow_agent=False)

    def run(self, cmd: str) -> str:
        _, stdout, stderr = self.client.exec_command(cmd, timeout=self.timeout * 4)
        out = stdout.read().decode(errors="replace")
        err = stderr.read().decode(errors="replace")
        return out + ("\n" + err if err.strip() else "")

    def close(self):
        self.client.close()


def collect_switch(sw: dict, runner) -> list[LogicalSwitch]:
    vf = sw.get("vf")  # None = autodetectar
    fids = parse_lscfg_fids(runner.run("lscfg --show")) if vf is not False else []
    if vf is True and not fids:
        raise RuntimeError("vf: true no inventário, mas lscfg --show não retornou FIDs")

    result = []
    for fid in fids or [None]:
        def cmd(c: str) -> str:
            return runner.run(c if fid is None else f'fosexec --fid {fid} -cmd "{c}"')

        meta, ports = parse_switchshow(cmd("switchshow"))
        if not meta.get("switch_name") and not ports:
            raise RuntimeError(f"switchshow sem saída reconhecível (FID {fid})")
        sfp = parse_sfpshow(cmd("sfpshow -all"))
        errs = parse_porterrshow(cmd("porterrshow"))
        for p in ports:
            p.update(sfp.get((p["slot"], p["port"]), {}))
            p.update(errs.get(p["idx"], {}))
        result.append(LogicalSwitch(fid=fid or meta.get("fid") or 0, meta=meta, ports=ports))
    return result


def _poll_one(sw: dict, cfg: dict, mock: bool):
    if mock:
        from .mock import MockRunner
        runner = MockRunner(sw)
    else:
        ssh = cfg["ssh"]
        runner = SSHRunner(
            sw["host"],
            username=sw.get("username") or os.environ.get(ssh.get("username_env", "SAN_USER")),
            password=sw.get("password") or os.environ.get(ssh.get("password_env", "SAN_PASS")),
            key_file=ssh.get("key_file"),
            timeout=ssh.get("timeout", 30),
        )
    try:
        return collect_switch(sw, runner)
    finally:
        if hasattr(runner, "close"):
            runner.close()


def poll_all(cfg: dict, mock: bool = False) -> tuple[int, int]:
    switches = cfg["switches"]
    if mock:
        from .mock import mock_inventory
        switches = mock_inventory()
    conn = db.connect(cfg["db_path"])
    ts = datetime.now().isoformat(timespec="seconds")
    ok = fail = 0
    workers = cfg["ssh"].get("workers", 10)
    with ThreadPoolExecutor(max_workers=workers) as ex:
        futs = {ex.submit(_poll_one, sw, cfg, mock): sw for sw in switches}
        for fut in as_completed(futs):
            sw = futs[fut]
            try:
                logicals = fut.result()
                db.save_switch_ok(conn, sw, logicals, ts)  # gravação só na thread principal
                ok += 1
                log.info("%-16s ok  (%d FID, %d portas)", sw["host"], len(logicals),
                         sum(len(ls.ports) for ls in logicals))
            except Exception as e:  # noqa: BLE001
                db.save_switch_fail(conn, sw, f"{type(e).__name__}: {e}", ts)
                fail += 1
                log.warning("%-16s FALHA: %s", sw["host"], e)
    db.purge_history(conn, cfg["history_days"])
    conn.close()
    return ok, fail


def main():
    ap = argparse.ArgumentParser(description="Coletor Brocade SAN")
    ap.add_argument("--config")
    ap.add_argument("--loop", action="store_true", help="coleta contínua")
    ap.add_argument("--mock", action="store_true", help="usa dados simulados")
    args = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    cfg = load_config(args.config)
    while True:
        t0 = time.time()
        ok, fail = poll_all(cfg, mock=args.mock)
        log.info("coleta concluída: %d ok, %d falha, %.1fs", ok, fail, time.time() - t0)
        if not args.loop:
            break
        time.sleep(max(5, cfg["poll_interval"] - (time.time() - t0)))


if __name__ == "__main__":
    main()
