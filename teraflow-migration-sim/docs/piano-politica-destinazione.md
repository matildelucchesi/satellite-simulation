# Piano: politica di destinazione e forwarding dai percorsi di TeraFlow

Branch: `forwarding-path-selection`. Stato: passi 1, 2, 4, 5 e 6 completati e verificati (12 novembre 2026); passo 3 (termine misurato della latenza) aperto. Primo esperimento con la politica completato (permanenza libera); la politica ha ora una permanenza minima di 600 s e l'esperimento va ripetuto.

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
| Permanenza minima | 600 s dopo la migrazione (`minimum_stay_s`). Senza, la politica sceglie destinazioni che restano appena oltre la soglia (circa 170 s) e il controller migra ogni 6 minuti, metà del tempo in migrazione. Con 600 s migra circa ogni 15 minuti (21 % del tempo in migrazione, downtime Cold 14,5 %). |
| Eventi della politica | Sugli ingressi in ombra degli eventi progettati; un ingresso non servito è sostituito dall'ingresso servito più vicino nel tempo con sorgente e destinazione non usate dagli altri eventi, così le tre migrazioni sono distinte. Non in catena: nel dominio fisso, con 600 s di permanenza, una catena regge una sola migrazione (vedi punto 8). L'evoluzione nel tempo del controller si studia nel modello, con il dominio che lo segue. |

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
- `policy_selected` (`policy_selected_events`): per ognuno dei 3 eventi progettati, la destinazione della politica sullo stesso ingresso in ombra della stessa sorgente. Un ingresso che la politica non può servire è sostituito dall'ingresso servito più vicino nel tempo, non già usato, la cui sorgente e destinazione non compaiono (né come sorgente né come destinazione) negli altri eventi; l'evento registra `replaces_designed_entry` e il motivo. Prima della regola il sostituto di 62768-8295 era 62774 → 60138 alle 02:06:08, la stessa migrazione dell'evento 2 (esperimento `job-98035e08…`, 18 novembre 2026).
- Ogni evento della politica porta `candidates` (`candidate_map`): tutti i satelliti del dominio all'ingresso in ombra, con latenza di controllo, permanenza e disponibilità di quelli che rispettano i vincoli e, per gli esclusi, il primo vincolo che non rispettano (`REJECTION_REASONS`). La console lo disegna nella tabella degli eventi della politica.
- Con la permanenza minima di 600 s la politica serve 90 dei 240 ingressi in ombra del dominio, con 5–6 salti: ogni satellite più indietro sull'orbita dà circa 180 s di luce in più, quindi 600 s richiedono di andare 5 o 6 satelliti indietro.
- Eventi installati (permanenza minima 600 s):

| Evento progettato | Evento della politica | Destinazione | Salti | Permanenza | Latenza |
| --- | --- | --- | --- | --- | --- |
| 62768-8295 | 62775-7387 (sostituto) | 60142, altro piano | 6 | 705 s | 14,0 ms |
| 62774-58281 | 62774-58281 | 60138, altro piano | 6 | 702 s | 17,7 ms |
| 60150-80439 | 60150-80439 | 68285, stesso piano | 5 | 714 s | 11,5 ms |

- Primo esperimento con la politica, senza permanenza minima (62776→60138, 62774→58890, 60150→60144, tutti a 3 salti): `events-56630cf4…`, 18 prove su 18 riuscite, Cold − Hot 137, 132 e 126 s, come con gli eventi progettati.
- Provata e scartata: gli eventi della politica in catena (la sorgente di ogni evento è la destinazione del precedente). Senza permanenza minima la catena più lunga nel dominio fisso ha 3 migrazioni; con 600 s una sola. `policy_chains` resta per il controllo del punto 8.

- Installato con `tools/install_scenario.py --refresh`: cambia solo `config/migration_events.json`; fixture invariata, nessun riavvio. La verifica funzionale è stata invalidata e va ripetuta (serve comunque dopo il passo 4).

### 3. Termine misurato della latenza

- Fonte: il tempo di risposta del controller verso gli switch nelle prove registrate (`operations.jsonl`, scritture P4Runtime tramite il proxy). Il punto esatto da cui leggerlo va verificato prima di implementarlo. Se la misura non è affidabile, il termine resta 0 e lo dichiariamo nel resoconto.

