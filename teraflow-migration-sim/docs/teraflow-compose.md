# Configurazione TeraFlowSDN per SAT-A e SAT-B

Usiamo due progetti Docker Compose distinti, `sat-a` e `sat-b`, con reti, database e broker indipendenti. Il deployment è un adattamento sperimentale dei manifest ETSI v7.0.0. Il tag verificato punta al commit `fb8707871eba26806cac7ac373c70b2bb5bd26fc`.

## Componenti e immagini

I cinque componenti logici corrispondono a **sei immagini**: Context, Device, PathComp frontend, PathComp backend, Service e NBI. Il manifest ufficiale PathComp avvia due container nello stesso pod; in Compose sono servizi separati e il frontend usa `PATHCOMP_BACKEND_HOST=pathcomp-backend`.

Ogni host dispone di CockroachDB, NATS e Kafka. Context usa CockroachDB per i dati e NATS per gli eventi; il codice NBI v7.0.0 crea i topic Kafka all'avvio, quindi Kafka è necessario anche per questa selezione ridotta. Le dipendenze sono preinstallate nel modello e non fanno parte delle sei immagini migrate; CPU, RAM e disco da esse consumati vanno inclusi nel bilancio del satellite. I database di A e B non sono replicati fra loro: il trasferimento dello stato deve passare dall'adattatore.

## Preparazione e avvio

Usare `tools/build_tfs_images.py` per preparare e costruire le immagini. Lo script estrae l'archivio fissato e costruisce da un volume Linux gestito da Docker. Questo preserva la distinzione tra i percorsi upstream `ACL/` e `acl/`, che un filesystem Windows standard fonderebbe. `.reference/build-context` resta utile per l'ispezione, ma non è usato per le build definitive.

Da PowerShell, nella radice del nuovo progetto:

```powershell
python tools/build_tfs_images.py
docker compose --env-file deploy/sat-a.env -p tfs-sat-a -f deploy/compose.yaml config --quiet
docker compose --env-file deploy/sat-a.env -p tfs-sat-a -f deploy/compose.yaml up -d
docker compose --env-file deploy/sat-b.env -p tfs-sat-b -f deploy/compose.yaml up -d
```

NBI è esposto solo localmente: SAT-A su `http://127.0.0.1:18080`, SAT-B su `http://127.0.0.1:18081`. Controllare `/healthz` e poi `/tfs-api/contexts`. La disponibilità HTTP non certifica il provisioning P4: serve una successiva prova di servizio tramite Device, PathComp e Service.

## Verifica runtime del 2 ottobre 2026

Le sei immagini sono state costruite dal sorgente Linux estratto dal commit fissato, per preservare la distinzione maiuscole/minuscole `ACL/` e `acl/`. SAT-A e SAT-B sono partiti con le immagini così ricostruite. Entrambi hanno superato `/healthz` e la lettura della lista dei contesti; il test `tools/check_tfs_hosts.py --check-isolation` ha creato un Context temporaneo su SAT-A, verificato che non fosse visibile da SAT-B, e poi lo ha rimosso.

I digest e le dimensioni locali non compresse delle sei immagini sono registrati in `config/teraflow-source.json`. La somma è 2.167.307.708 byte contando per intero ogni immagine: i layer condivisi tra immagini vengono quindi contati più volte. Questi valori sono dimensioni Docker locali non compresse, non i byte effettivi da trasmettere su FSO. Per i risultati di migrazione andrà misurato il formato concreto di trasferimento (per esempio archivio `docker save`, con o senza compressione) e il payload effettivamente inviato.

## Verifiche e limiti prima delle misure

- La verifica di health e isolamento del Context è stata superata; resta da esercitare la creazione di topologia/dispositivi/link e un servizio dati di prova end-to-end.
- Verificare avvio, riavvio e mantenimento dei dati locali. `depends_on` per i componenti TFS ordina l'avvio, ma non certifica la disponibilità delle loro API.
- I digest immagine e i digest delle immagini dipendenza sono fissati. Registrare ancora dimensioni degli archivi effettivamente trasferiti, dipendenze Python risolte e consumi di tutti i container.
- Il profilo 6 core / 12 GiB / 80 GiB è il budget complessivo di ogni host simulato. Questo file di preparazione non applica ancora quote aggregate: calibrazione e limiti vanno verificati prima di produrre risultati di prestazione.
- I due stack condividono il motore Docker e la sua cache immagini durante la verifica funzionale. Non usare la disponibilità di un'immagine in questa cache come prova del suo trasferimento a SAT-B: la simulazione deve imporre una contabilità per host e controllare separatamente i byte trasferiti e la disponibilità degli artefatti.
- La rete Compose non modella FSO: ritardo, allineamento, finestra di contatto e throughput saranno applicati dal livello di migrazione. Le API locali sono accessi di laboratorio.
- Database e broker sono confinati nella rete del progetto, senza porte pubblicate. La modalità CockroachDB `--insecure` serve a questo laboratorio locale e non rappresenta la sicurezza di una rete satellitare operativa.

## Fonti verificate

- [Deployment ETSI 7.0.0](https://tfs.etsi.org/documentation/v7.0.0/deployment_guide/): deployment ufficiale MicroK8s.
- [Manifest PathComp](https://labs.etsi.org/rep/tfs/controller/-/blob/fb8707871eba26806cac7ac373c70b2bb5bd26fc/manifests/pathcompservice.yaml): frontend e backend distinti.
- [Avvio NBI](https://labs.etsi.org/rep/tfs/controller/-/blob/fb8707871eba26806cac7ac373c70b2bb5bd26fc/src/nbi/service/app.py): creazione topic Kafka.
- [Immagine Docker Apache Kafka 3.9](https://kafka.apache.org/39/getting-started/docker/): immagine JVM `apache/kafka:3.9.1`.

Lo stato effettivo della verifica runtime viene aggiornato dopo build e prova delle API. La sola validazione sintattica Compose non costituisce una validazione del controller.
