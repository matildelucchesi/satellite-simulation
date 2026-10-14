# TeraFlowSDN — laboratorio di migrazioni satellitari

Il repository contiene un solo progetto applicativo, in [`teraflow-migration-sim/`](teraflow-migration-sim/): migrazione hot/cold del controller TeraFlowSDN 7, geometria orbitale di 17 satelliti e verifica del servizio attraverso Mininet/BMv2/P4.

## Avvio della console

Con le dipendenze Python installate nell'ambiente del progetto:

```powershell
cd teraflow-migration-sim
.\.venv\Scripts\python.exe tools/serve_gui.py
```

Aprire **http://127.0.0.1:18092/**. Per le operazioni live avviare Docker Desktop con engine Linux e il laboratorio TeraFlow/P4 descritto nella [guida di deployment](teraflow-migration-sim/docs/teraflow-compose.md).

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
