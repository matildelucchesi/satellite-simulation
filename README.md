# TeraFlowSDN — laboratorio di migrazioni satellitari

Il programma confronta due strategie di migrazione del controller TeraFlowSDN fra satelliti LEO, **Hot** e **Cold**, misurando downtime del controller, durata della migrazione e continuità del traffico. L'orbita (due piani Starlink reali, 3 laser per satellite) fornisce eventi realistici; la migrazione viene eseguita davvero in un laboratorio Docker con TeraFlowSDN 7.0, Mininet/BMv2 e P4Runtime. Il progetto applicativo è in [`teraflow-migration-sim/`](teraflow-migration-sim/); la console locale è sulla porta **18092**.

- **Hot**: la destinazione si prepara mentre la sorgente controlla ancora la rete; dopo un breve freeze si trasferisce il delta e si passa l'autorità.
- **Cold**: la sorgente si arresta, lo stato viene trasferito e ripristinato sulla destinazione, poi si passa l'autorità.

## 1. Prerequisiti

- **Python 3.13** e PowerShell (percorso Windows).
- **Docker Desktop con engine Linux** e Docker Compose.
- I materiali del laboratorio: immagini Docker TeraFlow con le patch previste, immagini Mininet/P4, file P4 e bundle registrati nei manifest (vedere il punto 3).

Durante un esperimento mantenere accesi PC, sessione Windows e Docker.

```powershell
py -3.13 --version
docker version
docker compose version
```

`docker version` deve mostrare anche il server.

## 2. Installare le dipendenze Python (solo la prima volta)

