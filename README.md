# TeraFlowSDN — laboratorio di migrazioni satellitari

Il programma confronta la migrazione **Hot e Cold** del controller TeraFlowSDN sullo stesso piano orbitale. Il progetto applicativo si trova in [`teraflow-migration-sim/`](teraflow-migration-sim/). La console locale è sulla porta **18092**.

## 1. Prerequisiti

Per il percorso Windows descritto qui servono:

- **Python 3.13** (versione usata nel progetto) e PowerShell.
- **Docker Desktop avviato con engine Linux** e Docker Compose disponibile.
- La copia completa del laboratorio: configurazioni, immagini Docker e artefatti congelati. Una sola copia del codice non contiene necessariamente gli archivi locali necessari; vedere il punto 3.
- Connessione Internet per installare le dipendenze e scaricare le immagini mancanti.

Durante la simulazione mantenere accesi PC, sessione Windows e Docker; evitare sospensione e riavvii. Le prove possono richiedere diverse ore, soprattutto al primo avvio con calibrazione.

Controllare gli strumenti in PowerShell:

```powershell
py -3.13 --version
docker version
docker compose version
```

`docker version` deve mostrare anche il server: un errore di connessione indica che il motore Docker non è disponibile.

## 2. Installare le dipendenze Python (solo la prima volta)

Aprire PowerShell e posizionarsi nella cartella applicativa. Nel percorso di questo workspace:

```powershell
cd C:\UNIFI-workspaces\satellite-simulation\teraflow-migration-sim
py -3.13 -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

Se il repository è stato copiato altrove, adattare soltanto il percorso del `cd`. Tutti i comandi successivi si eseguono da `teraflow-migration-sim`.

Non occorre attivare l'ambiente: i comandi usano direttamente il suo interprete. `requirements.txt` include anche le librerie per orbite e grafici del report. Negli avvii successivi riutilizzare `.venv`; dopo un aggiornamento delle dipendenze ripetere il comando di installazione.

## 3. Verificare che il laboratorio sia predisposto

Il comando di avvio usa `--no-build`: **non costruisce le immagini**. Prima devono essere disponibili le immagini TeraFlow con le patch previste, quelle del laboratorio Mininet/P4, i file P4 e il bundle di trasferimento referenziato dai manifest.

Verificare la configurazione e le immagini richieste:

```powershell
docker compose --env-file deploy/lab.env -p teraflow -f deploy/stack.yaml config --quiet
docker compose --env-file deploy/lab.env -p teraflow -f deploy/stack.yaml config --images
docker image ls
```

La configurazione richiede `deploy/lab.env` e `deploy/stack.yaml`. Conservare inoltre `config/scenario.json`, `config/fixture.json`, i manifest in `config/`, gli artefatti orbitali e gli archivi in `artifacts/` con i percorsi e checksum registrati. Non sostituire il bundle con un archivio generico: il motore verifica la provenienza degli input.

**Su una macchina nuova:** procurarsi gli artefatti congelati e importare le immagini dalla copia del laboratorio, oppure ricostruirli seguendo la [guida di deployment](teraflow-migration-sim/docs/teraflow-compose.md). `tools/build_tfs_images.py` costruisce le sei immagini upstream a partire dagli input già presenti in `.reference/` (`tfs-src.tar.gz`, `tfs-proto.tar.gz`, `common_requirements.in`, `common_requirements_py313.in`, `LICENSE`): non scarica quegli input e non prepara da solo le varianti Service/Device con patch e il bundle attualmente configurato. La sola build upstream non completa l'installazione live. Il repository non offre un unico comando per ricreare da zero tutti questi materiali.

Se immagini o archivi mancano, completare questa preparazione prima di proseguire. Per il laboratorio già predisposto non rigenerare fixture, costellazione o manifest a ogni avvio.

## 4. Avviare il laboratorio Docker

Con Docker Desktop pronto e nessuna prova in corso:

```powershell
.\.venv\Scripts\python.exe tools/stack.py up
.\.venv\Scripts\python.exe tools/stack.py status
```

`up` crea i volumi persistenti necessari e avvia il gruppo Compose **teraflow**, comprendente SAT-A, SAT-B e Mininet/P4. Attendere il completamento del comando e controllare lo stato dei container. Un'immagine mancante o un servizio non pronto va risolto prima di avviare la simulazione.

Le API NBI locali sono su `http://127.0.0.1:18080` (SAT-A) e `http://127.0.0.1:18081` (SAT-B). La sola risposta HTTP non certifica il corretto forwarding P4: il confronto verifica anche il servizio.

## 5. Avviare il programma e aprire la console

Nella stessa cartella eseguire:

```powershell
.\.venv\Scripts\python.exe tools/serve_gui.py
```

