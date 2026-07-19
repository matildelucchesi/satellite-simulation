# Satellite Network Simulation

Simulazione modulare di una costellazione di sette satelliti ispirata a
Starlink, con propagazione orbitale, agenti indipendenti, elezione e migrazione
del Controller, metriche e dashboard in tempo reale.

## Componenti

- `simulator`: coordinatore headless che propaga i TLE con Skyfield e conserva
  lo stato corrente della costellazione.
- `satellite_agent`: immagine riutilizzata per i sette agenti satellitari.
- `controller`: microservizio Controller associato logicamente a `SAT-1`.
- `dashboard`: base per la futura interfaccia di monitoraggio.
- `common`: configurazioni e utilità condivise tra i servizi.
- `config`: configurazione JSON della costellazione.
- `logs`: destinazione locale dei log generati dai container.

## Avvio

```bash
docker compose up --build
```

Endpoint iniziali:

- Simulator: `http://localhost:8000/health`
- Stato costellazione: `http://localhost:8000/api/v1/constellation`
- Elenco satelliti: `http://localhost:8000/api/v1/satellites`
- Singolo satellite: `http://localhost:8000/api/v1/satellites/SAT-1`
- Score globali: `http://localhost:8000/api/v1/scores`
- Heartbeat ricevuti: `http://localhost:8000/api/v1/heartbeats`
- Migrazioni raccomandate: `http://localhost:8000/api/v1/migrations`
- Controller: `http://localhost:8001/health`
- Dashboard: `http://localhost:8081/health`
- Interfaccia Dashboard: `http://localhost:8081/`
- Satelliti SAT-1 ... SAT-7: porte `8101` ... `8107`, percorso `/health`

API di ogni Satellite Agent:

- `GET /status`: stato locale, Controller, sincronizzazione e heartbeat.
- `GET /position`: ultima posizione ricevuta dal Simulator.
- `POST /receive_state`: ricezione push dello stato orbitale.
- `POST /start_controller` e `POST /stop_controller`: ciclo di vita logico del Controller.
- `POST /migration_request`: accettazione di una migrazione del Controller.
- `POST /receive_controller_state`: ricezione del final state e ACK `200` della
  Hot Migration.

API del Controller:

- `GET /heartbeat`: elenco degli heartbeat ricevuti; accetta `?id=SAT-1`.
- `POST /heartbeat`: ricezione degli heartbeat dai Satellite Agent.
- `GET /state`: topologia, routing table, heartbeat e versione dello stato.
- `POST /checkpoint`: serializzazione e salvataggio atomico dello stato.
- `POST /restore`: ripristino dal JSON inviato o dall'ultimo file salvato.
- `POST /shutdown`: checkpoint e disattivazione logica del Controller.
- `POST /quiesce` e `POST /resume`: freeze temporaneo delle mutazioni durante
  il cutover Hot e ripresa in caso di rollback.

Per arrestare lo stack:

```bash
docker compose down
```

## Stato prodotto dal Simulator

Il Simulator aggiorna ogni secondo uno snapshot JSON in memoria. Ogni satellite
espone posizione e velocita nel riferimento inerziale GCRS, coordinate
geodetiche WGS84, velocita scalare, stato `sunlight`/`shadow`, tempo alla
prossima entrata in ombra e distanza da tutti gli altri satelliti. Il file TLE
locale e `config/starlink.tle`; puo essere sostituito mantenendo il formato a
tre righe e un numero di satelliti coerente con `satellite_count` in
`config/constellation.json`.
La selezione predefinita usa sette Starlink del guscio a circa 53 gradi con
piani orbitali e fasi differenti. I due satelliti aggiunti occupano gli
intervalli più ampi tra quelli originali, così le posizioni proiettate restano
ben distribuite lungo l'orbita.

Ogni Satellite Agent recupera inoltre il proprio stato dal Simulator ogni
secondo e invia un heartbeat periodico al `score_manager` del Simulator;
eventuali errori di consegna restano visibili in `GET /status` senza
interrompere l'agente. I pesi `w1`...`w4`, il TTL degli heartbeat e le soglie di
migrazione sono configurabili in `config/scoring.json`.

Il `migration_manager` esegue in modo asincrono una migrazione alla volta. Il
protocollo, gli URL REST, timeout e retry sono configurabili in
`config/migration.json`. `POST /api/v1/migrations` permette inoltre di avviare
manualmente una migrazione `cold` o `hot`; `GET /api/v1/migrations/<id>` espone
stato, ACK, tempi, downtime, byte trasferiti, retry e risultato del rollback.
Prima di entrare nella coda di esecuzione, ogni migrazione resta nello stato
`waiting_for_contact`: sorgente e destinazione devono mantenere per 60 secondi
consecutivi una distanza non superiore a 5.500 km e linea di vista libera dalla
Terra. Un'interruzione del contatto o un intervallo eccessivo fra gli snapshot
azzera l'allineamento. Durata, distanza, causa dell'attesa e numero di reset
sono esposti nel campo `contact_window` della migrazione; soglie e durata sono
configurabili in `config/migration.json`.
La Hot Migration usa una pre-copy iniziale, mette brevemente il source in
quiescenza, acquisisce un secondo checkpoint con gli aggiornamenti intervenuti,
attende l'ACK `200` del target sul final sequence number e solo allora esegue
stop del source e attivazione definitiva del target.
La Cold Migration mette subito il source in quiescenza, lo arresta, acquisisce
il checkpoint definitivo, attende lo stesso ACK `200` dal target e soltanto
dopo esegue restore e attivazione. In caso di errore il checkpoint viene
ripristinato e il source viene riavviato.

La Dashboard Flask aggrega Simulator e Controller tramite `/api/dashboard` e
aggiorna ogni secondo una rete SVG, tabella satelliti, routing table, heartbeat,
score, luce/ombra, migrazioni e stream degli eventi. Accanto alla rete mostra
per ogni satellite il conto alla rovescia e l'orario della prossima transizione;
source e target delle migrazioni del Controller sono evidenziati anche nel
grafo. Sotto la rete, una timeline mostra gli istanti assoluti e relativi di
selezione, allineamento, checkpoint, trasferimento, ACK, cutover ed eventuale
rollback fino al completamento. Non usa CDN o librerie frontend esterne ed è
quindi disponibile anche senza accesso Internet.

Il modulo Metrics del Simulator registra automaticamente heartbeat ed elezioni
del Controller e aggrega numero di migrazioni, ACK, downtime e durata degli
handover. `GET /api/v1/metrics` restituisce lo snapshot JSON corrente. Gli
endpoint `/api/v1/metrics/export.json` e `/api/v1/metrics/export.csv` scaricano
lo stesso snapshot nei due formati; il tempo totale viene calcolato dall'avvio
del processo Simulator.

## Architettura dei moduli

Ogni container usa una composition root in `app/__init__.py`: qui vengono lette
le impostazioni, costruiti i servizi e iniettate le dipendenze. Le route Flask
sono isolate in `app/routes.py` e traducono soltanto HTTP/JSON verso i casi
d'uso. La logica applicativa resta nei moduli `service`, `agent`,
`score_manager`, `migration_manager`, `metrics` e `orbit_engine`.

Le dipendenze infrastrutturali sono dietro porte esplicite: il Satellite Agent
usa `AgentHttpTransport`, mentre il Controller usa `CheckpointRepository`.
Gli adapter correnti sono basati sulla standard library (`urllib` e filesystem)
e possono essere sostituiti nei test o da implementazioni future senza cambiare
la logica applicativa. La configurazione della costellazione è gestita dal
modulo dedicato `simulator/app/configuration.py`.
