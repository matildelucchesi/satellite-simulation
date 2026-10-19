# Simulazione continua TeraFlow

## Stato della consegna

Il 16 ottobre è stato validato il nuovo confronto funzionale FSO hot/cold dopo la correzione dei contatti Mininet: entrambe le migrazioni passano API e ping post-cutover. La validazione delle sessioni continue e della campagna estesa rimane separata e incompleta; il gate fallito del 15 ottobre riportato sotto è storico.

Il motore continuo, la pianificazione preventiva, gli slot intercambiabili, le API,
la console e i report sono implementati. La validazione live completa **non è
superata**: il gate del 15 ottobre 2026 ha rilevato assenza di ping riusciti e UDP
durante la preparazione. Il clock orbitale non è partito. Calibrazione definitiva,
tre passaggi consecutivi per modalità e campagna rimangono gate da superare;
le precedenti prove funzionali non li sostituiscono.

L'avvio senza le sei calibrazioni valide viene rifiutato prima di modificare
il laboratorio, salvando comunque una sessione e il suo report parziale.

## Cosa viene simulato e cosa viene misurato

I 17 NORAD del replay rimangono i nodi logici. Geometria orbitale, illuminazione,
contatti FSO, ranking e carichi sintetici sono modellati. I due ambienti Docker
`sat-a` e `sat-b` sono slot fisici riutilizzabili nel solo gruppo `teraflow`.
Snapshot, trasferimenti TCP, importazione immagini, API TeraFlow, regole P4,
ping, UDP e consumi dei due slot vengono misurati sul laboratorio.

Un NORAD non identifica un container. Dopo NORAD X/slot A → NORAD Y/slot B,
il passaggio successivo parte da B e può arrivare ad A con NORAD Z. Ogni
migrazione trasferisce e verifica nuovamente l'intero archivio delle immagini;
la cache del daemon Docker non vale come ricevuta del satellite logico.

Il clock live usa `time.monotonic()` a velocità reale e inizia solo dopo la
baseline. Non sono disponibili pausa o accelerazione live. Un crash richiede
recupero esplicito: revoca P4, arresto di entrambi i workload e chiusura della
sessione interrotta, senza ripresa del tempo perso.

## Avvio e interazione con il frontend

Dalla directory `teraflow-migration-sim`:

```powershell
.\.venv\Scripts\python.exe tools/stack.py up
.\.venv\Scripts\python.exe tools/serve_gui.py
```

Aprire http://127.0.0.1:18092/. L'operazione principale è **Simulazione continua**.
I valori iniziali sono hot, 1 Gbit/s e 3.600 secondi. Dalla console, inizio
orbitale e satellite iniziale vengono sempre scelti automaticamente: il
pianificatore cerca la prima finestra con una sequenza fattibile per la durata
richiesta e mostra la scelta nel piano della sessione. Il limite di migrazioni
vuoto significa nessun limite. Un limite esplicito termina la sessione al suo raggiungimento,
anche se rimane durata disponibile.

**Avvia simulazione** crea un job durevole. Un pannello sopra la mappa
evidenzia la fase corrente, la percentuale della
durata richiesta, i tempi trascorso e residuo, le migrazioni riuscite, il
controller e il prossimo passaggio. Gli aggiornamenti live arrivano dal motore;
se non ne arrivano per oltre dieci secondi, il pannello lo segnala senza far
avanzare artificialmente i tempi. Preparazione e replay storico sono indicati
separatamente. Il resto della console mostra pianificazione,
rifiuti, baseline, controller logico, slot Docker, tempo trascorso/residuo,
migrazioni completate e forwarding osservato. Geometria e forwarding sono
segnali distinti: avere un percorso non dimostra che i pacchetti passino.
I candidati sono evidenziati e i titoli dei nodi mostrano score o esclusioni.

**Interrompi** richiede la conclusione controllata. Chiudere il browser non
ferma il worker. Solo un job può detenere il laboratorio; dopo la perdita del
worker usare **Recupera job dopo crash**. A sessione conclusa, i workload senza
autorità sono mostrati come fermi; console, database, broker e Mininet restano
disponibili. Le prove singole e gli strumenti della campagna rimangono nella
sezione sperimentale del selettore Operazione.

Il selettore **Sessione continua** apre lo storico. Il cursore di replay appare
solo per sessioni concluse con osservazioni salvate e non controlla il clock live.
La timeline SSE si riconnette con il cursore dell'ultimo evento.

## Ammissione, risorse e sicurezza

Prima di qualsiasi modifica al laboratorio il pianificatore verifica l'intera
durata richiesta nel replay congelato. Usa contatti diretti, 60 secondi di
allineamento, tempi calibrati, riserva CPU/RAM/disco e margine di recupero.
Esplora i candidati nell'ordine dello score esistente; il backtracking scarta
anche candidati che porterebbero a un vicolo cieco successivo. Gli input
espliciti non vengono sostituiti. Dopo ogni passaggio ricalcola la sequenza
residua con il tempo realmente trascorso.

La politica `continuous-planned-v2` conserva il carico per NORAD e tempo
orbitale. La rampa 55→85% è riferita all'inizio dell'intervallo illuminato
indicizzato, con durata di due orizzonti calibrati. Per intervalli già illuminati
all'inizio del replay, il bordo osservato è il riferimento disponibile. Il carico
post-posizionamento è il massimo tra questa curva e il carico candidato di base
più il costo calibrato; i due contributi non vengono sommati due volte.