### 4. Inoltro dal percorso di TeraFlow (`src/fixture.py`, `src/live_backend.py`, `tools/install_scenario.py`) — fatto e verificato

Lo schema iniziale (creare il servizio, leggere la connessione, aggiornare `fwd_list`) è stato scartato: in Release 7 `UpdateService` ricalcola il percorso a ogni aggiornamento e, cambiando l'intento di un servizio già attivo, crea una seconda connessione (nota già presente in `TfsAdapter.reconcile`). In più avrebbe aggiunto chiamate API durante la migrazione e cambiato i tempi misurati.

Soluzione adottata, verificata sul codice del gestore `p4_fabric_tna_l2_simple`: il gestore programma solo le porte della connessione scelta da TeraFlow e, su ciascuna, solo i MAC che `fwd_list` associa a quella porta; `fwd_list` può associare lo stesso MAC a più porte.

- `state()` descrive gli switch di **tutti** i percorsi minimi in salti fra gli host (`hop_distances`, come PathComp, che dà costo 1 a ogni collegamento) e, per ogni host, **tutte** le porte un salto più vicine. Qualunque percorso minimo TeraFlow scelga, le sue porte hanno le voci giuste e nessuno dei suoi switch manca dalle impostazioni. Su un percorso semplice ogni switch usa una sola porta per host, quindi non nascono voci in conflitto.
- Con percorso minimo unico l'intento è identico a prima: verificato su tutti i 2.880 istanti (ogni 30 s) del replay installato. Fixture invariata, nessun riavvio.
- Prima le regole seguivano la distanza in km: con un pareggio in salti potevano indicare un percorso diverso da quello di TeraFlow. Ora seguono i salti, come TeraFlow.
- Ogni prova scrive in `service-paths.jsonl` il percorso di ogni connessione calcolata da TeraFlow: sorgente preparata, eventuali ricreazioni per cambio di topologia, destinazione dopo la verifica API. La scrittura è fuori dalle fasi misurate.
- `install_scenario.py` rifiuta estremi senza percorso nel dominio e avvisa se in qualche istante ci sono più percorsi minimi. Per gli estremi installati gli istanti con pareggio sono 0 su 1.440 (ogni 60 s).
- Estremi del servizio invariati: con più percorsi minimi sorgente e destinazione potrebbero scegliere connessioni diverse, e l'equivalenza API (che confronta le connessioni) fallirebbe senza ACK. Con l'invariante intatto, cambiare estremi resta possibile ma va provato nel laboratorio.
- Fuori dal piano: ricalcolo del percorso durante la prova se un collegamento cade. Il vincolo dei 900 s di persistenza resta la protezione.
- Verifica funzionale `compare-2baabf59…` (12 novembre 2026): Hot riuscita (downtime 5,3 s, durata 177,1 s), Cold riuscita (127,1 s, 188,8 s), ping continui, servizio verificato. TeraFlow ha calcolato per sorgente e destinazione lo stesso percorso di 7 salti lungo l'arco del piano 1.

### 5. Parametro del job e worker (`src/jobs.py`, `src/event_comparison.py`, `src/experiment.py`, `tools/experiment.py`) — fatto

- `compare_events` accetta `parameters: {"policy": "designed" | "cost"}`, con `designed` come predefinito. `validate` rifiuta altri parametri, altre politiche e `policy` per le altre operazioni.
- Con `cost` e un catalogo senza `policy_selected` l'avvio fallisce prima di prendere il lock e di avviare il worker, quindi senza richiedere il ripristino.
- `compare(app, policy)` legge `selected` o `policy_selected`. `metadata.json` passa a `schema_version` 3 e registra in `design` la politica e i suoi parametri; ogni evento della politica registra l'evento progettato corrispondente e se lo sostituisce. I risultati precedenti si leggono come `designed`.
- CLI: `tools/experiment.py compare_events --policy cost --wait`.
- `functional` resta sul primo evento progettato.

### 6. Console (`web/index.html`, `web/app.js`, `web/style.css`, `src/web.py`) — fatto

