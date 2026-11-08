# Piano di riprogettazione del simulatore

Stato: bozza da rivedere, 7 novembre 2026. Nessuna modifica al codice è ancora stata fatta.

## 1. Perché cambiare

Il confronto guidato attuale non arriva alla misura. Il 4 novembre 2026 la calibrazione sulla rete completa (64 dispositivi) è riuscita (job `job-8fd1d5dd9de74dafa831176dc2a32132`). Una migrazione è però risultata di circa 1.390 s. Con i margini, il planner riserva 2.776 s di operazione e 1.079 s di recupero, a fronte di un periodo di luce di circa 4.100 s. La ricerca della partenza non ha trovato piani con tre migrazioni concatenate.

Le prove offline mostrano che un piano esiste solo con una finestra ridotta al 25% (scala 0,25) e non esiste fra 0,3 e 1,0. Il tempo è dominato dal ripristino TeraFlow: 64 `POST /devices` sequenziali, circa 7,6 s ciascuno. Seguono effetti del laboratorio: caricamento delle immagini nel daemon condiviso, pulizia della destinazione e riconciliazione della topologia accodata.

## 2. Decisioni

Decise:

| # | Decisione |
| --- | --- |
| D1 | Obiettivo: confrontare Hot e Cold su downtime del controller e durata della migrazione. Il mezzo di comunicazione è un modulo sostituibile, perché in seguito si passerà dal laser alla radio. |
| D2 | L'orbita fornisce il **contesto** degli eventi, non un vincolo di ammissione. La fattibilità orbitale diventa un risultato per evento. |
| D3 | Repliche come **eventi indipendenti**. Si eliminano le tre migrazioni concatenate come requisito. |
| D4 | La riserva di recupero dentro la finestra orbitale diventa facoltativa. |
| D5 | Rete ridotta su **due piani orbitali**. |
| D6 | Migrazione **multi-hop** sui satelliti della costellazione. |
| D7 | Struttura Starlink: **3 laser** per satellite. Ipotesi di progetto: 2 nello stesso piano e 1 verso il piano adiacente. Antenne Ku e Ka/E documentate per la futura variante radio. |
| D8 | Piani: guscio 53°, circa 463 km, RAAN **80,8° e 82,8°**, 31 + 31 satelliti (verificati offline con SGP4 sulle 24 ore). |
| D9 | Dominio del controller: **8 + 8 satelliti** contigui sui due piani. Gli altri satelliti esistono solo nel modello orbitale e fanno da relè. |

Decise il 7 novembre 2026, dopo la discussione delle proposte:

