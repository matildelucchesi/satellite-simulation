# Esperimento di migrazione del piano di controllo SDN

## Scopo e architettura dell’esperimento

L’esperimento confronta la migrazione della funzione di controller tra satelliti usando TeraFlowSDN Release 7 come workload Docker, dati orbitali Starlink e collegamenti inter-satellite modellati come FSO. Si confrontano hot e cold migration in tre condizioni orbitali (Worst, Base/Average e Best) e a tre valori di throughput FSO utile: 100 Mbit/s, 1 Gbit/s e 10 Gbit/s.

Si separano tre piani che hanno tempi e risultati distinti:

1. **Piano orbitale:** propaga i TLE, costruisce la topologia satellite-satellite e determina scadenze e finestre di contatto.
2. **Piano di migrazione:** trasferisce immagini Docker e stato operativo tra SAT-A e SAT-B sul collegamento FSO con TCP/IP.
3. **Piano dati del servizio:** inoltra pacchetti tra endpoint attraverso una rete emulata Mininet con switch BMv2/P4, configurati da TeraFlowSDN.

La simulazione studia la migrazione e il ripristino del piano di controllo; non dimostra che un deployment TeraFlowSDN completo sia già pronto per migrare operativamente tra satelliti.

## Costellazione Starlink e TLE

La shell di riferimento è **53° / 550 km**, con satelliti appartenenti a **due piani orbitali**.

