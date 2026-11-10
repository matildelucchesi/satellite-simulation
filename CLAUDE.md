# Sviluppare il laboratorio TeraFlowSDN

## Regole del repository

- Leggi [AGENTS.md](AGENTS.md). Implementa modifiche solo con un livello di confidenza di almeno il 95%. Se un requisito resta ambiguo dopo aver letto codice, configurazione e test, chiedi chiarimenti.
- Graphify è disattivato. Usa ricerche e letture dirette con `rg` e `rg --files`. Non usare Graphify e non rigenerarne gli output.
- Parti da `git status --short` e dal diff dei file rilevanti. Il worktree può contenere modifiche in corso e risultati sperimentali tracciati. Preservali.
- Prima di modificare un comportamento, identifica il punto d'ingresso reale, i test che lo coprono e gli eventuali formati persistiti che deve continuare a leggere.
- Non modificare file in `src/` mentre un job di laboratorio è in esecuzione: il worker importa alcuni moduli durante la prova.

## Scopo

Il laboratorio confronta due strategie di migrazione del controller ETSI TeraFlowSDN 7.0.0 fra satelliti LEO. L'orbita è modellata da TLE reali: due piani Starlink adiacenti (guscio 53°/463 km, 31 + 31 satelliti), 3 laser per satellite (2 nel piano, 1 verso l'altro piano), dominio del controller di 16 satelliti, eventi di migrazione causati dall'ingresso in ombra della sorgente, percorsi multi-hop con ritardo di propagazione, allineamento di 60 s come ipotesi. Il laboratorio esegue realmente API TeraFlow, trasferimento TCP dello stato, autorità P4Runtime e forwarding Mininet/BMv2.

