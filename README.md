# TeraFlowSDN — laboratorio di migrazioni satellitari

> Aggiornamento 19 ottobre 2026: la console propone un solo **Confronto continuo Hot/Cold**: durata per modalità, piano di eventi condiviso, Hot completo, ripristino e Cold completo. Verifiche e calibrazione sono automatiche quando necessarie. [Guida al confronto continuo](teraflow-migration-sim/docs/paired-continuous.md). Le sezioni sul confronto FSO singolo descrivono il percorso CLI precedente.

> Aggiornamento 16 ottobre 2026: il percorso principale è **Confronto FSO hot/cold**, su un evento a 1 Gbit/s con verifica API e ping. Simulazione continua e campagne rimangono funzioni avanzate con validazione separata. Avvio e criteri di successo sono nella [guida operativa](teraflow-migration-sim/docs/operating-guide.md).

Il repository contiene un solo progetto applicativo, in [`teraflow-migration-sim/`](teraflow-migration-sim/): migrazione hot/cold del controller TeraFlowSDN 7, geometria orbitale di 17 satelliti e verifica del servizio attraverso Mininet/BMv2/P4.

## Confronto FSO hot/cold

Il percorso principale è **Confronto FSO · hot e cold**, a 1 Gbit/s. Un unico job esegue hot, poi cold sullo stesso evento orbitale, ricostruendo lo stato iniziale prima di ciascuna prova. Non richiede la calibrazione della simulazione continua. La console mostra downtime del controller, ripristino ping, durata della migrazione e tentativi, con differenza cold meno hot.

La baseline richiede API e autorità P4 della sorgente e dieci ping freschi consecutivi. Dopo il cutover servono equivalenza API dello stato ripristinato, destinazione attiva e dieci ping consecutivi nuovi. UDP è diagnostico. Un errore ferma la coppia, conservando le evidenze; un job concluso non implica un confronto riuscito. I risultati sono in `results/comparisons/compare-*/metadata.json` all'interno del progetto e nel risultato del job.

Simulazione continua e campagne restano nelle funzioni avanzate. La prima coppia è una validazione funzionale; il confronto radio e la campagna statistica sono fasi successive.

## Avvio della console

Con le dipendenze Python installate nell'ambiente del progetto:

```powershell
cd teraflow-migration-sim
.\.venv\Scripts\python.exe tools/stack.py up
.\.venv\Scripts\python.exe tools/serve_gui.py
```

Aprire **http://127.0.0.1:18092/**. Per le operazioni live avviare Docker Desktop con engine Linux e il laboratorio TeraFlow/P4 descritto nella [guida di deployment](teraflow-migration-sim/docs/teraflow-compose.md).

Docker Desktop mostra tutti i servizi del laboratorio nel gruppo **teraflow**. Per controllarlo o fermarlo usare `tools/stack.py status` e `tools/stack.py stop` con lo stesso interprete. Dalla radice del repository sono disponibili anche `docker compose up -d --wait`, `docker compose stop` e `docker compose ps`. Su una nuova installazione eseguire prima `tools/stack.py up`, che crea i volumi persistenti necessari. `down` conserva i dati; il motore delle migrazioni continua ad avviare e fermare separatamente i workload A/B.

La precedente simulazione a sette satelliti, la dashboard sulla porta 8081 e il relativo proxy sono stati rimossi. Il progetto resta nella directory attuale per preservare i percorsi registrati nei manifest e nei risultati. La porta 8081 interna al container PathComp appartiene a TeraFlow e non espone la vecchia dashboard.

## Documentazione

- [Report sul funzionamento, frontend e report delle prove](teraflow-migration-sim/docs/report-funzionamento-applicazione.md)
- [Guida operativa: GUI, CLI, interruzione e recupero](teraflow-migration-sim/docs/operating-guide.md)
- [Descrizione tecnica del progetto](teraflow-migration-sim/README.md)
- [Stato di implementazione e limiti delle misure](teraflow-migration-sim/docs/implementation-status.md)

I risultati del nuovo progetto sono in `teraflow-migration-sim/results/`; le configurazioni, le immagini e le evidenze restano associate al laboratorio TeraFlow.

## Verifiche locali

```powershell
cd teraflow-migration-sim
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

I test che richiedono i protobuf P4 del container Linux possono essere saltati sull'host. L'esecuzione dei test locali non certifica il completamento della campagna live.