- Nella card Esperimento, accanto a «Avvia esperimento», la select «Politica»: «Eventi progettati» e «Politica di costo». Con la seconda, sotto, l'elenco dei tre eventi; se il catalogo non li ha, l'opzione è disabilitata e una nota spiega perché. La scelta resta in `localStorage` (con `try/catch`).
- `/api/v1/scenario-profiles` espone `policy_events` e i parametri della politica; `/api/v1/topology?event=` trova anche gli eventi della politica.
- Pagina Scenario: un esperimento avviato con la politica segue i suoi eventi. L'anteprima segue gli eventi dell'esperimento scelto in «Tempi da» (progettati o della politica); la tabella degli eventi della politica è sotto quella degli eventi progettati.
- Risultati: un pannello «Politica di destinazione» con regola, parametri e, per ogni evento, scelta, evento progettato, permanenza, disponibilità attesa e latenza; la politica è anche nel menu degli esperimenti.

### 7. Test

- Politica: soglia rispettata, ordinamento per latenza, stessa destinazione per Hot e Cold, nessun candidato se la soglia è troppo alta.
- Catalogo: `policy_selected` ha la stessa sorgente e lo stesso ingresso in ombra degli eventi progettati, salvo i sostituti, che registrano l'evento sostituito. La permanenza minima esclude le destinazioni che resterebbero meno. Le catene della politica seguono il controller e si fermano su una sorgente senza destinazione ammessa.
- Fixture: tutti i percorsi minimi coperti e nessuno switch in più, una porta per host su ogni percorso, percorso unico invariato, nessun percorso, lettura del percorso da una connessione.
- Job: parametro valido e non valido, catalogo senza `policy_selected`, lettura dei metadati con `schema_version` 2.
- JavaScript: select, select disabilitata, payload dell'avvio.
- Laboratorio: verifica funzionale con il nuovo inoltro prima di qualsiasi esperimento con la politica.

### 8. Analisi: dominio che segue il controller (solo modello) — fatto

Il laboratorio emula un dominio fisso di 16 satelliti; questa analisi, solo sul replay del profilo, misura quanto il dominio fisso condiziona la politica. Il laboratorio non cambia.

- `domain_around(host, …)`: dominio ricostruito attorno al satellite che ospita il controller, con la stessa regola di `choose_domain`: 8 satelliti consecutivi del suo piano, `behind` dei quali lo seguono sull'orbita, e gli 8 dell'altro piano più vicini all'arco.
- `follow_controller(…, domain_of, …)`: la politica di costo (stessi vincoli, stessi tempi misurati, soglia 95 % Hot) decide a ogni ingresso in ombra del satellite che ospita il controller, dentro `domain_of(host, istante)`; la decisione successiva è all'ingresso in ombra della destinazione. Si ferma quando non c'è una destinazione ammessa o quando finisce il replay (una destinazione al sole fino alla fine del replay non resterebbe abbastanza). Con il dominio fisso ritrova esattamente le catene del catalogo (lo strumento lo controlla).
- `tools/sliding_domain.py [--behind 4 6 7]` parte da ognuno dei 240 ingressi in ombra del dominio fisso e scrive `results/analysis/sliding-domain.json`. In `journeys` registra, per ogni dominio e dalla stessa partenza, la giornata del controller migrazione per migrazione (satelliti, salti, piano, permanenza, latenza, destinazioni ammesse, satelliti che entrano ed escono dal dominio).
- Console, pagina Scenario, pannello «Il controller nel tempo» (`/api/v1/controller-journey`): sceglie il dominio e mostra in tre grafici sull'ora del giorno il piano del satellite che ospita il controller, la latenza e la permanenza di ogni migrazione, con i valori al passaggio del mouse e la tabella di tutte le migrazioni. Se il catalogo cambia dopo l'analisi, avvisa di rieseguirla.

Risultati senza permanenza minima (profilo installato, 12 novembre 2026):