Lasciare aperto questo terminale e aprire nel browser **[http://127.0.0.1:18092/](http://127.0.0.1:18092/)**. Il server rimane in primo piano; usare un secondo PowerShell, sempre nella cartella applicativa, per eventuali altri comandi.

In alternativa, su Windows aprire `teraflow-migration-sim\tools\start_gui.cmd` da Esplora file. Il launcher richiede `.venv` già installato e avvia la console; il laboratorio Docker va avviato separatamente al punto 4.

## 6. Avviare la simulazione Hot/Cold

1. Attendere il caricamento della console e controllare **Requisiti del laboratorio**. È ammesso un solo job alla volta.
2. Scegliere **Velocità utile del canale**: 100 Mbit/s, 1 Gbit/s oppure 10 Gbit/s. Per la prima prova si può mantenere 1 Gbit/s.
3. Premere **Avvia confronto Hot/Cold**.
4. Seguire **Il tuo esperimento** e la **Timeline del confronto**. Se mancano calibrazioni compatibili, il programma esegue le verifiche funzionali e sei prove di calibrazione prima del confronto vero e proprio.
5. Attendere la selezione automatica di satellite e istante iniziali. Durante preparazione e calibrazione il clock orbitale è fermo: la mappa immobile è prevista. Se non viene trovato un piano ammissibile, leggere il motivo registrato.
6. Il programma esegue **Hot → Ripristino → Cold** sullo stesso piano. L'obiettivo attuale è **tre migrazioni verificate per Hot e tre per Cold**, senza durata prefissata. Non occorre scegliere manualmente satellite, partenza o durata.
7. Alla conclusione controllare **Risultati del confronto** ed **Evento per evento**, quindi aprire o scaricare i file da **Report e dati**.

Un processo terminato non garantisce un confronto riuscito: verificare l'esito delle due modalità e il numero di migrazioni riuscite. `—` indica una misura mancante. Il downtime del controller e il ripristino del forwarding sono misure distinte; Cold−Hot viene mostrato solo per eventi confrontabili.

La [guida al flusso guidato](teraflow-migration-sim/docs/guided-flow.md) descrive preparazione, attese e interpretazione dei risultati. Le vecchie istruzioni basate su durata manuale e velocità fissa descrivono una versione precedente della console.

### Alternativa da riga di comando

Con il laboratorio avviato, la stessa operazione si può lanciare senza browser:

```powershell
.\.venv\Scripts\python.exe tools/experiment.py compare_continuous --rate-bps 1000000000 --wait
```

Sostituire la velocità con `100000000` oppure `10000000000` per le altre opzioni. Non avviare contemporaneamente il confronto da GUI. Per questo comando la partenza è automatica e `--duration-s` non imposta la durata del confronto attuale. `--wait` segue il job fino all'esito.

## 7. Consultare i risultati

I percorsi seguenti sono relativi a `teraflow-migration-sim/`:

- `results/continuous-comparisons/pair-*/`: piano condiviso, risultati, CSV e report HTML del confronto.
- `results/simulations/sim-*/`: dettagli delle sessioni Hot e Cold.
- `results/runs/run-*/`: evidenze delle singole migrazioni.
- `results/jobs/job-*/`: stato persistente, eventi e log del worker.

La console consente anche di selezionare confronti precedenti in **Storico e replay**. I report e le evidenze parziali restano disponibili anche dopo un fallimento. Orbite e FSO sono modellati; TCP, API, autorità P4 e sonde sono verificati live.

## 8. Interrompere, recuperare e spegnere

Per fermare una prova usare **Interrompi** nella console e attendere la messa in sicurezza. Chiudere la scheda non ferma il worker. Per controllare o interrompere da un secondo terminale:

```powershell
.\.venv\Scripts\python.exe tools/experiment.py jobs
.\.venv\Scripts\python.exe tools/experiment.py stop --job-id job-IDENTIFICATIVO
```

Sostituire `job-IDENTIFICATIVO` con l'ID effettivo. Se compare **Ripristino necessario**, usare **Ripristina laboratorio** e attendere. Per un worker morto con lock ancora presente:

```powershell
.\.venv\Scripts\python.exe tools/experiment.py recover --wait
```

Non cancellare manualmente `results/jobs/lab.lock`. Il recupero conclude la prova interrotta; una nuova simulazione richiede un nuovo avvio.

Quando non ci sono job attivi o recuperi pendenti, fermare il server con **Ctrl+C** nel suo terminale e arrestare il laboratorio:

```powershell
.\.venv\Scripts\python.exe tools/stack.py stop
```

`tools/stack.py down` rimuove container e reti conservando i volumi persistenti; `stop` basta per lo spegnimento ordinario. Negli avvii successivi ripetere i punti **4, 5 e 6**.

## Problemi frequenti

- **Python o `.venv` non trovato:** verificare il percorso corrente e completare il punto 2.
- **Docker non raggiungibile:** avviare Docker Desktop, selezionare engine Linux e attendere che `docker version` mostri il server.
- **Immagine, bundle o file mancante / checksum errato:** ripristinare gli artefatti previsti dai manifest (punto 3); non aggirare i controlli modificando i checksum.
- **Porta 18092 occupata:** verificare se la console è già avviata; usare l'istanza esistente oppure arrestarla prima di riavviare il server.
- **Pulsante di avvio disabilitato o laboratorio occupato:** controllare stato, job attivo ed eventuale richiesta di recupero.
- **Preparazione ferma o fallita:** leggere sottofase, ultimo progresso, scadenza e log del job; non avviare altre operazioni Docker durante una prova.
- **Conflitto di subnet Docker:** vedere le variabili di rete in `deploy/lab.env` nella guida di deployment.

## Documentazione e verifiche locali

- [Guida al confronto guidato attuale](teraflow-migration-sim/docs/guided-flow.md)
- [Deployment e immagini Docker](teraflow-migration-sim/docs/teraflow-compose.md)
- [Guida operativa e strumenti CLI avanzati](teraflow-migration-sim/docs/operating-guide.md)
- [Descrizione tecnica](teraflow-migration-sim/README.md)
- [Stato di implementazione e limiti delle misure](teraflow-migration-sim/docs/implementation-status.md)

Per eseguire i test locali dalla cartella applicativa:

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

I test locali non certificano il completamento della campagna live. La vecchia dashboard sulla porta 8081 è stata rimossa; l'unico frontend è la console sulla porta 18092.