La preparazione ha un budget complessivo configurabile in
`config/scenario.json`, `live.preparation_timeout_s`, inizialmente 120 s.
Richiede switch e arbitraggio P4 coerenti, ripristino della topologia, API
disponibili e dieci risposte ping consecutive fresche. UDP è diagnostico e non blocca il gate.
Le sonde hanno directory univoche: risposte vecchie non soddisfano il gate.

Ogni migrazione ha al massimo tre tentativi e directory di ricezione separate.
Docker e trasferimenti sono vincolati alla deadline, mantenendo una riserva
per il rollback. Generazioni e revoca dell'ACK impediscono a un'operazione
amministrativa superata di recuperare l'autorità dopo il fencing.
Non vengono promessi downtime zero o disponibilità continua del percorso dati.

## CLI e API

```powershell
# Sessione automatica: hot, 1 Gbit/s, 3.600 secondi
.\.venv\Scripts\python.exe tools/experiment.py simulate --wait

# Parametri espliciti; gli esempi non garantiscono ammissibilità geometrica
.\.venv\Scripts\python.exe tools/experiment.py simulate --method cold --rate-bps 1000000000 --duration-s 3600 --start-orbital-s 4348 --initial-satellite-id 53848 --max-migrations 3 --wait

.\.venv\Scripts\python.exe tools/experiment.py stop --job-id job-IDENTIFICATIVO
.\.venv\Scripts\python.exe tools/experiment.py recover --wait
.\.venv\Scripts\python.exe tools/experiment.py complete --wait
```

Con `--wait`, un worker completato non basta per l'exit code 0: anche l'esito
applicativo deve essere positivo. Gate negativo, interruzione e recupero
necessario restituiscono un exit code non zero. Senza `--wait`, lo 0 conferma
solo l'accettazione del job.

| Interfaccia | Contenuto |
| --- | --- |
| `POST /api/v1/jobs` | `operation: "simulate"`, con `parameters` |
| `POST /api/v1/jobs/<job-id>/stop` | Richiesta di interruzione |
| `GET /api/v1/jobs/<job-id>/events` | Timeline SSE durevole |
| `GET /api/v1/simulations` | Sessioni e relativi esiti |
| `GET /api/v1/simulations/<sim-id>` | Configurazione e stato della sessione |
| `GET /api/v1/simulations/<sim-id>/observations` | Osservazioni, geometria, heartbeat, autorità, risorse ed eventi |
| `GET /api/v1/simulations/<sim-id>/topology?orbital_s=N` | Geometria e contesto del replay |
| `GET /api/v1/artifacts` | Artefatti scaricabili registrati |

I POST richiedono la sessione locale e il token CSRF. I parametri di simulazione
sono `method`, `rate_bps`, `duration_s`, `start_orbital_s`,
`initial_satellite_id`, `max_migrations`; gli ultimi tre accettano `null`.

## Struttura e lettura dei report

La generazione avviene automaticamente anche dopo rifiuto, errore o interruzione:

```text
results/simulations/sim-<uuid>/
  inputs.json                    parametri e scenario
  calibration.json               calibrazione usata, se ammessa
  artifact-manifest.json         manifest delle misure usate
  prepared-snapshot.json         topologia ripristinata prima del clock
  baseline.json                  gate del servizio
  plans/initial.json             intera sequenza iniziale
  plans/revision-*.json           ripianificazioni dopo i passaggi
  checkpoint.json                mapping e azione di recupero dopo crash
  metadata.json                   stato applicativo
  observations.jsonl             osservazioni e carichi dei 17 NORAD
  geometry.jsonl                 geometria e forwarding osservato
  heartbeat.jsonl, authority.jsonl
  resources.jsonl                misure fisiche dei due slot
  events.jsonl                   timeline della sessione
  migrations/migration-<uuid>/
    operation/                   snapshot, delta, fasi, checkpoint, risultato
    attempts/<n>/                ricevute e payload del singolo tentativo
  report.html                    documento leggibile
  report.json                    risultati, provenienza e limiti delle metriche
  migrations.csv                 esiti, slot, NORAD, tempi e margini
  observations.csv               avanzamento della sessione
  modeled-resources.csv          carichi modellati per NORAD
  physical-resources.csv         CPU/RAM misurate per slot
  downtime.svg                   downtime controller
  controller-history.svg         cronologia del posizionamento
```

Gli archivi immagini ricevuti vengono eliminati dopo l'uso per limitare il
consumo di disco; le ricevute con dimensione e checksum rimangono. I report
sono disponibili in **Artefatti e report**; aprendo `report.html` nella directory
salvata, i grafici SVG relativi vengono caricati insieme al documento.

Il downtime controller di una migrazione riuscita misura stop/freeze → cutover.
I recuperi dei tentativi falliti hanno tempi ed errori separati nella timeline
e nel campo `recoveries`. Per il servizio, prima perdita, prima risposta e
conferma di dieci risposte sono campi distinti: l'attesa della conferma non è
il downtime esatto. La perdita con percorso geometrico disponibile non prova
da sola che la migrazione ne sia la causa.

`null` e celle CSV vuote indicano valori mancanti. Origine misurata/modellata,
unità e politica sono registrate nel JSON. Le migrazioni continue non entrano
nelle 18 celle della campagna principale, che legge esclusivamente `results/runs`.
I risultati storici non vengono riscritti per uniformarli alle nuove evidenze.

## Ordine dei gate

`complete` esegue hot/cold funzionali con baseline, sei calibrazioni, validazione
continua con tre passaggi per modalità, capacità del laboratorio, selezione e
congelamento, guasti, campagna, ranking, sensibilità e report. Al primo gate
negativo conserva le evidenze, genera il report parziale e si ferma. La selezione
non congela una campagna prima della validazione continua; i checksum congelati
invalidano la campagna se il codice o gli input vengono modificati.
