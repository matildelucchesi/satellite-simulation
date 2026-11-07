# Descrizione tecnica

Il simulatore confronta la migrazione **Hot** e **Cold** del controller TeraFlowSDN 7.0 fra satelliti LEO. La geometria orbitale è modellata da TLE reali; la migrazione (API TeraFlow, trasferimento TCP dello stato, autorità P4Runtime, forwarding Mininet/BMv2) è eseguita davvero nel laboratorio Docker. Istruzioni d'uso nel [README principale](../README.md).

## Fasi

| Fase | Cosa fa | Quando | Laboratorio |
| --- | --- | --- | --- |
| 0. Scenario | Selezione dei piani, replay orbitale, laser, percorsi, dominio, catalogo eventi | Una volta (`tools/build_scenario.py`, `tools/install_scenario.py`) | No |
| 1. Laboratorio | Stack Compose, rete del dominio in TeraFlow, baseline | A ogni prova, nella preparazione | Sì |
| 2. Verifica | Una migrazione Hot e una Cold sul primo evento (`functional`) | Per sessione o dopo modifiche al codice | Sì |
| 3. Esperimento | Hot e Cold su 3 eventi, ordine alternato (`compare_events`) | Per esperimento | Sì |
| 4. Analisi | Fasi, Cold − Hot, fattibilità a posteriori, CSV | Alla fine di ogni esperimento | No |

## Moduli (`src/`)

| Area | Moduli |
| --- | --- |
| Scenario | `starlink_scenario` (piani, 3 laser, percorsi multi-hop, dominio, eventi), `orbit` (replay, illuminazione, grafo laser, grafo del laboratorio, collegamento della migrazione), `fixture` (rete del dominio e servizio L2) |
| Laboratorio | `live_backend` (Compose, preparazione, sonde, topologia, operazioni della migrazione), `tfs_adapter` (API TeraFlow: export, restore, reconcile, verify), `p4_proxy` (autorità P4Runtime), `emulator` e `link_control` (Mininet/BMv2, collegamenti con `tc netem`), `udp_probe`, `deployment`, `processes`, `preparation_budget` |
| Migrazione | `orchestrator` (macchina a stati Hot/Cold), `handover`, `authority`, `snapshot`, `transport` (TCP con limitatore e verifica), `artifacts` (hash e ricevute), `probes`, `measurements`, `clock` |
| Esperimento | `experiment` (verifica, singola prova, recupero, ambiente), `event_comparison` (esperimento a eventi, fasi, fattibilità, CSV), `results` |
| Job e console | `jobs` (un job alla volta, worker separato, lock, recupero), `progress`, `checkpoints`, `storage`, `web` (API locale e SSE) |

## Invarianti

- Autorità esclusiva: la destinazione riceve l'ACK e il cutover solo dopo verifica del trasferimento, equivalenza delle API e stato P4 pronto; copia, staging o verifica falliti non producono ACK.
- Contatti chiusi emulati con perdita `tc netem` al 100% nelle due direzioni; dopo la perdita del collegamento il trasferimento riparte da zero.
- Il recupero si ferma se fallisce il fencing della destinazione o il ripristino della sorgente.
- La baseline del servizio richiede API, autorità P4 e almeno 10 ping freschi consecutivi; UDP è diagnostico.
- Il laboratorio accetta un solo job alla volta; il worker sopravvive alla chiusura della console.
- Misure assenti restano assenti; Cold − Hot si calcola solo quando entrambi i valori esistono.

## Scelte del modello

- Due piani adiacenti del guscio Starlink 53°/463 km (RAAN 80,8° e 82,8°, 31 + 31 satelliti). Con piani così coerenti la topologia laser resta stabile per tutto il giorno; ciò che cambia nel tempo è l'illuminazione.
- 3 laser per satellite: 2 verso i vicini dell'anello, 1 verso un partner stabile sull'altro piano; 60 s di allineamento per i collegamenti che si formano durante il replay.
- Il laboratorio emula solo il dominio del controller (16 satelliti); il resto della costellazione è modellato e fa da relè per il percorso multi-hop della migrazione.
- Gli estremi del servizio di prova hanno un percorso minimo unico (capi dell'arco del piano 1), così il percorso di TeraFlow e le regole di inoltro coincidono; il servizio descrive solo gli switch del percorso.
- Software del controller a bordo: migra solo lo stato. Il database della destinazione viene svuotato prima del trigger.
- Velocità unica di 1 Gbit/s.

## Configurazione

- `config/scenario.json`: orbita, laser (`fso`), dominio, eventi, opzioni della migrazione (`migration`).
- `config/selected_constellation.json`, `config/domain.json`, `config/migration_events.json`: scenario installato.
- `config/fixture.json`: rete emulata (dispositivi, collegamenti, host del servizio).
- `config/artifact_manifest.json`, `config/lab-manifest.json`, `config/teraflow-source.json`: materiali del laboratorio.
- `deploy/stack.yaml`, `deploy/lab.env`: gruppo Compose `teraflow`; NBI su 18080/18081, Mininet 18090, proxy P4 18091, console 18092.

## Strumenti (`tools/`)

- Uso: `lab.py` (avvio, stato, arresto), `experiment.py` (job da riga di comando e worker), `stack.py`, `serve_gui.py`, `start_gui.cmd`.
- Scenario: `build_scenario.py`, `install_scenario.py`, `tfs_context_cleanup.py` (svuota l'inventario del laboratorio in un database Context), `tle_catalog.py` (lettura del catalogo TLE).
- Materiali del laboratorio: `generate_stack.py`, `prepare_lab.py`, `prepare_artifacts.py`, `build_tfs_images.py`, `prepare_tfs_source.py`, `prepare_device_patch.py`, `prepare_l2_patch.py`, `validate_artifact_manifest.py`, `check_tfs_hosts.py`, `live_preflight.py`.

## Test

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
node --test tests/test_experiment_state.cjs tests/test_orbit_motion.cjs
```

Alcuni test P4 richiedono i protobuf dell'ambiente Linux del laboratorio e vengono saltati sull'host.
