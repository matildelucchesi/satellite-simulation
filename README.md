# Satellite Network Simulation

Scaffold iniziale per una simulazione modulare di una costellazione di cinque
satelliti ispirata a Starlink. I componenti applicativi sono volutamente
limitati a un'app Flask e a un endpoint di health check: la logica di
simulazione verrà aggiunta in una fase successiva.

## Componenti

- `simulator`: coordinatore headless che propaga i TLE con Skyfield e conserva
  lo stato corrente della costellazione.
- `satellite_agent`: immagine riutilizzata per i cinque agenti satellitari.
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
- Dashboard: `http://localhost:8080/health`
- Satelliti SAT-1 ... SAT-5: porte `8101` ... `8105`, percorso `/health`

API di ogni Satellite Agent:

- `GET /status`: stato locale, Controller, sincronizzazione e heartbeat.
- `GET /position`: ultima posizione ricevuta dal Simulator.
- `POST /receive_state`: ricezione push dello stato orbitale.
- `POST /start_controller` e `POST /stop_controller`: ciclo di vita logico del Controller.
- `POST /migration_request`: accettazione di una migrazione del Controller.

API del Controller:

- `GET /heartbeat`: elenco degli heartbeat ricevuti; accetta `?id=SAT-1`.
- `POST /heartbeat`: ricezione degli heartbeat dai Satellite Agent.
- `GET /state`: topologia, routing table, heartbeat e versione dello stato.
- `POST /checkpoint`: serializzazione e salvataggio atomico dello stato.
- `POST /restore`: ripristino dal JSON inviato o dall'ultimo file salvato.
- `POST /shutdown`: checkpoint e disattivazione logica del Controller.

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
tre righe e un totale esatto di cinque satelliti.

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