| Dominio | Partenze servite | Migrazioni per catena (media, max) | Arresto | Una migrazione ogni | Permanenza media | Latenza scelta | Destinazioni ammesse | Altro piano | Satelliti che cambiano dominio per passo |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| Fisso (laboratorio) | 180 su 240 | 2, 3 | nessuna destinazione ammessa | 370 s | 176 s | 14,1 ms | 4,8 | 31 % | 0 |
| Segue, 2 dietro | 240 su 240 | 120, 230 | fine del replay | 363 s | 169 s | 17,7 ms | 2,0 | 40 % | 4 |
| Segue, 4 dietro (centrato) | 240 su 240 | 120, 230 | fine del replay | 363 s | 169 s | 11,6 ms | 6,0 | 35 % | 4 |
| Segue, 6 dietro | 240 su 240 | 86, 164 | fine del replay | 509 s | 315 s | 10,3 ms | 10,0 | 58 % | 5,6 |

- Con il dominio che segue il controller la politica non si blocca più: dalla catena installata (60150, 00:25:57) il controller migra 230 volte in 23,2 ore, fino alla fine del replay. Con il dominio fisso si ferma dopo 3 migrazioni sul bordo (60138).
- Il prezzo è il passaggio di satelliti fra domini: 4 su 16 a ogni migrazione con il dominio centrato (5,6 con 6 dietro). È un'operazione che il laboratorio non emula.
- La latenza scelta scende da 14,1 ms (dominio fisso, il controller scivola verso il bordo) a 11,6 ms (centrato) o 10,3 ms (6 dietro).
- Con qualsiasi dominio la politica migra molto spesso: sceglie la destinazione con la latenza minima fra quelle che restano appena oltre la soglia, quindi la permanenza è breve (circa 170 s) e la migrazione successiva arriva dopo circa 6 minuti. Il controller passa circa metà del tempo a migrare; il downtime è l'1,8 % in Hot ma sarebbe il 36 % in Cold. Mettere più satelliti dietro il controller (6 dietro) allunga la permanenza a 315 s e riduce il downtime Cold al 26 %, perché le destinazioni con più luce sono quelle che lo seguono.
- Le misure Hot/Cold del laboratorio non cambiano: la migrazione emulata è la stessa con qualsiasi dominio.

Con la permanenza minima di 600 s:

| Dominio | Partenze servite | Migrazioni per catena (media, max) | Arresto | Una migrazione ogni | Permanenza media | Latenza scelta | Destinazioni ammesse | Altro piano | Satelliti che cambiano dominio per passo |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| Fisso (laboratorio) | 90 su 240 | 1, 1 | nessuna destinazione ammessa | 903 s | 709 s | 14,4 ms | 4,0 | 50 % | 0 |
| Segue, 4 dietro (centrato) | 0 su 240 | — | nessuna destinazione ammessa | — | — | — | — | — | — |
| Segue, 6 dietro | 240 su 240 | 48, 92 | fine del replay | 908 s | 714 s | 14,0 ms | 4,0 | 39 % | 10 |
| Segue, 7 dietro | 240 su 240 | 48, 92 | fine del replay | 908 s | 714 s | 11,5 ms | 6,0 | 44 % | 10 |

- Il controller migra circa ogni 15 minuti invece che ogni 6; passa il 21 % del tempo in migrazione; il downtime è lo 0,7 % in Hot e il 14,5 % in Cold.
- La permanenza richiede di andare 5–6 satelliti indietro, quindi il dominio deve estendersi dietro il controller: centrato (4 dietro) non ammette nessuna destinazione. Con 6–7 dietro la politica regge fino alla fine del replay, ma a ogni migrazione 10 satelliti su 16 cambiano dominio.
- Dominio fisso più grande (arco che termina in 60150 e si estende indietro): con 600 s le catene restano di 1 migrazione fino a 10 satelliti per piano, arrivano a 2 con 12 e a 5 con 16; solo da 20 per piano (40 switch) la politica regge tutto il giorno, con latenza media 33 ms. Un piano orbitale in più non aiuta: la luce in più viene dalla posizione lungo l'orbita, non dal numero di piani.

## Ordine

1. Politica rivista e analisi di sensibilità — fatto.
2. Catalogo con `policy_selected` e installazione — fatto.
3. Inoltro dal percorso di TeraFlow e verifica funzionale — fatto.
4. Parametro del job, console, test — fatto.
5. Esperimento con la politica di costo — fatto senza permanenza minima (`events-56630cf4…`); da ripetere con la permanenza minima di 600 s (circa 2 ore, 19 prove).

## Da decidere

- Nulla per i passi 1 e 2.
