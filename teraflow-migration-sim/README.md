# Descrizione tecnica

Il simulatore confronta la migrazione **Hot** e **Cold** del controller TeraFlowSDN 7.0 fra satelliti LEO. La geometria orbitale è modellata da TLE reali; la migrazione (API TeraFlow, trasferimento TCP dello stato, autorità P4Runtime, forwarding Mininet/BMv2) è eseguita davvero nel laboratorio Docker. Istruzioni d'uso nel [README principale](../README.md).

## Fasi

| Fase | Cosa fa | Quando | Laboratorio |
| --- | --- | --- | --- |
| 0. Scenario | Selezione dei piani, replay orbitale, laser, percorsi, dominio, catalogo eventi | Una volta (`tools/build_scenario.py`, `tools/install_scenario.py`) | No |
| 1. Laboratorio | Stack Compose, rete del dominio in TeraFlow, baseline | A ogni prova, nella preparazione | Sì |
| 2. Verifica | Una migrazione Hot e una Cold sul primo evento (`functional`) | Per sessione o dopo modifiche al codice | Sì |
| 3. Esperimento | Riscaldamento e 3 repliche di Hot e Cold su 3 eventi, ordine casuale per coppia (`compare_events`) | Per esperimento | Sì |
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

## Fasi della migrazione

L'orchestratore (`src/orchestrator.py`) emette una fase per ogni passo; la pagina Scenario le ricava dallo stesso flusso di eventi (`web/mission.js`). Solo i due estremi si avviano o si arrestano: i satelliti intermedi del percorso multi-hop inoltrano soltanto i pacchetti del trasferimento e non hanno fasi proprie.

| Fase | Hot | Cold | Dove | Nel downtime |
| --- | --- | --- | --- | --- |
| Trigger: la sorgente sta per entrare in ombra | sì | sì | sorgente | no |
| Allineamento del percorso: 60 s di contatto continuo sull'intero percorso multi-hop (ipotesi) | sì | sì | percorso | no |
| Quiete e snapshot dello stato | snapshot | quiete e snapshot | sorgente | no |
| Arresto del controller | — | sì | sorgente | sì (inizio) |
| Trasferimento dello stato | sì | sì | percorso | Cold |
| Avvio del controller (software già a bordo) | sì | sì | destinazione | Cold |
| Ripristino dello stato | sì | sì | destinazione | Cold |
| Freeze del controller | sì | — | sorgente | sì (inizio) |
| Trasferimento e applicazione del delta | sì | — | percorso, destinazione | sì |
| Verifica di equivalenza delle API | sì | sì | destinazione | sì |
| ACK e passaggio dell'autorità P4 | sì | sì | proxy P4 | sì (fine) |

- Il collegamento della migrazione esiste quando nel grafo laser c'è un percorso fra sorgente e destinazione (`Orbit.migration_link`); il percorso disegnato è quello del catalogo, che coincide con il percorso modellato per almeno 15 minuti dal trigger.
- Un tentativo fallito revoca la destinazione, restituisce il controllo alla sorgente (`rollback`) e riparte dall'allineamento, fino a 3 tentativi; con un fallimento del fencing o del ripristino i tentativi si fermano (`recovery_required`).
- L'orbita resta ferma a T−30 s durante la preparazione del laboratorio, poi avanza di un secondo orbitale al secondo.

## Migrazione Hot: ordine delle fasi in teoria

La migrazione Hot segue lo schema *pre-copy* della migrazione a caldo delle macchine virtuali [1], applicato al controller SDN [3]. **La destinazione si avvia prima del freeze**, mentre la sorgente controlla ancora la rete. Dopo il freeze si trasferisce e si applica solo il delta, su un controller già in esecuzione.

1. **Preparazione (sorgente attiva, nessun downtime).** La destinazione si avvia in ruolo di riserva e riceve una copia completa dello stato. Eventuali giri successivi copiano ciò che è cambiato nel frattempo, finché il residuo è piccolo [1]. In riserva la destinazione non scrive sugli switch: in OpenFlow ha ruolo *slave* [4]; in P4Runtime è un client non primario, con `election_id` più basso del primario [5]. Le sue regole restano in staging.
2. **Freeze (inizio del downtime).** La sorgente non accetta più modifiche: niente richieste NBI e niente scritture sul piano dati.
3. **Stop-and-copy del delta [1].** Si trasferiscono le sole modifiche successive all'ultima copia e la destinazione le applica.
4. **Verifica.** La destinazione deve essere equivalente alla sorgente prima di ricevere l'autorità.
5. **Cutover (fine del downtime).** La destinazione diventa primaria (ruolo *master* [4] o `election_id` più alto [5]); la sorgente perde l'autorità. Durante il passaggio c'è sempre un solo controller che scrive [3].

Il downtime Hot è quindi circa trasferimento del delta + applicazione + verifica + passaggio dell'autorità. Se la destinazione si avviasse dopo il delta, nel downtime entrerebbero anche l'avvio dei servizi e il caricamento dello stato: la migrazione si avvicinerebbe alla Cold, dove l'avvio della destinazione è per definizione dentro il downtime.

Esiste anche la variante *post-copy*: la destinazione prende il controllo con uno stato minimo e recupera il resto su richiesta [2]. Anche lì la destinazione è avviata prima del cutover. In nessuna variante a caldo l'avvio del controller cade nella finestra di downtime.