```powershell
cd C:\UNIFI-workspaces\satellite-simulation\teraflow-migration-sim
py -3.13 -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

Tutti i comandi successivi si eseguono da `teraflow-migration-sim`, con l'interprete `.venv`.

## 3. Verificare i materiali del laboratorio

L'avvio usa `--no-build` e **non costruisce le immagini**: devono essere già presenti.

```powershell
docker compose --env-file deploy/lab.env -p teraflow -f deploy/stack.yaml config --quiet
docker compose --env-file deploy/lab.env -p teraflow -f deploy/stack.yaml config --images
```

Su una macchina nuova seguire la [guida di deployment](teraflow-migration-sim/docs/teraflow-compose.md). Non sostituire bundle o immagini con archivi generici: il programma verifica provenienza e checksum degli input.

## 4. Preparare lo scenario (una volta)

Lo scenario si calcola offline una sola volta e resta congelato con i suoi hash: si rigenera solo se cambiano TLE, piani, parametri dei laser o dominio.

```powershell
.\.venv\Scripts\python.exe tools/build_scenario.py
.\.venv\Scripts\python.exe tools/install_scenario.py
```

`build_scenario.py` scrive il profilo `artifacts/constellation-profiles/starlink-53-463-2x31/`: due piani adiacenti del guscio 53°/463 km (31 + 31 satelliti), replay orbitale di 24 ore, collegamenti laser secondo per secondo, dominio del controller di 16 satelliti (8 + 8) e catalogo degli eventi di migrazione. `install_scenario.py` archivia la configurazione precedente nel profilo e installa il nuovo scenario in `config/` e `results/`. Su Windows, se la fixture cambia, fermare prima Mininet e proxy P4 (`--resume` completa un'installazione interrotta, `--refresh` aggiorna un profilo ricostruito) e riavviarli dopo.

## 5. Avviare laboratorio e console

```powershell
.\.venv\Scripts\python.exe tools/lab.py start
```

Il comando verifica Docker, avvia il gruppo Compose **teraflow** (SAT-A, SAT-B, Mininet/P4) attendendo i servizi, poi avvia la console su **[http://127.0.0.1:18092/](http://127.0.0.1:18092/)** e la apre nel browser. Se un job detiene il lock del laboratorio, lo stack resta invariato. Opzioni: `--no-stack` (solo console), `--no-browser`; `tools/lab.py status` mostra Docker, lock, container e console. La console si chiude con **Ctrl+C**; i job proseguono nel worker.

## 6. Eseguire l'esperimento

Nella console:

1. **Laboratorio** è la pagina iniziale. In alto: lo stato del laboratorio, i sei componenti come canali con LED e la durata dell'ultima verifica e dell'ultimo esperimento su un asse in minuti. Sotto, due procedure distinte con il downtime Hot e Cold dell'ultima esecuzione: **Esegui verifica** (una migrazione Hot e una Cold sul primo evento, circa 15 minuti) e **Avvia esperimento** (un riscaldamento più 5 repliche di Hot e Cold su ciascuno dei 5 eventi: 51 prove, circa 5 ore e mezza; l'asse ne mostra la stima). Le spiegazioni e le date stanno nei punti informativi *i*. Durante un job l'asse mostra il tempo trascorso, il riquadro del job la fase in corso e il registro; **Interrompi** mette in sicurezza il laboratorio.
2. **Scenario** mostra i due piani orbitali con la Terra al centro e i satelliti in movimento: gialli al sole, blu in ombra, viola quello che ospita il controller; la zona d'ombra di ogni anello e il lato notturno della Terra seguono i satelliti eclissati. Quando parte una verifica o un esperimento la console apre questa pagina e la vista segue la prova: l'orbita resta ferma a T−30 s durante la preparazione del laboratorio, poi avanza di un secondo orbitale al secondo; al trigger si evidenzia il percorso multi-hop verso la destinazione, con un'etichetta che indica la fase in corso e il downtime del controller, e il pannello laterale elenca tutte le fasi con le loro durate. Senza job la pagina mostra in anteprima l'evento scelto, più veloce del reale; sotto ci sono il profilo installato e i 5 eventi; nel pannello compaiono anche replica e numero della prova.
3. **Risultati** mostra, per ogni evento, downtime, durata, ping persi, fattibilità rispetto all'ombra e al percorso, Cold − Hot, le fasi misurate e i file scaricabili.

Da riga di comando, con il laboratorio avviato:

```powershell
.\.venv\Scripts\python.exe tools/experiment.py functional --wait
.\.venv\Scripts\python.exe tools/experiment.py compare_events --wait
```

Ogni evento parte 15 minuti prima che il satellite sorgente entri in ombra. I 5 eventi coprono migrazioni di portata diversa: 1 salto sullo stesso piano, 1 salto verso l'altro piano, 3, 5 e 7 salti (l'ultimo verso l'altro piano). In questa costellazione ogni salto verso i satelliti che seguono sull'orbita dà circa 3 minuti di luce in più alla destinazione; la destinazione deve restare al sole almeno 10 minuti, con un percorso stabile per 15. Il clock orbitale scorre durante la migrazione. Migra solo lo stato del controller: il software è già a bordo di ogni satellite. La velocità del collegamento è 1 Gbit/s; ogni collegamento laser ha il ritardo di propagazione della sua lunghezza (circa 4–5 ms per salto nel piano), applicato sia al servizio in Mininet sia al trasferimento dello stato.

**Disegno dell'esperimento.** Hot e Cold di uno stesso evento partono dallo stesso istante orbitale e usano lo stesso percorso; il laboratorio viene preparato da capo prima di ogni prova. Dopo una prova di riscaldamento (esclusa) si eseguono 5 repliche, una dopo l'altra su tutti gli eventi; in ogni coppia l'ordine Hot/Cold è estratto a caso con un seme registrato nei risultati. Per ogni evento si riportano mediana e quartili di downtime e durata, e la differenza Cold − Hot appaiata con un intervallo bootstrap al 95 % della mediana. Una prova non riuscita resta mancante e l'esperimento prosegue; si ferma se serve il ripristino del laboratorio o dopo 3 prove non riuscite di fila. Le misure assenti restano "non misurato".

**Ipotesi dell'allineamento.** Prima di ogni tentativo il percorso multi-hop deve restare disponibile per 60 secondi di fila. È un'ipotesi prudente: i laser fra satelliti vicini sono già puntati e non lo richiederebbero. Pesa allo stesso modo su Hot e Cold e non entra nel downtime, ma allunga la durata della migrazione.

## 7. Dove sono i risultati

Relativi a `teraflow-migration-sim/`:

- `results/event-comparisons/events-*/`: esperimento a eventi (`metadata.json`, `summary.csv`).
- `results/comparisons/compare-*/` e `results/functional-gate.json`: verifiche.
- `results/runs/run-*/`: evidenze di ogni migrazione (input, fasi, autorità, sonde, baseline).
- `results/jobs/job-*/`: stato, eventi e log del worker.

## 8. Interrompere, recuperare e spegnere

Per fermare un job usare **Interrompi** nella console, oppure:

```powershell
.\.venv\Scripts\python.exe tools/experiment.py jobs
.\.venv\Scripts\python.exe tools/experiment.py stop --job-id job-IDENTIFICATIVO
```

Se un job richiede il ripristino (o il worker è morto con il lock presente) usare **Ripristina laboratorio** oppure:

```powershell
.\.venv\Scripts\python.exe tools/experiment.py recover --wait
```

Non cancellare a mano `results/jobs/lab.lock`. Per spegnere, senza job attivi:

```powershell
.\.venv\Scripts\python.exe tools/lab.py stop
```

## Il satellite di riferimento: Starlink

Il modello prende come riferimento la struttura dei satelliti Starlink descritta da SpaceX nella pagina [Tecnologia satellitare](https://starlink.com/it/technology) (consultata il 7 novembre 2026). Il disegno riporta i componenti che contano per la simulazione; posizioni e proporzioni sono indicative.

![Schema del satellite Starlink](teraflow-migration-sim/docs/img/starlink-satellite.svg)

| Componente (dichiarato da SpaceX) | Ruolo nella simulazione | Stato nel simulatore |
| --- | --- | --- |
| **3 laser spaziali** (collegamenti ottici intersatellitari, ISL), fino a 200 Gbps | Canale della migrazione e dei percorsi multi-hop fra satelliti | Modellati: 2 verso i vicini dello stesso piano e 1 verso l'altro piano, con allineamento di 60 s per i collegamenti che si formano durante la giornata |
| **5 antenne phased array in banda Ku** | Collegamento con i terminali utente a terra | Non modellate. Candidate per la futura variante radio |
| **3 antenne dual-band Ka/E** | Collegamento con le stazioni di terra (gateway) | Non modellate. Candidate per la futura variante radio |
| **2 pannelli solari + batteria** | Il satellite è pienamente operativo solo al sole: l'ombra è l'evento che richiede la migrazione | Modellati come periodi di illuminazione dal replay orbitale |
| **Propulsore elettrico ad argon** | Innalzamento d'orbita, manovre e rientro a fine vita | Non modellato. Il replay usa orbite da TLE senza manovre |
| **Inseguitore stellare e 4 ruote di reazione** (una di scorta) | Assetto e puntamento, necessari anche per allineare i laser | Rappresentati solo dal tempo di allineamento (60 s) |

Ipotesi e limiti:

- La pagina indica il numero di laser ma non la loro assegnazione: 2 nel piano e 1 verso il piano adiacente è un'ipotesi di progetto.
- La portata dei laser **non è dichiarata**. I 1.700 km e i 60 s di allineamento sono parametri dello scenario (`config/scenario.json`).
- SpaceX indica una quota di circa 550 km; i due piani scelti appartengono al guscio a 53° a circa 463 km, ricavato dai TLE del catalogo.
- Le orbite derivano da TLE pubblici, la cui accuratezza è limitata: i contatti vicini al limite di portata vanno considerati incerti (ESA, *Space Debris Mitigation for CubeSats and Smallsats*, ESA-TECQI-HO-2025-003724, 11/12/2025).
- Per la variante radio, le antenne Ka/E e Ku collegano il satellite con la Terra: una migrazione via radio passerebbe da una stazione di terra (satellite → gateway → satellite).
- Il laboratorio gira su un solo host con un daemon Docker condiviso; il percorso multi-hop della migrazione è modellato, non emulato pacchetto per pacchetto.

## Problemi frequenti

- **Docker non raggiungibile:** avviare Docker Desktop con engine Linux e attendere che `docker version` mostri il server.
- **Immagine, bundle o file mancante / checksum errato:** ripristinare i materiali previsti dai manifest (punto 3).
- **Porta 18092 occupata:** la console è probabilmente già avviata.
- **Pulsanti disattivati:** laboratorio occupato da un job, ripristino necessario o scenario non installato.
- **Prova fallita in preparazione:** leggere fase, motivo e log nel job (`results/jobs/job-*/`).

## Documentazione e verifiche locali

- [Piano di riprogettazione e avanzamento](teraflow-migration-sim/docs/piano-riprogettazione-simulatore.md)
- [Deployment e immagini Docker](teraflow-migration-sim/docs/teraflow-compose.md)
- [Adapter di stato TeraFlow v7](teraflow-migration-sim/docs/tfs-v7-state-adapter.md)
- [Descrizione tecnica](teraflow-migration-sim/README.md)

Test locali, dalla cartella applicativa:

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
node --test tests/test_experiment_state.cjs tests/test_orbit_motion.cjs
```

I test locali non sostituiscono la verifica live del laboratorio.
