# SAN Port Monitor (Brocade FOS)

Portal para monitorar portas de switches Brocade SAN: portas offline, RX/TX baixo e erros,
com visão geral (todos os switches/fabrics) e visão por switch, por FID (Virtual Fabric) e por fabric.

## Arquitetura

```
 ┌──────────────┐  SSH (paralelo)   ┌────────────────────┐   SQLite (WAL)   ┌───────────────┐
 │ 50+ switches │ ◄──────────────── │ coletor (sanmon)   │ ───────────────► │ Streamlit     │
 │ Brocade FOS  │ lscfg / switchshow│ parse + deltas     │  ports_latest    │ (só lê o DB)  │
 └──────────────┘ sfpshow/porterrsh └────────────────────┘  ports_history   └───────────────┘
```

* **Coletor separado do portal** — o portal nunca abre SSH; abrir 50 sessões a cada clique seria lento
  e geraria carga nos switches. O coletor roda a cada `poll_interval` (padrão 5 min).
* **Virtual Fabric** — autodetectado com `lscfg --show`; cada FID é coletado com
  `fosexec --fid <FID> -cmd "<comando>"` e vira um "switch lógico" no portal.
  Force com `vf: true|false` no inventário.
* **Erros = delta entre coletas** — o `porterrshow` é cumulativo desde o último `statsclear`, então
  o portal sinaliza somente erros que *aumentaram* desde a coleta anterior (o total também é exibido).
  Contador que diminuiu (statsclear/reboot) é tratado como reset.
* **RX/TX** — limites globais em `config.yaml`; se o FOS informar o *warn low* do próprio SFP,
  ele é usado (`use_sfp_thresholds`).

## Classificação de portas

| Categoria     | Regra                                                                  | Severidade |
|---------------|------------------------------------------------------------------------|------------|
| Offline       | tem SFP e estado ≠ Online (No_Light, No_Sync, Laser_Flt, Mod_Inv…)     | crítico    |
| RX/TX baixo   | Online e potência ≤ limite de atenção / crítico                        | atenção/crítico |
| Erros         | incremento de crc_err, enc_out, link_fail, loss_sync, c3timeout… > 0   | atenção (crítico ≥ `error_crit_delta`) |
| Sem SFP / Desabilitada | No_Module ou `Disabled` no switchshow                         | ignorado   |

Portas livres com SFP (No_Light) podem ser ignoradas pelo toggle na barra lateral ou `ignore_no_light: true`.

## Rodando

A coleta é **manual**: botão **📡 Coletar agora** na barra lateral do portal, ou `./collect.sh`.

```bash
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt   # 1ª vez
cp config.example.yaml config.yaml     # inventário + limites
cp .env.example .env                   # SAN_USER / SAN_PASS
rm -f data/sanmon.db*                  # descarta dados simulados, se houver

./start.sh          # sobe o portal em segundo plano (http://<ip>:8501, logs em logs/)
./stop.sh           # para o portal
./collect.sh        # coleta pelo terminal
MOCK=1 ./start.sh   # portal com coleta simulada (sem switches)
```

Para subir o portal no boot: `crontab -e` → `@reboot /caminho/brocade-portal/start.sh`.

Coleta automática continua disponível, se um dia quiser: `./collect.sh --loop` (intervalo em `poll_interval`),
ou um cron chamando `./collect.sh`. Os arquivos em `deploy/` são para rodar via systemd.

**Erros com coleta manual:** o "Δ" é o incremento desde a coleta *anterior*, seja ela de 5 minutos ou de
3 dias atrás. Para ver se uma porta está gerando erros *agora*, colete duas vezes com alguns minutos
de intervalo.

Testes: `pip install pytest && pytest -q`

## Conta nos switches

Crie um usuário dedicado (ex.: `monitor`) com role `user` (somente leitura). Para switches com
Virtual Fabric, a conta precisa ter acesso a **todos os FIDs** (`userconfig --add monitor -r user -l 1-128 -h 128 -c user`)
e permissão para `fosexec`/`lscfg` (chassis role). Se não tiver, use `vf: false` e cadastre cada
switch lógico separadamente, ou ajuste o role.

## Notas / limitações

* `porterrshow` arredonda valores grandes (`1.5k`, `3.4m`), então deltas acima de ~1000 são aproximados.
  Os contadores de erro normalmente são pequenos, o que torna isso aceitável.
* Alternativa à CLI: o **FOS REST API** (FOS ≥ 8.2) devolve JSON com contadores exatos
  (`/rest/running/brocade-interface/fibrechannel`, `.../fibrechannel-statistics`,
  `/rest/running/brocade-media/media-rssi`, `?vf-id=<FID>`). Para trocar, basta implementar outro
  "runner" em `sanmon/collector.py` que devolva os mesmos dicts — banco e portal não mudam.
* `parsers.py` foi escrito para FOS 7.x–9.x; se alguma versão tiver formato diferente, adicione a saída
  real em `tests/fixtures/` e um teste.

## Estrutura

```
app.py                 # navegação do Streamlit
views/overview.py      # KPIs, resumo por fabric e por switch (clique abre o detalhe)
views/problems.py      # todas as portas com problema (abas: críticas/offline/RX-TX/erros), busca, CSV
views/switch.py        # detalhe por switch/FID ou por fabric inteira
views/history.py       # RX/TX e erros ao longo do tempo de uma porta
sanmon/parsers.py      # parsers de switchshow, sfpshow -all, porterrshow, lscfg
sanmon/collector.py    # SSH paralelo, VF/fosexec, gravação
sanmon/health.py       # regras de classificação
sanmon/db.py           # schema SQLite, cálculo de deltas, retenção
sanmon/mock.py         # gerador de saída CLI simulada
```
