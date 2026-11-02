# Correzione HTTP 500 durante la configurazione L2

## Evidenza del 23 ottobre 2026

Job `job-4c810a9197c84510b39a57dd29a6226d`, run `run-8e3cd26371d64cf0bd3c7ffc58befffe`: inventario completo di 64 dispositivi e 216 link. Il PUT del servizio è iniziato alle 11:07:31 UTC. Alle 11:08:01 UTC Gunicorn ha terminato il worker NBI con `WORKER TIMEOUT` mentre attendeva `ServiceClient.UpdateService`; la risposta è HTTP 500. Il Service continuava a configurare porte dopo la perdita della risposta, fino allo shutdown verificato. Nessuna misura di migrazione è stata prodotta.

Il precedente limite di preparazione non è la causa di questo errore: il ripristino aveva ancora budget. L'handler P4 applicava una chiamata `ConfigureDevice` per ogni regola; ogni chiamata ripete letture e scritture Context e riconciliazione degli endpoint. La configurazione delle prime tre porte era ancora in corso alla scadenza NBI.

## Correzione

La patch locale del solo handler L2 invia le regole ordinate di una porta in una chiamata `ConfigureDevice`. Il driver conserva l'applicazione sequenziale e le dipendenze membro/tabella; gli errori Device vengono propagati, senza contare il batch come applicato. Nessun parallelismo, retry o aumento dei timeout NBI/Gunicorn è introdotto. La policy è `ordered-rules-one-configure-rpc-per-port-v1`.

Immagine distinta `tfs-migration/service:7.0.0-fb870787-lab3`; bundle nuovo `artifacts/images-l2-patched-v3`. Il bundle precedente resta sul disco; una copia del relativo manifest della patch è conservata nel suo folder. Hash del nuovo sorgente e diff sono prodotti dal generatore della patch. Le nuove calibrazioni devono misurare il nuovo bundle e la nuova implementazione; nessuna vecchia misura viene convertita o attribuita alla nuova immagine.

## Verifica

Test mirati: ordine di inserimento e cancellazione, un RPC per batch, batch vuoto, propagazione del fallimento, budget/caricamento/cancellazione e deployment. Verifica nell'immagine Service senza rete con i veri protobuf: batch ordinato e un solo RPC confermati. La suite completa e la prova funzionale live hanno evidenze separate; questa descrizione della correzione non costituisce accettazione del confronto alle tre velocità.

Suite completa: **211 test, OK, 9 skipped**, log `.test-tmp/service-lab3-suite.log` nella radice del workspace. I nove skip riguardano dipendenze protobuf/P4 dell'host; il controllo del batch con protobuf reali è stato eseguito nell'immagine Service. Graphify aggiornato: 2079 nodi, 4914 archi.

### Riscontro live della correzione

Job `job-f5aa08bc55984a0892a98481db4ec9c4`, run `run-449e922bef9847bd8338f97de9ff3d7d`, immagine `tfs-migration/service:7.0.0-fb870787-lab3` con digest `sha256:8cf95d5fb4dfaaec1d482b47e0d9918486de369fd011f83ce37ea00cd1b9f0f1`.

- Caricati 64/64 dispositivi, 216/216 link e 1/1 servizio; verifica inventario e snapshot completata.
- Il PUT del servizio prima fallito ha risposto **200 in 10,247403 s**. Evidenza: `restore-operations.jsonl` nella directory del run.
- `baseline.json`: `success=true`, autorità/API verificate, 12 ping consecutivi senza perdite e 110 pacchetti UDP ricevuti.
- Bundle nuovo: SHA256 `ec2e48e7ba4e5ee1956b4d68add982e23d0cfbcfeac3d3ea08498cda8acf8a4e`, 1823463936 byte. Non sono state riutilizzate misure di calibrazione precedenti.

Questo riscontro verifica la correzione del 500 e il servizio iniziale. L'esito delle migrazioni funzionali e del confronto scientifico alle tre velocità va letto dai rispettivi risultati; non è implicato da questo successo di preparazione.