- **Hot** prepara la destinazione mentre la sorgente controlla ancora la rete; dopo il freeze trasferisce e applica il delta, verifica e passa l'autorità.
- **Cold** salva lo stato, arresta la sorgente, trasferisce e ripristina sulla destinazione; il downtime include tutto il lavoro successivo all'arresto.
- **Verifica** (`functional`): una migrazione Hot e una Cold sul primo evento del catalogo.
- **Esperimento** (`compare_events`): 3 eventi del catalogo (1 e 5 salti sullo stesso piano, 7 salti verso l'altro piano), con destinazione e percorso dentro il dominio del controller; un riscaldamento escluso, poi 3 repliche di Hot e Cold per evento, una replica dopo l'altra, ordine Hot/Cold casuale in ogni coppia con seme registrato; mediana, quartili e Cold − Hot appaiato con IC 95 %.

Il piano e le decisioni del progetto sono in [docs/piano-riprogettazione-simulatore.md](teraflow-migration-sim/docs/piano-riprogettazione-simulatore.md); le istruzioni d'uso nel [README](README.md).

## Struttura e punti d'ingresso

Il codice applicativo è in `teraflow-migration-sim/`. Salvo indicazione diversa, i percorsi partono da quella cartella. Descrizione dei moduli nel [README tecnico](teraflow-migration-sim/README.md).

| Area | File |
| --- | --- |
| Avvio | `tools/lab.py` (stack + console), `tools/experiment.py` (CLI e worker), `tools/serve_gui.py`, `tools/stack.py` |
| Scenario | `tools/build_scenario.py`, `tools/install_scenario.py`, `src/starlink_scenario.py`, `src/orbit.py`, `src/fixture.py` |
| Job | `src/jobs.py` (lock, worker, annullamento, recupero), `src/progress.py`, `src/checkpoints.py`, `src/storage.py` |
| Esperimento | `src/experiment.py` (`run`, `functional`, `recover`, `environment`), `src/event_comparison.py` |
| Migrazione live | `src/orchestrator.py`, `src/live_backend.py`, `src/tfs_adapter.py`, `src/handover.py`, `src/authority.py`, `src/p4_proxy.py`, `src/snapshot.py`, `src/transport.py`, `src/artifacts.py` |
| Servizio e misure | `src/emulator.py`, `src/link_control.py`, `src/probes.py`, `src/measurements.py`, `src/results.py` |
| Console | `src/web.py` (API `/api/v1/` e SSE), `web/app.js`, `web/experiment-state.js`, `web/orbit-view.js`, `web/stars.js` |

## Ambiente e verifiche locali

Windows, PowerShell e Python 3.13; per il live Docker Desktop con engine Linux e i materiali congelati del laboratorio; Node.js per i test JavaScript.

```powershell
Set-Location teraflow-migration-sim
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
node --test tests/test_experiment_state.cjs tests/test_orbit_motion.cjs
.\.venv\Scripts\python.exe tools/experiment.py --help
```

Se la sandbox restituisce `WinError 5` nelle directory temporanee dei test, punta `TMP` e `TEMP` a `..\.test-tmp`. Alcuni test P4 richiedono i protobuf del lab e vengono saltati sull'host.

## Laboratorio live

- Il progetto Compose `teraflow` usa `deploy/stack.yaml` e `deploy/lab.env`. NBI su 18080 (SAT-A) e 18081 (SAT-B), Mininet 18090, proxy P4 18091, console 18092. Mininet e proxy P4 leggono `config/fixture.json` all'avvio.
- Lo scenario installato è in `config/` (`scenario.json`, `selected_constellation.json`, `domain.json`, `migration_events.json`, `fixture.json`) e `results/direct_link_windows.json` (collegamenti laser). Si cambia solo con `tools/install_scenario.py`.
- Cambiare dominio o fixture richiede: fermare Mininet e proxy P4 (Windows tiene il file aperto), svuotare l'inventario precedente dai database Context di SAT-A e SAT-B (`tools/tfs_context_cleanup.py`), riavviare Mininet e proxy P4.
- Gli estremi del servizio di prova devono avere un percorso minimo unico nel dominio: TeraFlow sceglie il proprio percorso fra quelli equivalenti e le regole di inoltro devono coincidere.

## Invarianti per le modifiche

- Preserva l'autorità esclusiva e la separazione fra stato P4 staged e scritture attive. ACK e cutover solo dopo verifica del trasferimento e dell'equivalenza API; i test coprono l'assenza di ACK quando copia, staging o verifica falliscono.
- Preserva deadline orbitali (ingresso in ombra della sorgente, fine del percorso), timeout per assenza di progresso e budget delle sottofasi. Dopo la perdita del collegamento il trasferimento ricomincia da zero. Un recupero che fallisce nel fencing della destinazione o nel ripristino della sorgente ferma i retry.
- I contatti chiusi sono emulati con perdita `tc netem` al 100% nelle due direzioni, senza abbassare le interfacce.
- Baseline fresca e almeno dieci ping freschi consecutivi per il servizio; UDP è diagnostico. Registra separatamente downtime del controller, durata, perdita e ripristino del forwarding. Misure assenti restano assenti; Cold − Hot solo con entrambi i valori.
- Un solo job alla volta. Per interrompere usa la console o `tools/experiment.py stop --job-id ...`; per il recupero **Ripristina laboratorio** o `tools/experiment.py recover --wait`. Non cancellare a mano `results/jobs/lab.lock`.
- Uno stato del worker `completed` descrive il processo; verifica separatamente l'esito applicativo. Per modifiche web preserva sessione, controlli same-origin, replay SSE e registro dei download.

## Evidenze

| Percorso (relativo all'applicazione) | Uso |
| --- | --- |
| `results/jobs/job-*/` | Stato, eventi e log del worker; prima tappa per errori, annullamenti e recupero |
| `results/event-comparisons/events-*/` | Esperimento a eventi: `metadata.json`, `summary.csv` |
| `results/comparisons/compare-*/`, `results/functional-gate.json` | Verifiche |
| `results/runs/run-*/` | Singola migrazione: input, fasi (`operations.jsonl`), baseline, autorità, sonde, pulizia della destinazione |
| `artifacts/constellation-profiles/<profilo>/` | Profilo dello scenario con manifest e archivio della configurazione precedente |

Prima di riportare misure, individua job, evento, input e repliche verificabili.
