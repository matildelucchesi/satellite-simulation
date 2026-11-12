# Piano: politica di destinazione e forwarding dai percorsi di TeraFlow

Branch: `forwarding-path-selection`. Stato: passi 1, 2 e 4 completati (12 novembre 2026); passo 4 da verificare nel laboratorio; passi 3, 5 e 6 da implementare.

## Obiettivo

Aggiungere all'esperimento una seconda politica di scelta della destinazione del controller, basata sul costo, accanto agli eventi progettati (1, 5, 7 salti). La politica si sceglie dalla console prima dell'avvio. Ogni evento, con qualsiasi politica, si esegue sia in Hot sia in Cold sulla stessa destinazione, così le due modalità restano confrontabili a coppie. Le regole di inoltro del servizio di prova seguono il percorso calcolato da TeraFlow invece di un percorso imposto.

## Decisioni prese

| Punto | Decisione |
| --- | --- |
| Peso `k` arbitrario | Niente somma pesata. Vincolo di disponibilità (quota di downtime sotto una soglia), poi latenza di controllo minima fra le destinazioni ammesse. Analisi di sensibilità sulla soglia. |
| Downtime fisso a 7 s | Downtime misurato per modalità, letto da un esperimento completato e registrato con la sua provenienza. Un valore per modalità: le misure non dipendono dai salti (Hot 5,8–8,5 s, Cold 129–134 s, `events-f77d737a…`). |
| Latenza solo propagazione | Propagazione dal modello più un termine misurato costante (tempo di risposta del controller). Il termine non cambia la classifica; si riporta per avere un costo assoluto realistico. |
| Percorso diverso da TeraFlow | Le regole di inoltro si ricavano dal percorso che TeraFlow ha davvero calcolato (connessione del servizio). |
| Politica | Aggiuntiva: gli eventi progettati restano. Una select nella console sceglie la politica dell'esperimento. |
| Hot e Cold | Per ogni evento entrambe le modalità, sulla stessa sorgente, destinazione e istante orbitale (come oggi). |
| Selezione | Downtime Hot, soglia 95 %. |
| Permanenza | Dalla fine della migrazione più lunga (Cold, 194 s di mediana) al trigger della destinazione. |
| Ingresso non servito | Sostituito dall'ingresso servito più vicino nel tempo; gli eventi progettati restano invariati. |

## Casualità nella scelta dei percorsi di TeraFlow

Verificato nelle immagini del laboratorio (`pathcomp-frontend`, `service:…-lab3`):

- Alla creazione del servizio, Service chiede a PathComp l'algoritmo `shortest_path`.
- Il frontend assegna a ogni collegamento costo 1 e latenza 1 (`compose_link`), ignorando gli attributi del collegamento. Il percorso scelto è quindi quello con meno salti.
- Non c'è casualità: a parità di salti decide il backend con un criterio interno e deterministico, che dipende dall'ordine in cui riceve dispositivi e collegamenti dal Context. Il codice del backend non l'ho letto (nell'immagine c'è solo il binario), quindi questo criterio non è documentato.
- Conseguenza pratica: stessa topologia e stesso ordine danno lo stesso percorso, ma niente garantisce che SAT-A e SAT-B, o due installazioni diverse, scelgano lo stesso percorso fra quelli equivalenti. Per questo il piano non prevede il percorso: lo legge dopo la creazione, lo registra per ogni prova e lo confronta fra sorgente e destinazione.
- Il costo non è configurabile senza modificare PathComp. Le immagini sono congelate, quindi resta fuori dal piano.

## Come TeraFlow programma oggi l'inoltro

