# Configurazione TeraFlowSDN per SAT-A e SAT-B

Usiamo un unico progetto Docker Compose, `teraflow`, con reti, database e broker indipendenti per SAT-A e SAT-B. La configurazione operativa è `deploy/stack.yaml`, generata dai template con `tools/generate_stack.py`. Il deployment è un adattamento sperimentale dei manifest ETSI v7.0.0. Il tag verificato punta al commit `fb8707871eba26806cac7ac373c70b2bb5bd26fc`.

## Componenti e immagini

I cinque componenti logici corrispondono a **sei immagini**: Context, Device, PathComp frontend, PathComp backend, Service e NBI. Il manifest ufficiale PathComp avvia due container nello stesso pod; in Compose sono servizi separati e il frontend usa `PATHCOMP_BACKEND_HOST=pathcomp-backend`.

Ogni host dispone di CockroachDB, NATS e Kafka. Context usa CockroachDB per i dati e NATS per gli eventi; il codice NBI v7.0.0 crea i topic Kafka all'avvio, quindi Kafka è necessario anche per questa selezione ridotta. Le dipendenze sono preinstallate nel modello e non fanno parte delle sei immagini migrate; CPU, RAM e disco da esse consumati vanno inclusi nel bilancio del satellite. I database di A e B non sono replicati fra loro: il trasferimento dello stato deve passare dall'adattatore.

## Preparazione e avvio

Usare `tools/build_tfs_images.py` per preparare e costruire le immagini. Lo script estrae l'archivio fissato e costruisce da un volume Linux gestito da Docker. Questo preserva la distinzione tra i percorsi upstream `ACL/` e `acl/`, che un filesystem Windows standard fonderebbe. `.reference/build-context` resta utile per l'ispezione, ma non è usato per le build definitive.

Da PowerShell, nella radice del nuovo progetto:

```powershell
python tools/build_tfs_images.py
docker compose --env-file deploy/lab.env -p teraflow -f deploy/stack.yaml config --quiet
.\.venv\Scripts\python.exe tools/stack.py up
# SAT-B viene avviato dallo stesso comando insieme a SAT-A e al laboratorio P4.
```

NBI è esposto solo localmente: SAT-A su `http://127.0.0.1:18080`, SAT-B su `http://127.0.0.1:18081`. Controllare `/healthz` e poi `/tfs-api/contexts`. La disponibilità HTTP non certifica il provisioning P4: serve una successiva prova di servizio tramite Device, PathComp e Service.

Le reti private dei due controller hanno alias DNS locali (`contextservice`, `kafka`, ecc.), così ogni stack risolve soltanto le proprie dipendenze. I volumi esterni `sat-a_crdb-data`, `sat-a_kafka-data`, `sat-b_crdb-data`, `sat-b_kafka-data` e `migration-lab_proxy-state` mantengono i dati del deployment precedente. I container dei satelliti conservano i nomi `sat-a-...`/`sat-b-...` e hanno etichette `org.teraflow.role`; la contabilità del disco filtra sia il progetto `teraflow` sia il satellite.

Le subnet predefinite sono 172.25.0.0/16 per il laboratorio, 172.26.0.0/16 per A e 172.27.0.0/16 per B. Mininet e proxy conservano gli indirizzi 172.25.0.2 e 172.25.0.3. Su un host con subnet già occupate, configurare `LAB_SUBNET`, `SAT_A_SUBNET`, `SAT_B_SUBNET`, `MININET_IP` e `P4_PROXY_IP` in `deploy/lab.env`, mantenendole distinte e adattando gli indirizzi statici alla subnet del laboratorio. Per modificare la configurazione generata, aggiornare i template e poi eseguire `tools/generate_stack.py`.

## Verifica runtime del 2 ottobre 2026

Le sei immagini sono state costruite dal sorgente Linux estratto dal commit fissato, per preservare la distinzione maiuscole/minuscole `ACL/` e `acl/`. SAT-A e SAT-B sono partiti con le immagini così ricostruite. Entrambi hanno superato `/healthz` e la lettura della lista dei contesti; il test `tools/check_tfs_hosts.py --check-isolation` ha creato un Context temporaneo su SAT-A, verificato che non fosse visibile da SAT-B, e poi lo ha rimosso.

I digest e le dimensioni locali non compresse delle sei immagini sono registrati in `config/teraflow-source.json`. La somma è 2.167.307.708 byte contando per intero ogni immagine: i layer condivisi tra immagini vengono quindi contati più volte. Questi valori sono dimensioni Docker locali non compresse, non i byte effettivi da trasmettere su FSO. Per i risultati di migrazione andrà misurato il formato concreto di trasferimento (per esempio archivio `docker save`, con o senza compressione) e il payload effettivamente inviato.

## Verifiche e limiti prima delle misure

- La verifica funzionale aggiornata include 17 dispositivi, topologia/link, restore del servizio L2NM e traffico ping/UDP end-to-end. Vedere `implementation-status.md` per le patch necessarie e le misure; cutover e campagna restano da validare.
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

## Variante locale L2NM verificata

La correzione locale autorizzata mantiene il commit upstream come base e registra diff/checksum separati in `deploy/patches/`. L'override `deploy/l2-patched.yaml` seleziona le immagini Service e Device `7.0.0-fb870787-lab2`. Il bundle effettivo, unico e non compresso, è descritto da `artifacts/images-l2-patched-v2/bundle.json`: 1.823.463.936 byte, SHA-256 `9fc2920c12e4cc8867cd34ad294f1c240acc34b181dd462ce69e5abd51531c00`.

Con il laboratorio già avviato, usare gli override anche quando si riavviano i controller:

```powershell
.\.venv\Scripts\python.exe tools/stack.py up
# La configurazione unica include gli override P4 e le immagini con patch per entrambi i controller.
python tools/live_preflight.py --reset-fixture
```

`--reset-fixture` elimina e ricrea gli oggetti della fixture di laboratorio sui due controller. Dopo un riavvio del proxy, riavviare Device su entrambi gli stack e ricostruire la fixture: lo stato standby del proxy non è persistente. L'emulatore disabilita gli offload degli host e usa logging BMv2 a livello warning per non compromettere le sonde su Docker Desktop.