La nuova simulazione usa il catalogo Starlink CelesTrak acquisito il **1 ottobre 2026**, contenente **10.681 oggetti**, archiviato in [teraflow-migration-sim/data/starlink_2026-10-01.tle](teraflow-migration-sim/data/starlink_2026-10-01.tle). URL di provenienza, data di acquisizione, epoca e checksum SHA-256 sono registrati nel [manifest della fonte](teraflow-migration-sim/data/source_manifest.json). Il file rimane congelato per rendere ripetibili le prove. [Documentazione CelesTrak sui dati GP/TLE](https://www.celestrak.org/NORAD/documentation/gp-data-formats.php)

La selezione iniziale è stata generata in [selected_constellation.json](teraflow-migration-sim/config/selected_constellation.json), che contiene ID NORAD, nomi, assegnazione ai due piani, parametri orbitali ed epoca di riferimento. Il filtro comprende inclinazioni **52,5–53,5°** e quote medie ricavate dal semiasse maggiore SGP4 di **520–580 km**. Gli elementi vengono propagati con SGP4 a un’epoca comune prima del raggruppamento per RAAN, così da tenere conto della precessione tra le diverse epoche dei TLE.

Il raggruppamento usa un massimo intervallo di **1,5° tra RAAN consecutivi**; tra le coppie di gruppi con separazione RAAN di **10–30°**, si sceglie quella con più satelliti complessivi e si mantengono tutti i suoi candidati. Per il catalogo congelato i centri RAAN dei due gruppi sono circa **90,00° e 110,03°**. Il metodo identifica i piani ai fini del modello; l’appartenenza operativa a una shell Starlink non è certificata dal solo filtro geometrico.

### Dimensione del modello

Il modello ridotto iniziale comprende **17 satelliti: 6 nel primo piano e 11 nel secondo**. Gli stessi ID e lo stesso numero di satelliti restano fissi nei casi Worst, Base/Average e Best. Il campione è stato ampliato rispetto ai 10 satelliti inizialmente proposti per consentire una scelta fra più destinazioni FSO.

Le quote medie effettive del campione sono circa **521,9–540,1 km**. Si mantiene il filtro 520–580 km concordato: **STARLINK-3527 (NORAD 51726), a 521,9 km**, è incluso e va segnalato come caso limite nell’interpretazione dei risultati. Con il filtro più stretto 530–570 km restano 16 satelliti e, nella verifica geometrica di 24 ore, nessuna sorgente ha più di un vicino FSO diretto. Con 17 satelliti, tre sorgenti hanno più destinazioni dirette in alcuni momenti; l’idoneità effettiva al trigger dovrà includere anche risorse e disponibilità temporale.

Il passo temporale orbitale è **1 secondo**, con una prima finestra di osservazione di **24 ore**. La verifica geometrica ha prodotto **168 finestre FSO**, tutte lunghe almeno 60 s, distribuite su **7 coppie distinte**, senza errori SGP4. Si applicano portata massima di 1.700 km e assenza di occultamento da parte di una Terra sferica di raggio 6.378,137 km. Le finestre sono archiviate in [direct_link_windows.json](teraflow-migration-sim/results/direct_link_windows.json): rappresentano contatti geometrici, non migrazioni già selezionate o eseguite.

### Epoca e visibilità dall’Italia

L’epoca comune di riferimento è **1 ottobre 2026, 09:01:39,677 UTC**, corrispondente all’epoca più recente nel catalogo congelato. I TLE dei satelliti selezionati hanno un’età di circa **10–15,3 ore** rispetto a tale riferimento. L’inizio della verifica orbitale è fissato a questa epoca e non è stato ottimizzato per la visibilità dall’Italia.

La configurazione attuale non include un gateway terrestre nel percorso del servizio. Se verrà introdotto, occorrerà fissare coordinate, maschera di elevazione e finestra di osservazione; Firenze e una maschera di 10° restano una proposta per tale estensione.

Parametri comuni, criteri di selezione e comandi per riprodurre la configurazione sono disponibili in [scenario.json](teraflow-migration-sim/config/scenario.json), nella [descrizione della selezione orbitale](teraflow-migration-sim/docs/orbital-selection.md) e nel [README del nuovo progetto](teraflow-migration-sim/README.md). La configurazione orbitale iniziale è disponibile. Gli stack TeraFlow Compose sono stati avviati e hanno superato i controlli iniziali di salute e isolamento; restano da implementare e validare l’adattatore di ripristino, l’integrazione Mininet e la selezione degli eventi Worst/Base/Best con trigger e score.

## Scenari Worst, Base/Average e Best

Si usano gli stessi satelliti e gli stessi due piani in tutti e tre i casi. Worst, Base/Average e Best sono occasioni di handover distinte nel tempo, non costellazioni modificate artificialmente.

Per ogni evento si calcolano:

\[
T_{\text{disponibile}}=\min(W_{\text{FSO}},T_{\text{scadenza}})
\]

\[
M_{\text{orbitale}}=T_{\text{disponibile}}-T_{\text{allineamento}}
\]

Dove (W_{\text{FSO}}) è la durata del contatto FSO continuo, (T_{\text{scadenza}}) è il tempo alla scadenza operativa e (T_{\text{allineamento}}=60\) s.

I percentili si calcolano sugli **eventi di handover distinti**, non su ogni campione al secondo:

- **10º percentile:** evento Worst rappresentativo;
- **50º percentile:** evento Base/Average, cioè l’occasione mediana;
- **90º percentile:** evento Best rappresentativo.

Per ciascun percentile si seleziona l’evento reale più vicino. Hot, cold e tutti i valori di throughput sono poi provati sullo stesso evento e sulla stessa coppia SAT-A/SAT-B.

## Trigger e selezione del next-controller

Il trigger decide **quando** avviare una migrazione; lo score decide **quale SAT-B** scegliere. Sono decisioni separate.

Il trigger scatta se almeno una delle condizioni seguenti persiste secondo le regole temporali definite:

- SAT-A si avvicina alla scadenza operativa associata nel modello al suo ingresso in ombra;
- la previsione indica che CPU o RAM di SAT-A supereranno la soglia entro l’orizzonte (H).

L’ingresso in ombra è una scadenza operativa del modello; **non equivale automaticamente alla perdita del collegamento FSO**.

### Requisiti minimi dei candidati

Prima del ranking, si escludono i satelliti che non soddisfano questi requisiti:

- SAT-B è raggiungibile sul collegamento FSO secondo distanza, visibilità e finestra di contatto del modello;
- CPU e RAM consentono di ospitare il controller mantenendo la riserva del 20%;
- il disco ha spazio per immagini mancanti, stato operativo e riserva prevista.

Il margine di migrazione **non è un filtro di idoneità** nelle prove comparative principali: viene registrato come risultato. Se è negativo, la migrazione non entra nei tempi disponibili secondo le ipotesi del caso.

### Score del next-controller

Per ogni candidato idoneo (i), si calcola:

\[
S_i=100\left(0{,}35U_{\text{latenza},i}+0{,}30U_{\text{connettività},i}+0{,}20U_{\text{continuità},i}+0{,}15U_{\text{risorse},i}\right)
\]

Ogni utilità è normalizzata tra 0 e 1; un valore maggiore indica sempre un candidato migliore.

- **(U_{\text{latenza},i}), peso 35%:** premia una latenza di controllo più bassa tra SAT-B e gli elementi che deve gestire; la normalizzazione è inversa.
- **(U_{\text{connettività},i}), peso 30%:** misura la quota degli elementi di rete necessari al controllo raggiungibile da SAT-B nella topologia prevista.
- **(U_{\text{continuità},i}), peso 20%:** misura per quanto tempo il candidato dovrebbe mantenere il ruolo prima della prossima interruzione operativa prevista. Si basa sulla disponibilità futura, non sul numero di nodi raggiungibili.
- **(U_{\text{risorse},i}), peso 15%:** premia il margine residuo di CPU, RAM e disco dopo l’avvio del workload e il ripristino.

I pesi sono una scelta di progetto, non pesi ottimali dimostrati per una costellazione reale. Le definizioni esatte delle normalizzazioni e i valori di riferimento restano da fissare e andranno sottoposti ad analisi di sensibilità.

Al trigger si calcola lo score una volta per l’evento e si congela la destinazione. Lo stesso SAT-B viene usato per hot e cold e per tutte le velocità FSO nelle prove abbinate dello stesso evento. La destinazione può cambiare tra eventi orbitali diversi. In caso di parità si usa un criterio deterministico indipendente dalla velocità, per esempio collegamento più corto e poi ID satellite.

## Profili di capacità e trigger basato sulle risorse

Il simulatore rappresenta CPU, RAM e disco del nodo che ospita il controller. I profili sono riferimenti di deployment TeraFlow, **non specifiche hardware note dei satelliti Starlink**. La guida ETSI 7.0 riporta:

| Profilo del nodo | CPU | RAM | Disco |
|---|---:|---:|---:|
| Limitato | 4 core | 8 GB | 60 GB |
| Nominale | 6 core | 12 GB | 80 GB |
| Ampio | 8 core | 32 GB | 120 GB |

Il profilo nominale è il caso principale; limitato e ampio sono analisi di sensibilità. I valori si riferiscono al nodo fisico/virtuale di deployment, non al singolo container. [Guida ETSI al deployment di TeraFlowSDN 7.0](https://tfs.etsi.org/documentation/v7.0.0/deployment_guide/)

La riserva principale è **20% per CPU e RAM**: oltre l’80% di utilizzo si considera una condizione di pressione. Si confronteranno anche riserve del 10% e 30%. SAT-B deve inoltre avere spazio disco libero per immagini mancanti, stato operativo e riserva del 20% della capacità.

Il superamento previsto della soglia su SAT-A deve persistere per **30 campioni consecutivi** (30 s al passo scelto). Se la migrazione non è iniziata, la condizione rientra quando l’utilizzo scende sotto il 70% per 60 s. La soglia di rientro è un parametro sperimentale.

### Profilo di carico di fondo riproducibile

Per evitare che rumore casuale cambi il trigger tra prove hot/cold o tra velocità, il carico di risorse è un **tracciato sintetico deterministico**, campionato ogni secondo e riutilizzato identico in tutte le prove abbinate dello stesso evento. Non viene presentato come una misura del carico reale Starlink.

Si definisce (H_{\text{ref}}) come l’orizzonte comune ricavato dalla stima di completamento più lenta per l’evento. Per SAT-A, CPU e RAM aggregate (controller più carico di fondo nel modello) partono dal 55% e crescono linearmente fino all’85% in (2H_{\text{ref}}):

\[
U_A(t)=55\%+30\%\cdot\min\left(\frac{t}{2H_{\text{ref}}},1\right)
\]

La soglia dell’80% viene raggiunta dopo circa (5H_{\text{ref}}/3); la previsione di superamento entro (H_{\text{ref}}) si attiva quindi dopo circa (2H_{\text{ref}}/3) dall’inizio della rampa e deve restare vera per 30 campioni consecutivi. I satelliti candidati mantengono un carico aggregato di riferimento del 40% CPU e 45% RAM, che viene comunque ricontrollato dopo aver aggiunto il consumo misurato del controller ripristinato. Le curve vengono congelate prima delle prove e riutilizzate senza randomizzazione. Dopo il primo deployment, il profilo potrà essere calibrato con misure TeraFlow a carico controllato; la forma e i valori calibrati andranno poi tenuti fissi per i confronti.

### Orizzonte di previsione (H)

(H) è l’intervallo futuro entro cui si controlla il rischio che SAT-A superi la soglia; non è la persistenza del trigger. Per mantenere identici trigger e SAT-B nelle prove abbinate dello stesso evento, (H) è comune alle modalità e alle velocità: si basa sulla stima di completamento più lenta fra i casi confrontati, in genere cold a 100 Mbit/s.

\[
T_{\text{completamento, stimato}}=T_{\text{allineamento}}+T_{\text{trasferimento}}+T_{\text{ripristino/verifica}}+T_{\text{cutover}}
\]

\[
H=\left\lceil1{,}2\cdot\max(T_{\text{completamento, stimato}})\right\rceil
\]

Il fattore 1,2 aggiunge un margine del 20%; si confronteranno anche 1,0 e 1,5. Perché la previsione sia informativa, il simulatore deve rappresentare l’evoluzione del carico, per esempio tramite carico di fondo controllato; con il solo utilizzo istantaneo il trigger diventerebbe reattivo e non predittivo.

ESA descrive gli OBC come sistemi con capacità di elaborazione e memorie volatile e non volatile, ma non fornisce da questa fonte capacità numeriche per Starlink. [ESA: Onboard Computers](https://www.esa.int/Enabling_Support/Space_Engineering_Technology/Onboard_Data_Handling/Onboard_Computers)

## Canale FSO e trasferimento

La migrazione tra SAT-A e SAT-B è **single-hop** nella sperimentazione principale; il multi-hop resta un’estensione futura. Il trasferimento usa **FSO con TCP/IP**. Si assume una portata massima nominale di **1.700 km** e si richiede visibilità senza occultamento terrestre. Il contatto deve restare valido per **60 secondi consecutivi** di allineamento. Un’interruzione azzera l’allineamento; la ripresa del trasferimento dopo una perdita di link è modellata come ripartenza del trasferimento dall’inizio.

I 1.700 km sono un parametro modellistico informato da uno studio su collegamenti laser inter-satellite Starlink Phase I, non una specifica certificata di un terminale Starlink. [Chaudhry e Yanikomeroglu, 2022](https://doi.org/10.1109/OJCOMS.2022.3198391)

I 60 secondi sono un’ipotesi del modello arrotondata da un riferimento ESA che riporta circa 55 secondi per stabilire un link ottico GEO–LEO; non è una misura di un link Starlink specifico. [ESA, Laser communications](https://www.esa.int/Applications/Connectivity_and_Secure_Communications/EDRS/Laser_communications)

Si confrontano tre valori di throughput utile:

- 100 Mbit/s;
- 1 Gbit/s;
- 10 Gbit/s.

Il tempo di trasferimento è:

\[
T_{\text{trasferimento}}=\frac{8D_{\text{totale}}}{R_{\text{utile}}}
\]

Dove (D_{\text{totale}}) è il volume di immagini Docker mancanti e stato operativo in byte, e (R_{\text{utile}}) il throughput in bit/s. Si misurano i byte reali delle immagini e dello stato; non si aggiungono dati fittizi per riempire gli 80 GB di disco.

La finestra disponibile per il trasferimento è quella del contatto FSO continuo entro la scadenza operativa. Il margine di migrazione è un **risultato**:

\[
M_{\text{migrazione}}=M_{\text{orbitale}}-T_{\text{trasferimento}}-T_{\text{ripristino/verifica}}-T_{\text{cutover}}
\]

Un margine negativo significa che trasferimento e ripristino non entrano nel tempo disponibile con le ipotesi del modello. Si registra per ciascun caso senza cambiare SAT-B nelle prove abbinate.

### Fallimenti del trasferimento

Il trasporto usa TCP/IP, con controllo d’integrità. Si assume un timeout di mancato progresso di **120 s** e al massimo **3 tentativi complessivi**. Se il link si interrompe, il tentativo fallisce e la copia riparte dall’inizio dopo aver ristabilito il contatto e completato nuovamente l’allineamento. Questi parametri sono ipotesi sperimentali realistiche da documentare, non valori imposti dal protocollo TCP o da una specifica ESA.

## TeraFlowSDN, immagini e stato operativo

TeraFlowSDN Release 7 è l’implementazione concreta della funzione di controller. Le immagini Docker considerate sono quelle dei componenti:

- **Context**;
- **Device**;
- **PathComp**;
- **Service**;
- **NBI**.

La verifica dei manifest ufficiali v7.0.0 ha mostrato che **PathComp richiede due immagini, frontend e backend**: i cinque componenti logici corrispondono quindi a **sei immagini Docker da conteggiare**. Nel caso principale SAT-B parte senza le sei immagini del workload e riceve quelle mancanti.

Il deployment scelto usa **due stack Docker Compose indipendenti**, SAT-A e SAT-B, ciascuno con CockroachDB, NATS e Kafka preinstallati. Kafka è richiesto anche dall'avvio di NBI nella release verificata. Database, reti e volumi sono separati: SAT-B deve ricevere lo stato tramite l'adattatore e non tramite un database condiviso. Il consumo delle dipendenze rientra nel budget complessivo del satellite, anche se le loro immagini non vengono ritrasferite a ogni migrazione.

La configurazione è in [deploy/compose.yaml](teraflow-migration-sim/deploy/compose.yaml), con le [istruzioni di deployment e verifica](teraflow-migration-sim/docs/teraflow-compose.md). Il codice ufficiale è fissato al commit `fb8707871eba26806cac7ac373c70b2bb5bd26fc` del tag `v7.0.0`. È stato realizzato un adattamento sperimentale Docker Compose; la distribuzione ufficiale ETSI documentata per questa release usa MicroK8s. La build delle immagini è stata fatta da un filesystem Linux Docker gestito per mantenere distinti i percorsi upstream `ACL/` e `acl/`, che su Windows collidono.

La configurazione è stata avviata e verificata il **2 ottobre 2026**. Entrambi gli stack hanno superato i controlli di avvio e salute dei componenti e gli endpoint NBI hanno risposto a `/healthz` e alle richieste di lettura dei contesti. Il test di isolamento ha creato un contesto temporaneo su SAT-A, verificato che non fosse visibile su SAT-B e poi lo ha rimosso. Lo script riproducibile è [check_tfs_hosts.py](teraflow-migration-sim/tools/check_tfs_hosts.py). Questa prova verifica l’avvio e l’isolamento iniziale, non ancora il ripristino completo di una topologia e di un servizio dopo una migrazione.

Le immagini locali sono identificate per tag e image ID e le dimensioni sono registrate in [teraflow-source.json](teraflow-migration-sim/config/teraflow-source.json). La loro somma non compressa è **2.167.307.708 byte** (circa 2,17 GB), conteggiando ogni immagine per intero e quindi ripetendo gli eventuali layer condivisi. È una dimensione locale Docker, **non** il volume di byte da addebitare al trasferimento FSO: il formato dell’artefatto trasmesso e i relativi byte effettivi devono ancora essere misurati.

In laboratorio i due progetti Compose hanno reti, database e volumi separati, ma condividono lo stesso Docker Engine e la cache locale delle immagini; NBI è esposto su `127.0.0.1:18080` per SAT-A e `127.0.0.1:18081` per SAT-B. L’isolamento dei dati è stato verificato, mentre la cache comune non simula due dischi/daemon indipendenti e non prova che le immagini siano state trasferite a SAT-B. Nel modello di migrazione, SAT-B deve partire senza le immagini del workload che si assume debba ricevere. CockroachDB, NATS e Kafka sono invece dipendenze separate e preinstallate su ciascun host, con dati non condivisi.

Lo stato operativo è uno snapshot coerente che contiene contesto e topologia, dispositivi e link, servizi e connessioni attivi, vincoli e regole di configurazione necessarie al ripristino. Sono esclusi memoria volatile, processi, log, metriche storiche e cache temporanee.

Un **adattatore di migrazione**, da realizzare per l’esperimento, esporta lo stato da SAT-A e lo ricrea su SAT-B tramite le API TeraFlowSDN, nell’ordine necessario: contesti/topologie, dispositivi/link, quindi servizi. L’adattatore interroga le API e controlla la presenza e lo stato degli oggetti. La migrazione automatica dell’intero deployment non è una funzione che si assume già fornita da TeraFlowSDN.

L’ACK di SAT-B conferma immagini disponibili, controller avviato, stato ricreato e verifiche API superate. La prova end-to-end dei pacchetti dagli endpoint è una misura distinta che continua durante e dopo il cutover: distingue la prontezza del controller dall’effettivo inoltro del servizio.

## Emulazione del piano dati con Mininet e BMv2/P4

La scelta per verificare il traffico del servizio è **Mininet con switch BMv2 P4**. Mininet crea host, switch e collegamenti virtuali; BMv2 (Behavioral Model v2) esegue in software un programma P4. TeraFlowSDN configura gli switch attraverso il proprio supporto P4; il gestore di servizio **L2NM P4** rappresenta la connettività Layer 2. Mininet non è il controller e BMv2 non è un componente TeraFlowSDN.

ETSI documenta il supporto P4 per connessioni L2, cita BMv2 fra i dispositivi testati e descrive L2NM P4. Il report dell’Hackfest ETSI descrive una rete Mininet a ring di switch P4, un servizio fra due endpoint e misure basate su ping. Queste fonti sostengono la scelta architetturale ma non certificano da sole i passi esatti né la compatibilità della configurazione con la specifica immagine TeraFlowSDN Release 7; tale integrazione va verificata. ([ETSI, P4 e dispositivi](https://tfs.etsi.org/documentation/latest/supported_sbis_and_network_elements/); [ETSI, service handler](https://tfs.etsi.org/documentation/latest/supported_service_handlers/); [ETSI, Hackfest 3](https://tfs.etsi.org/news/hackfest-3/))

### Topologia e servizio proposti

La scelta è rappresentare ogni satellite del campione orbitale con uno switch BMv2 e ricavare la topologia dei collegamenti dalla geometria: gli ISL logici sono disponibili quando rispettano portata e visibilità previste. Due host Mininet rappresentano gli endpoint del servizio e si collegano a due satelliti di accesso; il percorso deve attraversare la rete, possibilmente più hop. Il numero di switch resta uguale al numero di satelliti in Worst, Base/Average e Best.

Si configura **un servizio L2** tra i due endpoint, mantenendo invariati endpoint, indirizzi e servizio in tutte le prove. Il programma P4 iniziale si limita all’inoltro necessario per quel servizio. L’orchestratore orbitale aggiorna la disponibilità dei link emulati; TeraFlowSDN riceve/modella la topologia e configura il servizio attraverso il supporto P4. La procedura precisa di aggiornamento dinamico della topologia su Release 7 resta da verificare.

Gli switch e Mininet sono emulati sul computer di simulazione, non contati nel profilo CPU/RAM dei satelliti, così il carico dell’emulatore non altera il trigger di risorse del controller. I link dati Mininet seguono la geometria orbitale durante tutta la simulazione, indipendentemente dalla migrazione del controller; non si attivano soltanto al suo completamento. Dopo l’ACK/cutover si sposta su SAT-B l’associazione del piano di controllo e di gestione dei dispositivi. I 60 secondi di allineamento si applicano al collegamento FSO usato per trasferire immagini e stato. La perdita di un ISL dati deve invece derivare dalla topologia orbitale o da un guasto controllato, non dal semplice cambio di host del controller.

### Traffico e definizione del ripristino

Si osservano entrambi i tipi di traffico:

1. **Controllo:** heartbeat e messaggi degli agenti/apparati verso il controller attivo, più i comandi di configurazione. Gli heartbeat hanno frequenza iniziale di 5 s; gli eventi e le mancate risposte si registrano separatamente.
2. **Servizio:** pacchetti inviati tra i due endpoint attraverso gli switch BMv2/P4. Si inviano ping ogni **100 ms** e un flusso UDP a **1 Mbit/s**.

Il servizio si considera stabilmente ripristinato dopo **10 sonde consecutive riuscite** (circa 1 s con ping a 10 Hz). Si registrano tempo della prima perdita, tempo al ripristino stabile, perdita, RTT, jitter e throughput. Se le sonde non falliscono durante la migrazione, si registra che il data plane è rimasto continuo; non si presume che migrare il controller interrompa automaticamente i pacchetti.

BMv2 consente di verificare l’inoltro effettivo dei pacchetti nel modello, ma non riproduce prestazioni di switch hardware o di terminali ottici reali. Mininet/P4 è quindi una verifica funzionale del piano dati, non una misura del throughput fisico di una rete satellitare.

## Protocolli hot e cold

- **Cold migration:** SAT-A resta attivo durante l’allineamento FSO di 60 s. Dopo l’allineamento acquisisce lo stato completo e interrompe il servizio del controller; poi trasferisce le immagini mancanti e lo stato a SAT-B. SAT-B avvia TeraFlowSDN, ripristina lo stato, verifica tramite API e invia l’ACK. Il downtime del controller inizia quando SAT-A si ferma e termina al cutover completato. Se SAT-B fallisce prima del cutover, SAT-A può ripartire dalla copia locale se ancora operativo.
- **Hot migration:** SAT-A resta attivo durante l’allineamento e la copia iniziale di immagini e stato. Prima del passaggio trasferisce lo stato finale/delta; SAT-B lo applica e lo verifica mentre SAT-A è ancora attivo/quiescente. SAT-B invia l’ACK; solo allora SAT-A cede il ruolo attivo. L’intera pre-copy conta nel tempo totale della migrazione, mentre il downtime riguarda la fase finale di freeze e cutover.

Il confronto principale mantiene evento orbitale, trigger e SAT-B uguali tra hot/cold e tra throughput. Il passaggio del controller avviene solo dopo ACK; il test di servizio Mininet prosegue indipendentemente per misurare se l’inoltro sia continuato o quando si sia ripristinato.

## ACK e gestione dei fallimenti

SAT-B non invia ACK e non assume il ruolo attivo se non ha avviato i componenti, ricreato lo stato e superato le verifiche API. L’ACK certifica la prontezza del controller; le sonde Mininet verificano separatamente il servizio end-to-end.

Si iniettano fallimenti controllati, ad esempio un’interruzione FSO o un mancato avvio su SAT-B. Il protocollo usa timeout di mancato progresso, ritentativi e verifica d’integrità. In caso di link interrotto il trasferimento ricomincia dall’inizio dopo nuovo allineamento. Se SAT-B non completa il ripristino, non invia ACK e non assume il ruolo attivo. SAT-A conserva la copia necessaria al recupero; se può, riavvia il controller; altrimenti l’orchestratore può provare un altro candidato.

## Misure dell’esperimento

Per ogni evento orbitale, protocollo e throughput si misurano:

- durata dell’allineamento e del trasferimento;
- byte delle immagini mancanti e dello stato effettivamente trasferiti;
- tempo di avvio, ripristino e verifica su SAT-B;
- downtime del controller e tempo dell’ACK;
- stato del servizio e riconvergenza;
- continuità del flusso Mininet, perdita, RTT, jitter, throughput e tempo al ripristino stabile;
- esito entro la finestra di contatto e la scadenza operativa;
- errori, tentativi, checksum, rollback e recupero;
- CPU, RAM, disco disponibili, utilità dello score e score dei candidati;
- trigger, SAT-B scelto, margine di migrazione e causa di un mancato completamento.

Il risultato atteso è mostrare quando la hot migration riduce l’interruzione del controller rispetto alla cold, se il data plane resta operativo durante il passaggio e in quali condizioni geometria, risorse, throughput o finestra FSO impediscono la migrazione.

## Questioni ancora da definire o validare

- selezione degli eventi di migrazione sulla configurazione orbitale già generata di 17 satelliti, verificando i candidati idonei al momento dei trigger;
- luogo terrestre, maschera di elevazione ed eventuale diversa finestra di osservazione, solo se si aggiunge un gateway terrestre;
- quanti eventi campionare per ciascun percentile. Si esegue **una replica per ogni evento selezionato in ciascun caso**; con un evento per percentile e sei combinazioni hot/cold × throughput si ottengono 18 prove principali. Questo è un confronto di casi rappresentativi, non una stima statistica con repliche multiple;
- definire il formato concreto con cui si trasferiscono le sei immagini e misurare i byte effettivamente inviati, distinguendoli dalle dimensioni locali non compresse già registrate;
- misurare CPU, RAM e disco consumati dalle sei immagini e dalle dipendenze CockroachDB, NATS e Kafka rispetto al profilo host nominale;
- verifica dell’esportazione e del ripristino tramite API nella versione Release 7 selezionata;
- formule e riferimenti per normalizzare le quattro utilità dello score;
- modello del carico di fondo e previsione CPU/RAM;
- implementazione dell’aggiornamento orbitale dei link Mininet e sincronizzazione della topologia con TeraFlow Release 7;
- misure runtime del controller necessarie per calibrare il carico sintetico deterministico e la verifica che SAT-B mantenga la riserva del 20% dopo il ripristino;
- analisi di sensibilità dei pesi score, riserva risorse, soglia di rientro e fattore temporale per (H).

## Contratto d’implementazione

Questa sezione traduce lo schema in requisiti verificabili per il prompt e per l’implementazione. Le indicazioni marcate **da decidere** non devono essere trattate dal codice come decisioni già approvate. Le prime prove devono essere ripetibili e usare le configurazioni congelate nei file del progetto; nessun risultato deve essere presentato come misura di hardware o traffico satellitare reale.

### Perimetro e componenti software

L’implementazione è greenfield nella cartella `teraflow-migration-sim`; non deve dipendere dal codice del vecchio progetto. La release TeraFlow da usare è v7.0.0 al commit `fb8707871eba26806cac7ac373c70b2bb5bd26fc`. Gli stack SAT-A e SAT-B sono quelli definiti in `teraflow-migration-sim/deploy/compose.yaml`.

Organizzare il nuovo codice in moduli con responsabilità distinguibili: caricamento scenario e configurazioni congelate; selezione degli eventi e calcolo score; orchestrazione temporale della migrazione; trasporto FSO modellato; esportazione/ripristino dello stato attraverso NBI TeraFlow; gestione ACK, timeout, retry e guasti; sonde del traffico e raccolta degli artefatti di risultato. I nomi e l’organizzazione finali dei moduli sono una scelta d’implementazione, purché queste responsabilità siano verificabili separatamente.

### Fixture e stato iniziale

Usare gli stessi ID satellite, lo stesso evento orbitale e la stessa coppia SAT-A/SAT-B in tutte le prove abbinate hot/cold e ai tre throughput. SAT-A parte con il controller e con il servizio di prova configurati; SAT-B parte con i servizi TeraFlow avviati, dipendenze locali indipendenti, nessuno stato operativo del servizio e nessuna delle sei immagini workload disponibile nel modello di trasferimento. Le immagini e le dipendenze già presenti nella cache del singolo Docker Engine di laboratorio non devono alterare il conteggio simulato dei byte.

La fixture deve definire in modo deterministico contesto, topologia, dispositivi, link, servizio L2 e connessioni da creare. Gli identificativi e l’ordine di creazione devono essere stabili tra esecuzioni. **Restano da fissare prima della prova end-to-end** il contenuto esatto della topologia fixture, i parametri dei dispositivi BMv2, gli indirizzi e i nomi/ID degli endpoint, e l’identificativo del servizio. Salvare la fixture in un file versionato e usarla sia per popolare SAT-A sia per verificare SAT-B dopo il ripristino.

### Artefatti trasferiti

Separare nel codice e nei risultati almeno due payload: immagini Docker e stato operativo. Per ogni payload registrare dimensione in byte, SHA-256, istante di inizio/fine e tentativi. Per hot migration distinguere snapshot iniziale e delta finale; per cold migration conteggiare lo snapshot completo acquisito dopo l’arresto di SAT-A.

**Da decidere prima di congelare i tempi di trasferimento:** formato effettivo dell’artefatto immagine e compressione. Una proposta riproducibile è creare un archivio delle sei immagini con `docker save`, comprimerlo in modo deterministico, trasmettere esattamente quel file e usare la sua dimensione effettiva come payload FSO. Se si sceglie questa proposta, fissare anche strumento/versione e parametri di compressione. Non usare la somma delle dimensioni non compresse da `docker image inspect` come byte trasferiti. Il payload immagini è identico per hot e cold a parità di SAT-B e di immagini mancanti; le differenze di protocollo riguardano snapshot, delta e downtime.

Lo stato deve essere esportato e ricreato usando le API NBI operative della release fissata, mai copiando direttamente il database o invocando l’import dummy come restore completo. L’adattatore deve ordinare la ricreazione di contesti/topologia, dispositivi/link, quindi servizi/connessioni, adattando l’ordine alle dipendenze effettive restituite dalle API. Le risposte API da usare, le strutture JSON richieste e i controlli di equivalenza vanno ricavati e validati contro l’istanza v7.0.0 prima della prova end-to-end. Le operazioni di retry devono essere idempotenti o rilevare e gestire gli oggetti già creati.

### Regole deterministiche di trigger, eventi e score

Usare il trigger e i pesi score definiti sopra e in `config/scenario.json`. Per ogni evento candidato registrare tempo UTC, SAT-A, insieme dei SAT-B idonei, motivazione del trigger, misure e score di ogni candidato; congelare una sola destinazione per tutte le prove abbinate di quell’evento. Un evento senza alcun candidato idoneo va registrato come evento non migrabile, non eliminato senza conteggio.

**Da precisare prima di implementare il selettore definitivo:** formule complete e limiti delle quattro normalizzazioni dello score; gestione di candidati singoli, parità e valori mancanti; popolazione di eventi su cui calcolare i percentili; regola per scegliere l’evento osservato più vicino al 10º, 50º e 90º percentile. La normalizzazione deve essere deterministica e non dipendere da hot/cold o dal throughput; lo stesso evento e la stessa destinazione devono quindi essere riutilizzati in tutte le prove abbinate.

### Macchina a stati, tempi e fallimenti

Rappresentare ogni migrazione con transizioni ed eventi temporali espliciti: trigger; allineamento FSO di 60 s; trasferimento; eventuale freeze; avvio e restore su SAT-B; verifica; ACK; cutover; eventuale rollback/retry. Applicare il throughput utile configurato al numero di byte effettivamente trasmessi. Una perdita FSO interrompe il tentativo; dopo il ripristino del link si ripetono allineamento e copia dall’inizio, con timeout di mancato progresso di 120 s e al massimo 3 tentativi complessivi.

Nel cold, SAT-A resta attivo durante l’allineamento e si arresta prima del trasferimento dello snapshot completo e dell’avvio/restore su SAT-B. Nel hot, SAT-A resta attivo durante la copia iniziale, poi si congela per il delta finale e il cutover; SAT-A non cede il ruolo prima dell’ACK positivo di SAT-B. Un ACK è valido soltanto dopo disponibilità delle immagini, avvio del controller, ripristino e verifiche API. Il fallimento di SAT-B non deve produrre un ACK positivo né un doppio controller attivo.

### Verifiche di accettazione e risultati

Prima di eseguire la matrice orbitale completa, la prova funzionale minima deve dimostrare: salute dei componenti TeraFlow su entrambi gli host; isolamento dello stato iniziale; creazione controllata della fixture su SAT-A; esportazione e restore su SAT-B; equivalenza degli oggetti previsti via API; ACK solo dopo le verifiche; passaggio o mantenimento del traffico di prova e misurazione delle sonde. Eseguire inoltre almeno una prova per ciascuno dei guasti controllati previsti e verificare retry, timeout, assenza di split-brain e recupero.

Ogni run deve produrre un record leggibile da macchina con identificativo run/evento, percentile, scenario orbitale, NORAD di SAT-A e SAT-B, modalità hot/cold, throughput, score e utilità, byte immagine/snapshot/delta, checksum, tempi di allineamento/trasferimento/avvio/restore/verifica/ACK/cutover, downtime, tentativo, trigger, esito entro finestra, stato delle sonde e causa di fallimento. Conservare insieme configurazione effettiva, versione/commit, fixture, log essenziali e checksum degli artefatti; produrre CSV aggregabile più un JSON di metadati per run.

I test automatizzati devono coprire formule e casi limite del selettore/score, transizioni della macchina a stati, calcolo dei tempi/byte, retry e validazione degli artefatti; le verifiche live delle API e del traffico devono essere distinguibili dai test unitari. Una matrice finale di prestazione va eseguita solo dopo il superamento della prova end-to-end e la calibrazione/registrazione del consumo CPU, RAM e disco nel profilo host.

### Dove reperire i dati TeraFlowSDN Release 7

- **Versione e sorgenti:** repository ETSI del [controller](https://labs.etsi.org/rep/tfs/controller), fissando il tag Git `v7.0.0` (non il branch `develop`). Il tag/commit identifica il codice da costruire.
- **Componenti, build e tag delle immagini:** guida ETSI [Deployment Guide 7.0](https://tfs.etsi.org/documentation/v7.0.0/deployment_guide/) e script del repository, in particolare `deploy/`, `TFS_COMPONENTS` e `TFS_IMAGE_TAG`. Il tag d’immagine configurato nello script non va confuso con il tag Git della release. Dopo la build si registrano nome, tag e digest di ogni immagine.
- **Dimensioni trasferite:** misurare le immagini realmente prodotte per le cinque componenti. Per il conteggio di rete usare i byte effettivamente trasferiti (per esempio l’archivio OCI/Docker o i layer scaricati dal registry), non soltanto la dimensione locale scompattata mostrata da `docker image inspect`.
- **Dipendenze:** gli script `deploy/crdb.sh`, `deploy/nats.sh`, `deploy/qdb.sh` e i manifest indicano cosa viene distribuito e configurato. La guida v7.0 associa CockroachDB e NATS a Context e QuestDB a Monitoring. Per il modello, le dipendenze di supporto sono disponibili/preinstallate sui satelliti candidati oppure esterne raggiungibili; la configurazione effettiva va scelta dopo aver verificato se Monitoring è incluso.
- **API e schema dati:** documentazione [Supported NBIs](https://tfs.etsi.org/documentation/latest/supported_nbis/) e file `.proto` nel repository della release. La documentazione espone le operazioni TFS API per contesti, topologie, dispositivi, link, servizi e connessioni. L’endpoint `dummy_contexts` non è sufficiente come restore operativo: ETSI precisa che importa nel Context database in modalità dummy e non interagisce con Device, Service e Slice. L’adattatore dovrà quindi usare le API operative e verificare il servizio attraverso le componenti interessate.

## Bibliografia e fonti

1. CelesTrak, [GP Data Formats](https://www.celestrak.org/NORAD/documentation/gp-data-formats.php), documentazione per i dati orbitali GP/TLE.
2. ETSI TeraFlowSDN, [Deployment Guide 7.0](https://tfs.etsi.org/documentation/v7.0.0/deployment_guide/), profili di riferimento del nodo di deployment.
3. ESA, [Onboard Computers](https://www.esa.int/Enabling_Support/Space_Engineering_Technology/Onboard_Data_Handling/Onboard_Computers), descrizione delle funzioni OBC e delle categorie di memoria.
4. A. U. Chaudhry e H. Yanikomeroglu, “Temporary Laser Inter-Satellite Links in Free-Space Optical Satellite Networks,” *IEEE Open Journal of the Communications Society*, vol. 3, pp. 1413–1427, 2022, [DOI: 10.1109/OJCOMS.2022.3198391](https://doi.org/10.1109/OJCOMS.2022.3198391). Fonte per lo scenario di portata LISL; 1.700 km resta una scelta modellistica.
5. ESA, [Laser communications](https://www.esa.int/Applications/Connectivity_and_Secure_Communications/EDRS/Laser_communications), riferimento per il tempo approssimativo di acquisizione del link ottico GEO–LEO.
6. ETSI TeraFlowSDN, [Supported SBIs and Network Elements](https://tfs.etsi.org/documentation/latest/supported_sbis_and_network_elements/), supporto P4 e BMv2.
7. ETSI TeraFlowSDN, [Supported Service Handlers](https://tfs.etsi.org/documentation/latest/supported_service_handlers/), gestore di servizio L2NM P4.
8. ETSI TeraFlowSDN, [TFS#3 Hackfest report](https://tfs.etsi.org/news/hackfest-3/), esperienza con Mininet, switch P4, servizio tra endpoint e ping.
9. Mininet Project, [Overview](https://mininet.org/overview/), emulazione di host, switch, controller e link virtuali.
10. P4 Language Consortium, [Behavioral Model (BMv2)](https://github.com/p4lang/behavioral-model), switch software di riferimento per testare data plane P4.
