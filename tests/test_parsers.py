from pathlib import Path

from sanmon.collector import collect_switch
from sanmon.health import evaluate_port
from sanmon.config import DEFAULT_THRESHOLDS
from sanmon.mock import MockRunner, mock_inventory
from sanmon.parsers import (parse_count, parse_lscfg_fids, parse_porterrshow,
                            parse_sfpshow, parse_switchshow)

FX = Path(__file__).parent / "fixtures"


def read(n):
    return (FX / n).read_text()


def test_parse_count():
    assert parse_count("0") == 0
    assert parse_count("7.0k") == 7000
    assert parse_count("1.2g") == 1_200_000_000


def test_switchshow_fixed():
    meta, ports = parse_switchshow(read("switchshow_fixed.txt"))
    assert meta["switch_name"] == "SANSW01"
    assert meta["fid"] == 128 and meta["domain"] == 1
    assert meta["fabric_name"] == "FAB_A"
    assert meta["wwn"] == "10:00:c4:f5:7c:12:34:56"
    assert len(ports) == 6
    assert ports[0]["state"] == "Online" and ports[0]["port_type"] == "F-Port"
    assert ports[0]["remote_wwn"] == "10:00:00:10:9b:aa:bb:cc"
    assert ports[1]["port_type"] == "E-Port"
    assert ports[3]["state"] == "No_Module"
    assert ports[4]["disabled"] == 1
    assert ports[5]["port_type"] == "F-Port" and "NPIV" in ports[5]["info"]


def test_switchshow_director():
    meta, ports = parse_switchshow(read("switchshow_director.txt"))
    assert meta["fid"] is None
    assert [(p["idx"], p["slot"], p["port"]) for p in ports] == [(0, 1, 0), (48, 2, 0)]
    assert ports[1]["state"] == "No_Sync"


def test_sfpshow():
    s = parse_sfpshow(read("sfpshow.txt"))
    assert s[(0, 0)]["rx_dbm"] == -2.9 and s[(0, 0)]["tx_dbm"] == -2.4
    assert s[(0, 0)]["sfp_serial"] == "UAF1112300000AB" and s[(0, 0)]["temp_c"] == 35
    assert s[(0, 1)]["rx_dbm"] == -11.2
    assert s[(0, 1)]["rx_low_warn_dbm"] == -12.0  # 63.1 uW
    assert s[(0, 2)]["rx_dbm"] == -40.0
    assert abs(s[(0, 2)]["tx_dbm"] - (-3.0)) < 0.01
    assert (0, 3) not in s


def test_porterrshow():
    e = parse_porterrshow(read("porterrshow.txt"))
    assert e[0]["frames_tx"] == 665000
    assert e[1]["crc_err"] == 12 and e[1]["enc_out"] == 1500 and e[1]["c3timeout_tx"] == 2
    assert e[2]["loss_sig"] == 1


def test_lscfg():
    assert parse_lscfg_fids("Created switches:  128(ds)  10  20\nPort 0 1 2") == [128, 10, 20]
    assert parse_lscfg_fids("Virtual Fabric is not enabled") == []


def test_health():
    th = DEFAULT_THRESHOLDS
    assert evaluate_port({"state": "No_Module"}, th)[1] == "Sem SFP"
    assert evaluate_port({"state": "No_Light"}, th)[0] == 2
    assert evaluate_port({"state": "No_Light"}, {**th, "ignore_no_light": True})[0] == 0
    sev, cat, *_ = evaluate_port({"state": "Online", "rx_dbm": -8.0, "tx_dbm": -2}, th)
    assert (sev, cat) == (1, "RX/TX baixo")
    sev, cat, *_ = evaluate_port({"state": "Online", "rx_dbm": -3, "tx_dbm": -2, "d_crc_err": 500}, th)
    assert (sev, cat) == (2, "Erros")


def test_collect_mock_vf():
    sw = next(s for s in mock_inventory() if s.get("_vf"))
    logicals = collect_switch(sw, MockRunner(sw))
    assert [ls.fid for ls in logicals] == [128, 10, 20]
    assert all(ls.ports for ls in logicals)
    online = [p for ls in logicals for p in ls.ports if p["state"] == "Online"]
    assert online and all(p.get("rx_dbm") is not None and "crc_err" in p for p in online)


def test_collect_mock_director():
    sw = next(s for s in mock_inventory() if s.get("_kind") == "director")
    (ls,) = collect_switch(sw, MockRunner(sw))
    assert any(p["slot"] == 4 for p in ls.ports)
    assert all("frames_tx" in p for p in ls.ports)