Nel laboratorio l'ordine è lo stesso della tabella precedente: snapshot, trasferimento, avvio e ripristino precedono il freeze, e solo delta, verifica e passaggio dell'autorità stanno nel downtime. I due differiscono in tre punti.

- C'è una sola copia completa, senza giri iterativi.
- La riserva è realizzata dal proxy P4 (`src/p4_proxy.py`, `src/authority.py`). Il proxy inoltra agli switch solo le scritture del controller attivo; quelle della destinazione restano in staging fino al cutover. Al backend il proxy si presenta con un unico `election_id`.
- L'ACK e il cutover arrivano solo dopo la verifica del trasferimento e l'equivalenza delle API.

### Fonti

1. C. Clark, K. Fraser, S. Hand, J. G. Hansen, E. Jul, C. Limpach, I. Pratt, A. Warfield, «Live Migration of Virtual Machines», *NSDI 2005*. <https://www.usenix.org/legacy/event/nsdi05/tech/full_papers/clark/clark.pdf>. Pre-copy iterativo, stop-and-copy finale, downtime come durata della sola fase di arresto.
2. M. R. Hines, K. Gopalan, «Post-copy based live virtual machine migration using adaptive pre-paging and dynamic self-ballooning», *VEE 2009*. DOI [10.1145/1508293.1508301](https://doi.org/10.1145/1508293.1508301). Variante post-copy.
3. A. Dixit, F. Hao, S. Mukherjee, T. V. Lakshman, R. Kompella, «Towards an Elastic Distributed SDN Controller», *HotSDN 2013*. DOI [10.1145/2491185.2491193](https://doi.org/10.1145/2491185.2491193). Protocollo di migrazione dello switch fra controller con un solo controller attivo durante il passaggio.
4. Open Networking Foundation, *OpenFlow Switch Specification*, versione 1.3.0, 2012, sezione «Multiple Controllers». <https://opennetworking.org/wp-content/uploads/2014/10/openflow-spec-v1.3.0.pdf>. Ruoli master, slave ed equal.
5. P4.org API Working Group, *P4Runtime Specification*, versione 1.3.0, sezione «Client Arbitration and Controller Replication». <https://p4lang.github.io/p4runtime/spec/v1.3.0/P4Runtime-Spec.html>. Client primario e di riserva, `election_id`.

## Scelte del modello

- Due piani adiacenti del guscio Starlink 53°/463 km (RAAN 80,8° e 82,8°, 31 + 31 satelliti). Con piani così coerenti la topologia laser resta stabile per tutto il giorno; ciò che cambia nel tempo è l'illuminazione.
- 3 laser per satellite: 2 verso i vicini dell'anello, 1 verso un partner stabile sull'altro piano; 60 s di allineamento per i collegamenti che si formano durante il replay.
- Il laboratorio emula solo il dominio del controller (16 satelliti); il resto della costellazione è modellato e fa da relè per il percorso multi-hop della migrazione.
- Gli estremi del servizio di prova hanno un percorso minimo unico (capi dell'arco del piano 1), così il percorso di TeraFlow e le regole di inoltro coincidono; il servizio descrive solo gli switch del percorso.
- Software del controller a bordo: migra solo lo stato. Il database della destinazione viene svuotato prima del trigger.
- Velocità unica di 1 Gbit/s; ritardo di propagazione per collegamento pari a distanza / velocità della luce: `tc netem` sui collegamenti di Mininet (aggiornato con la geometria) e, per il trasferimento dello stato che avviene sull'host, un modello TCP con handshake, slow start (finestra iniziale di 10 segmenti) e conferma finale sul ritardo dell'intero percorso (`src/transport.py`).
- Eventi (combinazione 12): 1 salto sullo stesso piano (62768 → 62760), 5 salti sullo stesso piano (62774 → 62760), 7 salti verso l'altro piano (60150 → 62768), ciascuno con sorgente e fascia del giorno fissate (`EVENT_SPECS`); destinazione e percorso dentro il dominio del controller, destinazione al sole più a lungo della sorgente; destinazione al sole per almeno 10 minuti e percorso stabile per 15 (`starlink_scenario.designed_events`).
- Esperimento: riscaldamento escluso, 3 repliche replica dopo replica, ordine Hot/Cold casuale per coppia con seme registrato; statistiche in `event_comparison.event_statistics`.
- Politica di destinazione (riferimento, `starlink_scenario.policy_events`): a ogni ingresso in ombra di un satellite del dominio sceglie la destinazione con costo minimo, latenza media di controllo verso gli altri satelliti del dominio (ms, propagazione sui collegamenti interni) + k · downtime / permanenza · 1000, con k = 1 e il downtime Hot misurato (7 s). La permanenza è la luce della destinazione meno l'anticipo del trigger. Durata del percorso e salti non sono pesati: la prima è uguale per tutte le destinazioni di un evento, i salti seguono la luce guadagnata. `build_scenario.py` scrive in `events.json` le scelte, il riepilogo e il confronto con i tre eventi progettati (`destination_policy`); gli eventi dell'esperimento non cambiano.
- Ipotesi: prima di ogni tentativo il percorso deve restare disponibile per 60 s di fila (`fso.alignment_s`); i laser già puntati non lo richiederebbero.

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