| # | Decisione |
| --- | --- |
| D10 | **Migrazione il più possibile realistica.** Il software del controller è già a bordo di ogni satellite, come il software di volo: migra lo **stato**, non le immagini. La destinazione avvia i container dalla propria memoria locale, e quell'avvio resta nella misura. Il caricamento delle immagini nel daemon Docker condiviso è un effetto del laboratorio e va fuori dalla misura. Il trasferimento delle immagini resta una variante opzionale ("aggiornamento software"). |
| D11 | **Orbita che scorre durante la migrazione.** Il clock orbitale avanza in tempo reale anche durante la misura. Percorsi e partner fra piani possono cambiare (con l'allineamento di 60 s), il trasferimento riparte da zero se il percorso cade, e l'ombra della sorgente resta una scadenza vera. Gli aggiornamenti di topologia arrivati durante la migrazione si applicano dopo, e il loro costo fa parte della misura. Hot e Cold partono dallo stesso istante orbitale dello stesso evento, quindi incontrano la stessa sequenza geometrica. Una migrazione che non finisce prima dell'ombra è un esito da riportare, non un caso da escludere. |
| D12 | **Esperimento ridotto**: 3 eventi × 2 modalità = **6 migrazioni**, con ordine Hot/Cold alternato fra gli eventi. |
| D15 | **Una sola velocità: 1 Gbit/s**, per ogni tratto del percorso. Le altre due velocità (100 Mbit/s e 10 Gbit/s) escono dall'esperimento. Motivi: (1) è la velocità più alta che il laboratorio riproduce fedelmente: nell'ultima prova dell'host (`results/environment.json`) 1 Gbit/s configurato ha dato 1,0 Gbit/s misurato, mentre 10 Gbit/s ne ha dati circa 3. Così il valore usato nel modello coincide con quello misurato. (2) Con il solo stato (centinaia di kB con 16 dispositivi) il trasferimento a 1 Gbit/s dura pochi millisecondi, contro decine o centinaia di secondi di avvio e ripristino del controller. Le conclusioni valgono quindi anche per qualsiasi velocità più alta, compresi i laser Starlink, che SpaceX dichiara "fino a 200 Gbps". (3) È la velocità della verifica funzionale e delle calibrazioni precedenti, quindi le misure restano confrontabili con quelle storiche. Si dichiara che 1 Gbit/s è un valore prudente, non quello nominale Starlink. La velocità tornerà un fattore da variare con la radio o con la variante che trasferisce le immagini. |
| D13 | Il vecchio confronto guidato (piano concatenato, ricerca della partenza, base comune) resta come **percorso storico**. I risultati salvati restano leggibili, ma il percorso esce dalla console. |
| D14 | La calibrazione Cold/Hot **non è più un prerequisito**. Al suo posto c'è una verifica funzionale breve per sessione; le misure dell'esperimento sono esse stesse il risultato. |

## 3. Le fasi del nuovo simulatore

La divisione in fasi resta. Ogni fase produce artefatti con un'identità (hash degli input) e viene rieseguita solo quando i suoi input cambiano.

| Fase | Cosa fa | Quando si esegue | Laboratorio |
| --- | --- | --- | --- |
| **0. Scenario** | Dai TLE: selezione dei due piani, replay orbitale, illuminazione, collegamenti con la regola dei 3 laser, percorsi multi-hop, dominio, fixture di rete, catalogo degli eventi | **Una volta.** Di nuovo solo se cambiano TLE, piani, parametri FSO o dominio | No |
| **1. Laboratorio** | Stack Compose, immagini presenti su entrambi i satelliti, rete del dominio costruita e verificata (API, autorità, ping) | All'avvio di una sessione. Riusa lo stato esistente con la riconciliazione incrementale | Sì |
| **2. Verifica** | Una migrazione Hot e una Cold su un evento di prova, con verifica del servizio | Una volta per sessione, o dopo modifiche al codice | Sì |
| **3. Esperimento** | 3 eventi × 2 modalità con l'orbita che scorre, misure per fase | Per ogni esperimento | Sì |
| **4. Analisi** | Metriche, Cold−Hot appaiato, fattibilità orbitale a posteriori, report | Dopo ogni esperimento; ripetibile offline | No |

### Cosa si calcola una volta e cosa no

| Artefatto | Dipende da | Si rigenera quando |
| --- | --- | --- |
| Selezione dei piani e replay orbitale | TLE, epoca, piani scelti | Cambia il TLE o la scelta dei piani |
| Collegamenti e percorsi multi-hop | Replay, portata FSO, allineamento, regola dei 3 laser | Cambia uno di questi parametri |
| Dominio e fixture di rete | Piani, dimensione del dominio, servizio | Cambia il dominio |
| Catalogo eventi | Replay, collegamenti, dominio, criteri di selezione | Cambiano gli input sopra |
| Stato TeraFlow nel laboratorio | Fixture, immagini | Si riconcilia a ogni sessione; si ricostruisce solo se incompatibile |
| Misure | Codice, immagini, laboratorio | A ogni esperimento: sono il risultato |

Il modello orbitale è già congelato oggi (`tools/prepare_orbit.py` verifica l'hash di `artifacts/orbit/replay.npz`). A ogni esperimento si ripetono invece la ricerca della partenza (600 s) e la base comune. E la calibrazione si rifà dopo **qualsiasi** modifica a `src/`, perché l'impronta del motore (`src/simulation.py:26`) copre tutti i file `src/*.py`. Nel nuovo disegno questi passaggi escono dal percorso di ogni esperimento.

## 4. Lavori

Ogni lavoro elenca file, test e criterio di completamento. I lavori A–C sono offline e non occupano il laboratorio.

### A. Scenario orbitale

- `tools/select_constellation.py`: selezione per guscio e RAAN (80,8°/82,8°), solo TLE recenti, quote coerenti. Salvare la scelta in `config/selected_constellation.json` conservando i metadati di provenienza.
- `tools/check_direct_links.py`: regola dei 3 laser (2 nello stesso piano, 1 verso il piano adiacente), linea di vista, portata e allineamento. Ogni cambio del partner fra piani paga l'allineamento.
- `src/planner.py` (`OrbitIndex`): generalizzare `service_periods` in "fino a quando esiste un percorso fra A e B", con numero di salti e distanza.
- `tools/prepare_orbit.py`: rigenerare il replay per i 62 satelliti.
- Test: `test_orbital_artifacts.py`, `test_events.py`, nuovi test per la regola dei 3 laser e per i percorsi multi-hop.
- Fatto quando: gli artefatti sono rigenerati con hash registrati; anelli e collegamenti verificati sulle 24 ore come nell'analisi offline.

### B. Dominio e rete ridotta

- `src/fixture.py` e `config/fixture.json`: 16 dispositivi (8 + 8 contigui), collegamenti del dominio, servizio con estremi e percorso dentro il dominio.
- `src/emulator.py` e Mininet: solo gli switch del dominio.
- Test: `test_scenario_loading.py`, `test_topology_state.py`, `test_calibration_network.py`.
- Fatto quando: la rete del dominio si carica in TeraFlow e la baseline (API, autorità, 10 ping) passa.

### C. Catalogo eventi

- `src/events.py` e `src/event_sampling.py`: un evento = sorgente nel dominio vicina all'ombra, destinazione raggiungibile (diretta o multi-hop), istante, salti, luce guadagnata.
- Selezione deterministica di 3 eventi: quantili 0, 0,5 e 1 degli eventi fattibili ordinati per (salti, istante). Con questi piani tutti gli eventi richiedono gli stessi salti, quindi i 3 eventi sono repliche distribuite nella giornata (vedi sezione 7).
- Per ogni evento, registrare in anticipo i cambi di percorso e di partner attesi nella finestra della migrazione, così l'esito live si può confrontare con la geometria.
- Fatto quando: il catalogo è congelato con hash ed è riproducibile.

### D. Migrazione live

In ordine di sicurezza. Ogni punto si misura da solo rispetto a una baseline, prima di passare al successivo.

1. **Software a bordo (D10).** `src/orchestrator.py:73` oggi trasferisce il bundle di immagini a ogni migrazione: va reso opzionale (variante "aggiornamento software"). Le immagini si caricano su entrambi i satelliti nella fase 1, togliendo dalla misura `image_load_shared_daemon` (circa 95 s). L'avvio dei container sulla destinazione resta misurato.
2. **Destinazione pulita per costruzione.** Sostituire `target_perimeter_cleanup` (circa 105 s) con una verifica "vuota" e una pulizia solo se serve. Su un satellite reale la destinazione non ha residui di prove precedenti.
3. **Orbita che scorre (D11).** Il clock orbitale non si ferma durante la misura. `queued_topology_apply` (90–135 s con 64 dispositivi) resta nella misura come costo reale; va registrato separatamente, con il numero di cambi di topologia applicati. Se il percorso cade, il trasferimento riparte da zero; se arriva l'ombra della sorgente, la migrazione fallisce e si registra.
4. **Collegamento della migrazione = percorso.** `src/live_backend.py:550` usa il percorso multi-hop invece del contatto diretto, valutato a ogni istante del trasferimento. Velocità di 1 Gbit/s per tratto (D15), applicata dal limitatore già presente in `src/transport.py`. Latenza per salto opzionale.
5. **Una sola velocità (D15).** `config/scenario.json` (`fso.useful_throughput_bps`) passa a `[1000000000]`. I controlli che iterano sulle velocità (`src/experiment.py:220` e `:260`, `src/analysis.py`, `src/preparation.py`, `src/continuous_comparison.py`) vanno verificati con una lista di un solo valore. La verifica di capacità dell'host resta, e deve confermare 1 Gbit/s. Nel percorso storico restano leggibili i risultati con le tre velocità.
6. **Aggiunta dei dispositivi in parallelo, sperimentale.** `src/tfs_adapter.py:181` oggi è sequenziale sotto un unico lock. Va provato dietro un'opzione, con verifica di equivalenza obbligatoria.
7. **Programma P4 alla riconnessione, indagine.** Verificare nel driver P4 di TeraFlow se i circa 7,6 s per dispositivo includono il ricaricamento del programma sugli switch. Se sì, valutare la sola riconnessione, più veloce e più realistica.

Invarianti da preservare: autorità esclusiva, separazione fra stato P4 staged e scritture attive, ACK e cutover solo dopo la verifica, nessun ACK se copia, staging o verifica falliscono, trasferimento da zero dopo la perdita del collegamento, recupero che si ferma se fallisce il fencing.

Test: `test_authority_orchestrator.py`, `test_artifacts_snapshot_transport.py`, `test_restore_reconcile.py`, `test_tfs_adapter_cleanup.py`, `test_link_control.py`.

### E. Esperimento e job

- Nuova operazione (nome proposto: `compare_events`) in `src/jobs.py` e `src/experiment.py`, con lo stesso contratto in CLI (`tools/experiment.py`) e GUI. Esperimento base: 3 eventi a 1 Gbit/s (D12, D15); niente parametro di velocità nella console. Ordine Hot/Cold alternato fra gli eventi.
- Riusa `functional()` (`src/experiment.py:501`) come schema: Hot e Cold sullo stesso evento, dallo stesso istante orbitale e dallo stesso stato iniziale.
- La calibrazione esce dal percorso principale (D14). La ricerca della partenza e la base comune restano solo per il percorso storico (D13).
- Test: `test_jobs_storage.py`, `test_fso_comparison.py`, `test_automatic_contract.py` aggiornato.

### F. Console

File: `web/index.html`, `web/app.js`, `web/experiment-state.js`, `web/orbit-view.js`, `web/style.css`; API in `src/web.py`. La console e la CLI espongono le stesse operazioni con gli stessi parametri.

Le tre pagine attuali (Configurazione, Simulazione, Risultati) restano, ma cambiano contenuto.

**Configurazione.** Diventa una lista di controllo delle fasi 0–2, seguita dall'avvio.

| Oggi | Dopo |
| --- | --- |
| Menu "Velocità utile del canale" con tre valori | Rimosso. Testo fisso: "Collegamento laser: 1 Gbit/s (valore prudente; Starlink dichiara fino a 200 Gbps)" (D15) |
| "Dati da migrare" e la nota "Vengono trasferiti le immagini e lo stato" | Solo lo stato del controller, con la dimensione misurata. Nota: "Il software del controller è già a bordo di ogni satellite" (D10) |
| Regola "3 migrazioni verificate per HOT e 3 per COLD" e testi sulla partenza automatica dopo la calibrazione | "3 eventi; per ciascuno Hot e Cold dallo stesso istante orbitale, in ordine alternato" (D12) |
| Riquadro "Scenario iniziale" con "Crea scenario iniziale" (base comune, calibrazione) | Riquadro **Scenario** (fase 0), in sola lettura: piani (RAAN 80,8° e 82,8°, 31 + 31 satelliti), dominio 8 + 8, 3 laser per satellite, identità e data degli artefatti. Avviso se gli input sono cambiati e serve rigenerare |
| — | Tabella dei **3 eventi** del catalogo: sorgente, destinazione, salti, istante, luce residua della sorgente, luce guadagnata |
| "Requisiti del laboratorio" | Riquadro **Laboratorio** (fase 1): stack, immagini su entrambi i satelliti, rete del dominio caricata, baseline. Pulsante "Prepara laboratorio" |
| Elementi nascosti della calibrazione (`calibration-*`) | Rimossi. Riquadro **Verifica** (fase 2): esito e data dell'ultima verifica Hot + Cold, pulsante "Esegui verifica" (D14) |
| Pulsante "Avvia" | "Avvia esperimento", attivo solo con laboratorio pronto e verifica valida. "Ripristina laboratorio" invariato |

**Simulazione.** Segue l'esperimento evento per evento.

- Barra di fase: "Evento 1/3 · Hot → Ripristino → Cold" al posto di "Preparazione → Hot → Ripristino → Cold → Risultati".
- Indicatori: evento e modalità correnti; fase della migrazione (snapshot, trasferimento, avvio, ripristino, verifica, cutover) con il suo tempo; percorso e numero di salti; tempo orbitale che scorre (D11); cambi di topologia accodati; tempo che manca all'ombra della sorgente.
- Vista orbitale: i due piani con il dominio evidenziato, i collegamenti laser attivi (2 nello stesso piano, 1 verso l'altro piano), il percorso multi-hop della migrazione in corso e la zona d'ombra.
- Se il percorso cade o arriva l'ombra, il messaggio lo dice esplicitamente: "trasferimento ripartito da zero" oppure "migrazione non completata prima dell'ombra".
- Rimossi dal percorso principale i messaggi della ricerca della partenza e della calibrazione. `experiment-state.js` li conserva solo per mostrare correttamente i job storici (D13).

**Risultati.**

- Tabella per evento: Hot e Cold affiancati con downtime, durata, esito, salti, cambi di topologia e velocità misurata. Cold−Hot per evento, solo quando le misure sono confrontabili.
- Scomposizione per fase (avvio, ripristino, trasferimento, cutover), con barre affiancate Hot/Cold.
- Fattibilità a posteriori: con il solo contatto diretto, con il multi-hop, prima dell'ombra.
- Le misure assenti si mostrano come "non misurato", mai come zero.
- Nessuna statistica aggregata oltre i 3 eventi: valori per evento e, al più, l'intervallo fra minimo e massimo.
- Selettore dello storico: i confronti continui precedenti restano consultabili, etichettati "storico".

**Finestra Info.** Aggiornare le spiegazioni: fasi, eventi, multi-hop e struttura del satellite (con il disegno `docs/img/starlink-satellite.svg`).

Da preservare: sessione, controlli same-origin, replay SSE, registro dei download, ripresa dopo la chiusura della scheda, comandi Interrompi e Ripristina.

Test: `tests/test_experiment_state.cjs` (nuove fasi e lettura dei job storici), `tests/test_orbit_motion.cjs` (due piani, dominio, percorso), `test_web.py` (nuove API e contratto CLI/GUI). Verifica finale nel browser: flusso completo con un evento.

### G. Risultati

- Per ogni migrazione: avvio, ripristino, trasferimento, cutover, downtime, perdita e ripristino del forwarding, numero di salti, distanza del controller dagli switch.
- Fattibilità a posteriori: "sarebbe rientrata con il contatto diretto?", "con il multi-hop?", "prima dell'ombra?".
- Cold−Hot solo su eventi e metriche confrontabili. Le misure assenti restano assenti.
- `src/results.py`, `src/analysis.py`, `src/simulation_report.py`; continuare a leggere i risultati storici già salvati.

### H. Documentazione

- `README.md`, `docs/guided-flow.md`, `CLAUDE.md`: nuove fasi e nuovo percorso principale.
- Limiti dichiarati: laboratorio su un solo host con daemon Docker condiviso, multi-hop modellato e non emulato pacchetto per pacchetto, accuratezza limitata dei TLE.

## 5. Ordine di lavoro e traguardi

| Traguardo | Contenuto | Verifica |
| --- | --- | --- |
| M1 | Lavori A, C e dominio (B, solo selezione). Console: riquadro Scenario e tabella eventi | Suite locale; profilo congelato con hash; nessun laboratorio |
| M2 | Installazione del profilo (dopo il recupero del laboratorio), fixture e Mininet sui 16 satelliti del dominio, estremi del servizio, fase 2. Console: vista orbitale con due piani e dominio, riquadri Laboratorio e Verifica | Baseline e una migrazione Hot e una Cold riuscite |
| M3 | Lavoro D, punti 1–5, uno alla volta. Console: rimozione del menu delle velocità | Ogni modifica misurata rispetto a M2 |
| M4 | Lavoro E + G, esperimento completo. Console: pagine Simulazione e Risultati | 6 migrazioni, report, Cold−Hot appaiato |
| M5 | Lavoro H, finestra Info, rifinitura della console; lavoro D, punti 6–7, se le indagini lo giustificano | Suite JS e Python; validazione del flusso completo dalla console |

Ogni traguardo modifica `src/` e quindi cambia l'impronta del motore. È atteso: nel nuovo disegno l'impronta identifica le misure, ma non obbliga più a ricalibrare.

## 6. Rischi e punti aperti

- **Concorrenza TeraFlow (lavoro D, punto 6):** non è noto se il servizio Device di Release 7 regge le aggiunte in parallelo. Resta sperimentale finché non è misurato.
- **Programma P4 (lavoro D, punto 7):** l'ipotesi va verificata nel codice del driver prima di qualsiasi modifica.
- **Formati salvati:** i risultati storici (`results/continuous-comparisons/`, `results/runs/`, `results/calibration.json`) devono restare leggibili.
- **Poche repliche:** con 3 eventi le differenze Cold−Hot si possono riportare per evento, ma senza un'incertezza statistica solida. Se servisse, si aggiungono eventi senza cambiare il codice.
- **Orbita che scorre:** Cold dura di più e quindi incontra più cambi di topologia di Hot. È realistico e fa parte del risultato, ma va dichiarato quando si confrontano le durate.
- **Rete ridotta e confrontabilità:** i nuovi tempi non sono confrontabili con quelli sulla rete a 64 dispositivi. La dimensione del dominio può diventare un fattore in un secondo momento.
- **Lock del laboratorio:** prima di qualsiasi prova live serve il recupero del job `job-72e466b1a7b24006a8939ba0b2b6166e`.

## 7. Avanzamento

### M1 — 7 novembre 2026

Fatto, tutto offline:

- `src/starlink_scenario.py`: selezione dei piani con SGP4 all'epoca di riferimento, regola dei 3 laser secondo per secondo (2 vicini nell'anello, 1 partner stabile sull'altro piano, allineamento di 60 s), indice dei percorsi multi-hop, periodi di luce, dominio, catalogo eventi.
- `tools/build_scenario.py`: scrive il profilo `artifacts/constellation-profiles/starlink-53-463-2x31/` con selezione, scenario derivato, replay, collegamenti, dominio, eventi e manifest con hash. Non tocca `config/`, `results/` né il laboratorio. Ricostruzione in circa un minuto con `--force`. La cartella `artifacts/` è esclusa da git, come per i profili precedenti.
- `src/orbit.py`: `generate` accetta scenario e selezione espliciti; il comportamento predefinito non cambia.
- API `GET /api/v1/scenario-profiles` e riquadro "Nuovo scenario a due piani" nella pagina Configurazione.
- Test: `tests/test_starlink_scenario.py`, `tests/test_scenario_profiles.py`. Suite completa: 280 test Python (9 saltati) e 33 JavaScript superati.

Risultati del profilo:

| Voce | Valore |
| --- | --- |
| Satelliti | 62 (31 + 31), RAAN 80,8° e 82,8°, quota circa 463 km, TLE con meno di 24 ore |
| Collegamenti laser | 62 nello stesso piano e 31 fra i piani, tutti attivi per l'intera giornata dopo l'allineamento iniziale |
| Dominio | Piano 1: 60138, 60142, 68285, 58890, 60144, 68283, 60141, 60150. Piano 2: 62760, 62768, 62776, 58893, 58883, 62774, 62775, 58886. Connesso internamente per il 99,9% del tempo (escluso l'allineamento iniziale) |
| Eventi | 240 (uno per ogni ingresso in ombra di un satellite del dominio), tutti con destinazione, tutti a 5 salti |
| Eventi scelti | 60150 → 68285 alle 00:25:57, 58883 → 62777 alle 11:32:42, 62760 → 58878 alle 22:42:08 |

Cosa insegnano questi numeri:

- **La topologia laser è statica.** Con piani a 2° e satelliti alla stessa quota, ogni satellite tiene gli stessi partner tutto il giorno. Una coppia alternativa (RAAN 26,9° e 31,0°, piani a 4°) ha dato 22 cambi di topologia, dovuti a piccole differenze di quota, e 11 satelliti senza partner sull'altro piano. È il comportamento atteso in un guscio ordinato. Con l'orbita che scorre (D11) il vincolo che cambia nel tempo resta l'ombra; percorsi e partner restano stabili.
- **Tutti gli eventi sono geometricamente equivalenti.** La situazione si ripete a ogni orbita: per raggiungere un satellite con almeno 30 minuti di luce servono sempre 5 salti. Il numero di salti dipende dai parametri (avviso 15 min prima dell'ombra, almeno 30 min di luce alla destinazione), non dall'evento. I 3 eventi scelti sono quindi repliche dello stesso caso in tre momenti della giornata.
- Nel laboratorio il numero di salti non cambia la misura, perché il trasferimento non attraversa Mininet. Cambia la fattibilità e la distanza del controller dagli switch.

Da fare in M2:

- Recuperare il laboratorio, poi installare il profilo in `config/` con archivio della configurazione attuale, come fa già `src/constellation.py`.
- Separare costellazione e dominio nel laboratorio: oggi fixture, Mininet, preflight e servizio assumono un dispositivo per ogni satellite dell'orbita, e gli estremi del servizio sono fissati su due NORAD (`src/fixture.py` HOSTS, `src/planner.py`).
- Scegliere gli estremi del servizio dentro il dominio.
- Vista orbitale della console sul nuovo profilo.

Conseguenza da tenere presente: le modifiche a `src/` cambiano l'impronta del motore, quindi il vecchio confronto guidato chiederebbe una nuova calibrazione. È coerente con D13 e D14.

### M2 — 7 novembre 2026

Fatto:

- Laboratorio recuperato (`job-56cd8a1ffcd043dc9fd08afa33942735`), lock rilasciato.
- Separazione fra costellazione e dominio. `src/orbit.py`: `load_orbit` usa i collegamenti laser registrati quando lo scenario li prevede; `lab_graph` restringe la topologia al dominio emulato; `migration_link` e `migration_path` valutano il percorso multi-hop sull'intera costellazione. Senza profilo laser il comportamento resta quello di prima.
- `src/fixture.py`: con `config/domain.json` la fixture contiene solo i satelliti del dominio, e gli estremi del servizio vengono dal dominio. `src/live_backend.py`, `src/experiment.py`, `src/web.py` e `tools/live_preflight.py` usano grafo del laboratorio, estremi della fixture e collegamento multi-hop. `functional` usa il primo evento del catalogo.
- `tools/install_scenario.py`: archivia la configurazione precedente in `artifacts/constellation-profiles/starlink-53-463-2x31/original/`, così gli esperimenti storici a 64 satelliti mantengono la loro geometria, e installa il profilo. Opzioni `--resume` (installazione interrotta) e `--refresh` (profilo ricostruito).
- Correzione del modello: i laser già attivi al primo secondo del replay sono considerati allineati; solo i collegamenti che si formano dopo pagano i 60 s.
- Installazione: dominio di 16 satelliti e 22 collegamenti. Mininet e proxy P4 riavviati: 16 switch attivi.
- Console: vista orbitale con 62 satelliti, dominio evidenziato, 93 collegamenti laser e percorso del servizio. Il vecchio confronto continuo è disattivato con una spiegazione (D13), finché il nuovo esperimento arriva in M4.
- Su Windows `config/fixture.json` non si può sostituire mentre Mininet e proxy P4 lo tengono aperto: vanno fermati prima di installare una fixture diversa.
- Test: `tests/test_domain_split.py`, test di allineamento aggiornati; suite completa superata prima e dopo l'installazione.

Problemi incontrati nella verifica live e soluzioni:

1. **Vecchio inventario nei database TeraFlow.** Il servizio Device ricaricava all'avvio i 64 dispositivi del vecchio scenario e si chiudeva, perché il proxy serve solo i 16 switch del dominio. Soluzione, autorizzata: rimozione mirata, tramite il servizio Context, di servizi, connessioni, collegamenti `isl-*`, dispositivi `sat-*`, topologia e contesto `migration-lab` su SAT-A e SAT-B (64 dispositivi, 214 e 216 collegamenti). Il contesto `admin` è stato lasciato. **Da ricordare per ogni futuro cambio di dominio.**
2. **Nome della topologia.** L'adattatore ammetteva solo `starlink-<satelliti della costellazione>`; ora ammette anche il nome della fixture installata (`starlink-16`) (`src/tfs_adapter.py`).
3. **Percorso di TeraFlow diverso da quello delle regole di inoltro.** Fra i due piani il dominio è una "scala" con molti percorsi di pari lunghezza. TeraFlow ne sceglie uno con un criterio interno, mentre le regole della fixture seguono la distanza: i pacchetti finivano su uno switch senza regole (perdita del 100%). Soluzione: estremi del servizio sui due capi dell'arco del piano 1 (60138 → 60150, 7 salti), dove il percorso minimo è unico. L'installazione ora rifiuta estremi con percorso minimo assente, non unico o diverso da quello per distanza (`tools/install_scenario.py`). La migrazione del controller continua ad attraversare i due piani.

Esito della verifica funzionale (`job-5761c2d39e6746cbb810df31c16c76c4`, confronto `compare-148080b3273243bd9ae5eac895d55526`, evento 60150 → 68285, 5 salti, 1 Gbit/s), riuscita per entrambe le modalità con baseline valida e servizio verificato:

| Misura | Hot | Cold | Cold−Hot | Rete a 64 dispositivi (4/11): Hot / Cold |
| --- | ---: | ---: | ---: | ---: |
| Downtime del controller | 32,7 s | 283,8 s | 251,1 s | 219 s / 1.032 s |
| Durata dell'operazione | 296,2 s | 346,3 s | 50,1 s | 1.208 s / 1.119 s |
| Ripristino dei ping | 22,2 s | 23,3 s | 1,1 s | — |

Una sola replica per modalità, in ordine Hot → Cold; le misure includono ancora il trasferimento del bundle di immagini e gli effetti del laboratorio che il lavoro D toglierà (caricamento immagini, pulizia della destinazione). La durata complessiva del job è stata di 18 minuti. Suite locale: 290 test Python (9 saltati) e 33 JavaScript superati.

### M3 — 7 novembre 2026

Fatto (lavoro D, punti 1–5):

1. **Software a bordo (D10).** Con `migration.software_on_board` lo scenario non trasferisce più il bundle di immagini e la destinazione non esegue `docker load`. L'impronta del bundle verificato sull'host si calcola prima del trigger e diventa la ricevuta della destinazione, così la verifica degli input resta (`src/orchestrator.py`, `src/live_backend.py`). Il trasferimento resta disponibile disattivando l'opzione.
2. **Destinazione pulita per costruzione.** Con `migration.clean_target_store_before_trigger` la preparazione svuota il database Context della destinazione dai residui delle prove precedenti, nella fase di budget `clean_target` (`tools/tfs_context_cleanup.py`, eseguito nel container Context). Il report è salvato in `target-store-cleanup.json` della prova. La pulizia misurata del perimetro verifica soltanto una destinazione vuota (circa 2 s).
3. **Regole solo sul percorso del servizio.** Le fixture con dominio descrivono nel servizio solo gli switch del percorso (`forwarding: service-path-only` in `src/fixture.py`). Prima, gli switch fuori percorso cambiavano il prossimo salto con il movimento dei satelliti; ogni cambio ricreava il servizio (riconciliazioni accodate di 23 + 30 s in Cold) e interrompeva il traffico. TeraFlow programma comunque solo gli switch del percorso.
4. **Orbita che scorre e percorso multi-hop.** Il clock scorre durante la misura; il trasferimento usa il percorso multi-hop (`migration_link`). Con la topologia statica non ci sono state riconciliazioni accodate.
5. **Una sola velocità.** Lo scenario installato ammette solo 1 Gbit/s. Il selettore della velocità resta solo nel vecchio percorso, disattivato; la nuova console arriva in M4.

Misura (`job-d2c6428ee906438fb88aef9bea3b0c99`, confronto `compare-4e25327319944c39a32c4b7afe277c5b`, stesso evento di M2, una replica per modalità, ordine Hot → Cold):

| Misura | Hot M2 | Hot M3 | Cold M2 | Cold M3 |
| --- | ---: | ---: | ---: | ---: |
| Downtime del controller | 32,7 s | **20,6 s** | 283,8 s | **123,7 s** |
| Durata dell'operazione | 296,2 s | **192,8 s** | 346,3 s | **186,7 s** |
| Ping persi | 570 su 3.364 | **0 su 2.274** | 213 su 3.938 | **0 su 2.211** |

Fasi M3. Hot: avvio controller 66,1 s, ripristino API 42,2 s, snapshot finale 14,3 s, delta 1,4 s, verifica 3,6 s, cutover 0,5 s. Cold: arresto sorgente 22,0 s, avvio controller 59,4 s, ripristino API 37,5 s, verifica 1,7 s, cutover 0,3 s.

Lettura: Cold−Hot sul downtime è 103,1 s. In entrambe le modalità il piano dati non si è mai interrotto: le regole P4 restano negli switch mentre il controller migra, quindi il "tempo di ripristino dei ping" non è definito (nessuna perdita, non una misura mancante). Nel Cold il downtime è dominato da avvio del controller (circa 60 s) e ripristino API (circa 38 s). La durata totale di Hot e Cold è ora simile, perché in Hot avvio e ripristino avvengono prima del freeze.

Restano per M5 i punti 6 e 7 del lavoro D (aggiunta in parallelo dei dispositivi, programma P4 alla riconnessione).

### M4 — 7 novembre 2026

Esperimento a eventi completo (`job-7c13b869165841e1860449b882994e17`, confronto `events-b9eb7fc7eb8c42a7a212922de096405c`): 3 eventi, Hot e Cold su ciascuno, ordine alternato, 1 Gbit/s, software a bordo. Tutte e 6 le migrazioni riuscite con baseline valida e servizio verificato. Durata complessiva del job: **40,6 minuti**.

| Evento | Modalità | Downtime | Durata dell'operazione | Ping persi | Entro l'ombra | Preparazione | Prova completa |
| --- | --- | ---: | ---: | ---: | --- | ---: | ---: |
| 1 (60150 → 68285, 5 salti) | Hot | 6,3 s | 172,2 s | 0 su 2.059 | sì | 221 s | 433 s |
| 1 | Cold | 125,2 s | 186,8 s | 0 su 2.204 | sì | 150 s | 377 s |
| 2 (58883 → 62777, 5 salti) | Cold | 126,5 s | 189,4 s | 0 su 2.227 | sì | 217 s | 446 s |
| 2 | Hot | 6,6 s | 172,6 s | 0 su 2.061 | sì | 211 s | 423 s |
| 3 (62760 → 58878, 5 salti) | Hot | 6,7 s | 178,9 s | 0 su 2.126 | sì | 149 s | 367 s |
| 3 | Cold | 122,2 s | 184,3 s | 0 su 2.190 | sì | 148 s | 374 s |

Cold − Hot sul downtime: 118,9 s, 119,9 s e 115,5 s; sulla durata: 14,6 s, 16,9 s e 5,5 s. "Preparazione" va dall'inizio della prova al trigger (stack, pulizia della destinazione, rete del dominio, baseline); "prova completa" include anche migrazione, osservazione e messa in sicurezza. Il downtime Hot è sceso a circa 6 s rispetto ai 20,6 s di M3: il delta finale ora è piccolo (circa 3 s di applicazione) perché il servizio non viene più ricreato.

### Pulizia del vecchio esperimento — 7 novembre 2026

Su richiesta, rimosso tutto ciò che apparteneva al vecchio confronto continuo e agli strumenti collegati (commit separato dopo `f506552`):

- 21 moduli `src/` (pianificazione, confronto continuo, simulazione continua, base comune, calibrazione, campagne, sensitivity, diagnostica delle risorse, report, modelli di risorse e punteggio, eventi e selezione storici, stato della vecchia topologia), 7 strumenti, 20 file di test, 13 documenti.
- `experiment.py`, `jobs.py`, `progress.py` e la CLI ridotti alle operazioni `functional`, `compare_events`, `recover`, `environment`. `live_backend.py`, `orchestrator.py`, `orbit.py` e `fixture.py` senza i percorsi del vecchio flusso (riuso incrementale per la calibrazione, collettore delle risorse, sessioni continue, carico aggiuntivo, modello di contatto per distanza).
- Console riscritta con tre pagine (Scenario, Esperimento, Risultati) e API ridotte; restano sessione, controlli same-origin, SSE e registro dei download.
- I file di risultati storici restano su disco in `results/`; la console non li mostra più.
- Suite locale: 142 test Python (9 saltati) in 13 s e 8 test JavaScript.
- Verifica live sul codice ripulito, avviata dalla console (`job-f04bd2ddf6a443a5a64c0b1ccaea6639`): riuscita in **13,6 minuti**. Hot 5,3 s di downtime e 167,9 s di durata; Cold 117,0 s e 178,6 s; Cold − Hot 111,7 s. Preparazione 224 s e 161 s, prove complete 432 s e 378 s.

### Eventi diversi, repliche e ritardo di propagazione — 8 novembre 2026

- **Eventi.** Nella costellazione il numero di salti e la luce della destinazione vanno insieme: ogni salto verso i satelliti che seguono sull'orbita dà circa 3 minuti di luce, e la regola «almeno 30 minuti» imponeva 5 salti a tutti gli eventi. Il catalogo ha ora 5 eventi, uno per combinazione: 1 salto sullo stesso piano, 1 salto verso l'altro piano, 3, 5 e 7 salti (l'ultimo verso l'altro piano), distribuiti nel giorno, con destinazione al sole per almeno 10 minuti e percorso stabile per 15 (`designed_events`). La vecchia scelta per quantili è stata rimossa.
- **Esperimento.** Hot e Cold di un evento restano sullo stesso percorso e sullo stesso istante orbitale. Un riscaldamento escluso, poi 5 repliche eseguite una dopo l'altra su tutti gli eventi; in ogni coppia l'ordine Hot/Cold è estratto con un seme registrato. Per evento: mediana e quartili, Cold − Hot appaiato con intervallo bootstrap al 95 % (schema dei risultati 2). Una prova non riuscita resta mancante; l'esperimento si ferma se serve il ripristino o dopo 3 prove non riuscite di fila. 51 prove, circa 5 ore e mezza.
- **Ritardo di propagazione.** Ogni collegamento laser ha il ritardo della sua lunghezza: `tc netem delay` sui collegamenti di Mininet, aggiornato con la geometria; per il trasferimento dello stato, che avviene sull'host, un modello TCP (handshake, slow start, conferma finale) sul ritardo dell'intero percorso multi-hop.
- **Ipotesi dell'allineamento.** I 60 s di contatto continuo sul percorso prima di ogni tentativo restano, dichiarati come ipotesi nello scenario e nella documentazione.
- Le misure aggiuntive proposte (sonda esterna del downtime, carico della macchina, margine rispetto all'ombra) sono state escluse.
- **Combinazione 12 (stesso giorno).** Per contenere la durata (51 prove, quasi 6 ore) l'esperimento usa 3 eventi e 3 repliche: 1 salto sullo stesso piano (62760 → 62777), 5 salti sullo stesso piano (60142 → 60146), 7 salti verso l'altro piano (62776 → 60146). Ogni evento ha sorgente e fascia del giorno fissate in `EVENT_SPECS`, così il catalogo riproduce esattamente questi tre. 19 prove, circa 2 ore.