Il gestore `p4_fabric_tna_l2_simple` (con la patch del laboratorio) riceve gli endpoint della connessione calcolata da TeraFlow. Su ogni porta di quella connessione installa le voci di `fwd_list` (MAC dell'host → porta) che indicano proprio quella porta. TeraFlow decide quindi quali switch e porte programmare; `fwd_list` decide quali MAC vanno su ciascuna porta. Se le due scelte non coincidono, la porta del percorso di TeraFlow resta senza voci e i pacchetti cadono (perdita del 100 % già osservata, `piano-riprogettazione-simulatore.md` punto 3). Oggi la coincidenza è garantita solo dal percorso minimo unico fra gli estremi del servizio.

## Lavoro

### 1. Politica rivista (`src/starlink_scenario.py`) — fatto

- `DESTINATION_POLICY`: `availability_min` 0,95, `selection_mode` `hot`, `downtime_s` e `duration_s` per modalità, `overhead_ms` (0 finché il termine misurato non c'è) e la provenienza delle misure.
- `destination_candidates`: vincoli di prima (dominio, luce, persistenza del percorso, raggiungibilità del dominio) più uno: il trigger della destinazione deve arrivare dopo la fine della migrazione. La permanenza (`stay_s`) va dalla fine della migrazione più lunga al trigger della destinazione; `stay_from_trigger_s` conserva quella dal trigger. Ammessa se `downtime / permanenza ≤ 1 − availability_min` per la modalità di selezione. Ordine: latenza crescente, poi salti, poi id NORAD. Il costo pesato è stato rimosso.
- Selezione con il downtime Hot. Con il downtime Cold (131,4 s) nessuna destinazione del dominio resta abbastanza: la permanenza massima è circa 1.290 s, quindi nessuna soglia sopra il 90 % ammette destinazioni. Hot e Cold dello stesso evento usano comunque la stessa destinazione; il resoconto riporta per entrambe le modalità la quota di downtime sulla permanenza.
- `policy_sensitivity`: per una griglia di soglie, ingressi in ombra serviti, salti, permanenza e latenza medi.
- `compare_with_policy` segna per ogni evento progettato se è fattibile (`feasible`) e se rispetta la soglia (`admissible`).

Risultati sul profilo installato (downtime e durate da `events-f77d737a…`: Hot 6,7 s e 178,9 s, Cold 131,4 s e 194,1 s, 9 prove per modalità):

- La politica serve 180 dei 240 ingressi in ombra, con 2–4 salti. I 60 non serviti sono dei 4 satelliti all'estremo del dominio (60138, 60142, 62760, 62768): davanti a loro nel dominio nessuna destinazione resta al sole abbastanza. Succede a ogni orbita. È un limite del dominio di 16 satelliti: un sistema reale migrerebbe fuori dal dominio o lo sposterebbe con la costellazione.
- Il primo evento progettato (62768 → 62760, 182 s dal trigger) non è fattibile con la permanenza dalla fine della migrazione: il trigger della destinazione arriva prima che la migrazione finisca. Resta nel catalogo progettato perché è già misurato; lo si dichiara come limite. Gli altri due eventi progettati sono fattibili.

### 2. Catalogo con gli eventi della politica — fatto

- `tools/destination_policy.py --downtime-from events-…` legge il profilo senza rifare la propagazione SGP4, prende le mediane di downtime e durata dall'esperimento e scrive in `events.json` del profilo `destination_policy` (parametri, scelte, sensibilità, confronto) e `policy_selected`. Aggiorna l'hash nel manifest. `build_scenario.py` usa le stesse funzioni.
- `policy_selected`: per ognuno dei 3 eventi progettati, la destinazione della politica sullo stesso ingresso in ombra della stessa sorgente. Un ingresso che la politica non può servire è sostituito dall'ingresso servito più vicino nel tempo, non già usato; l'evento registra `replaces_designed_entry` e il motivo.
- Eventi installati:

| Evento progettato | Evento della politica | Destinazione | Salti | Permanenza |
| --- | --- | --- | --- | --- |
| 62768-8295 | 62776-8114 (sostituto) | 60138, altro piano | 3 | 159 s |
| 62774-58281 | 62774-58281 | 58890, altro piano | 3 | 158 s |
| 60150-80439 | 60150-80439 | 60144, stesso piano | 3 | 354 s |

- Installato con `tools/install_scenario.py --refresh`: cambia solo `config/migration_events.json`; fixture invariata, nessun riavvio. La verifica funzionale è stata invalidata e va ripetuta (serve comunque dopo il passo 4).

### 3. Termine misurato della latenza

- Fonte: il tempo di risposta del controller verso gli switch nelle prove registrate (`operations.jsonl`, scritture P4Runtime tramite il proxy). Il punto esatto da cui leggerlo va verificato prima di implementarlo. Se la misura non è affidabile, il termine resta 0 e lo dichiariamo nel resoconto.

### 4. Inoltro dal percorso di TeraFlow (`src/fixture.py`, `src/live_backend.py`, `tools/install_scenario.py`) — fatto, da verificare nel laboratorio

Lo schema iniziale (creare il servizio, leggere la connessione, aggiornare `fwd_list`) è stato scartato: in Release 7 `UpdateService` ricalcola il percorso a ogni aggiornamento e, cambiando l'intento di un servizio già attivo, crea una seconda connessione (nota già presente in `TfsAdapter.reconcile`). In più avrebbe aggiunto chiamate API durante la migrazione e cambiato i tempi misurati.

Soluzione adottata, verificata sul codice del gestore `p4_fabric_tna_l2_simple`: il gestore programma solo le porte della connessione scelta da TeraFlow e, su ciascuna, solo i MAC che `fwd_list` associa a quella porta; `fwd_list` può associare lo stesso MAC a più porte.

- `state()` descrive gli switch di **tutti** i percorsi minimi in salti fra gli host (`hop_distances`, come PathComp, che dà costo 1 a ogni collegamento) e, per ogni host, **tutte** le porte un salto più vicine. Qualunque percorso minimo TeraFlow scelga, le sue porte hanno le voci giuste e nessuno dei suoi switch manca dalle impostazioni. Su un percorso semplice ogni switch usa una sola porta per host, quindi non nascono voci in conflitto.
- Con percorso minimo unico l'intento è identico a prima: verificato su tutti i 2.880 istanti (ogni 30 s) del replay installato. Fixture invariata, nessun riavvio.
- Prima le regole seguivano la distanza in km: con un pareggio in salti potevano indicare un percorso diverso da quello di TeraFlow. Ora seguono i salti, come TeraFlow.
- Ogni prova scrive in `service-paths.jsonl` il percorso di ogni connessione calcolata da TeraFlow: sorgente preparata, eventuali ricreazioni per cambio di topologia, destinazione dopo la verifica API. La scrittura è fuori dalle fasi misurate.
- `install_scenario.py` rifiuta estremi senza percorso nel dominio e avvisa se in qualche istante ci sono più percorsi minimi. Per gli estremi installati gli istanti con pareggio sono 0 su 1.440 (ogni 60 s).
- Estremi del servizio invariati: con più percorsi minimi sorgente e destinazione potrebbero scegliere connessioni diverse, e l'equivalenza API (che confronta le connessioni) fallirebbe senza ACK. Con l'invariante intatto, cambiare estremi resta possibile ma va provato nel laboratorio.
- Fuori dal piano: ricalcolo del percorso durante la prova se un collegamento cade. Il vincolo dei 900 s di persistenza resta la protezione.

### 5. Parametro del job e worker (`src/jobs.py`, `src/event_comparison.py`, `src/experiment.py`, `tools/experiment.py`)

- `compare_events` accetta `parameters: {"policy": "designed" | "cost"}`, con `designed` come predefinito. `validate` rifiuta qualsiasi altro parametro o valore, come oggi.
- `compare(app, policy)` legge `selected` o `policy_selected`. Se `policy_selected` manca, il job fallisce prima di toccare il laboratorio con un messaggio chiaro.
- `metadata.json` registra in `design` la politica, i parametri e la provenienza dei downtime; la `schema_version` passa a 3. I risultati vecchi senza politica si leggono come `designed`.
- CLI: `tools/experiment.py compare_events --policy cost`.
- `functional` resta sul primo evento progettato.

### 6. Console (`web/index.html`, `web/app.js`, `web/style.css`, `src/web.py`)

- Nella card Esperimento, sopra «Avvia esperimento», una select «Politica»: «Eventi progettati (1, 5, 7 salti)» e «Costo (disponibilità e latenza)». La seconda è disabilitata, con il motivo, se il catalogo installato non ha `policy_selected`.
- `launch('compare_events')` invia la politica scelta. La scelta resta in `localStorage` (con `try/catch`) solo come comodità.
- `/api/v1/state` espone se `policy_selected` esiste e i tre eventi della politica.
- Risultati: la politica appare nella riga di stato dell'esperimento; ogni evento mostra destinazione e salti effettivi. Il pop-up «Cosa fa l'esperimento» descrive entrambe le politiche.
- Si mantengono sessione, controlli same-origin, replay SSE e registro dei download.

### 7. Test

- Politica: soglia rispettata, ordinamento per latenza, stessa destinazione per Hot e Cold, nessun candidato se la soglia è troppo alta.
- Catalogo: `policy_selected` ha la stessa sorgente e lo stesso ingresso in ombra degli eventi progettati, salvo i sostituti, che registrano l'evento sostituito.
- Fixture: tutti i percorsi minimi coperti e nessuno switch in più, una porta per host su ogni percorso, percorso unico invariato, nessun percorso, lettura del percorso da una connessione.
- Job: parametro valido e non valido, catalogo senza `policy_selected`, lettura dei metadati con `schema_version` 2.
- JavaScript: select, select disabilitata, payload dell'avvio.
- Laboratorio: verifica funzionale con il nuovo inoltro prima di qualsiasi esperimento con la politica.

## Ordine

1. Politica rivista e analisi di sensibilità (solo modello, nessun laboratorio). Scelta della soglia.
2. Catalogo con `policy_selected` e installazione.
3. Inoltro dal percorso di TeraFlow (fatto), poi verifica funzionale nel laboratorio.
4. Parametro del job, console, test.
5. Esperimento con la politica di costo (circa 2 ore, 19 prove come oggi).

## Da decidere

- Nulla per i passi 1 e 2.
