# Usare il confronto guidato Hot/Cold

Aprire `http://127.0.0.1:18092/`. Un solo esperimento può occupare il laboratorio.

### Preparazione della rete prima della calibrazione

Con «Crea scenario iniziale», quando servono nuove misure, il programma crea
prima la rete completa e ne verifica il servizio. Seguono le eventuali prove
funzionali e una calibrazione Cold e una Hot. Le prove riutilizzano i dispositivi
già presenti: viene ripristinato il servizio e riconciliata la configurazione,
con nuove verifiche di API, autorità P4 e ping prima di ogni migrazione.
Connessioni dei dispositivi incompatibili richiedono un ripristino completo.

Dopo le misure viene scelta la partenza orbitale e predisposta la sorgente della
simulazione riutilizzando lo stesso inventario. Collegamenti e servizio vengono
aggiornati per l'istante scelto; la rete non viene cancellata sistematicamente.
Le calibrazioni compatibili già disponibili continuano a essere riutilizzate.

## Dalla configurazione al risultato

1. Scegliere soltanto la velocità utile del canale: 100 Mbit/s, 1 Gbit/s oppure 10 Gbit/s. Satellite e tempo iniziali sono scelti esclusivamente dal simulatore, dopo le calibrazioni compatibili. La costellazione installata e le soglie restano fisse durante ogni confronto. Il profilo attuale usa 64 satelliti reali, 28+36 nei due gruppi, dalla fascia di selezione 450–580 km autorizzata.
2. Premere **Avvia confronto Hot/Cold**. Seguire il pannello **Il tuo esperimento**, non il movimento della mappa: durante la preparazione il clock orbitale è fermo.
3. Se mancano calibrazioni compatibili, creare lo scenario con **Crea scenario iniziale**: prima viene predisposta la rete completa, poi si eseguono le verifiche funzionali necessarie e due prove di calibrazione, una Cold e una Hot. L'inventario compatibile viene riutilizzato tra le prove e nella preparazione finale. Una calibrazione precedente viene riutilizzata soltanto se implementazione, artefatti e baseline risultano compatibili.
4. Il programma cerca la partenza nell’intero replay, con risoluzione di un secondo e budget separato di 600 s (`live.departure_search_budget_s`). Prima campiona il replay ogni 300 s, poi completa i secondi rimanenti; valuta una sequenza completa per ciascuna partenza. Preferisce il maggior margine temporale minimo fisico, poi l’istante minore e il NORAD minore. Se il budget termina, usa solo una soluzione già verificata e dichiara la ricerca parziale; senza una soluzione dichiara ricerca incompleta, non impossibilità. Solo una ricerca esaustiva può concludere che non esistono partenze ammissibili. Una selezione limitata nel tempo può dipendere dalla porzione esplorata; non è dichiarata ottima globalmente.
5. Sono escluse le sequenze in cui il percorso geometrico del servizio scompare durante una migrazione. Un contatto diretto fra i due controller non basta: deve restare disponibile anche il percorso fra gli estremi del servizio.
6. Seguire **Hot → Ripristino → Cold**. Il clock procede in tempo reale. Hot prepara la destinazione prima del passaggio finale; Cold arresta la sorgente prima del trasferimento. Le due esecuzioni seguono lo stesso piano.
7. Nei risultati distinguere obiettivo, migrazioni tentate, riuscite ed eventi confrontabili. I trattini indicano misure mancanti. La differenza Cold−Hot è disponibile solo per misure valide sullo stesso piano; un valore positivo indica una misura Cold maggiore.

## Capire le attese

- **Ultimo progresso** misura il tempo dall’ultimo avanzamento osservato.
- **Processo di esecuzione** mostra un segnale di vita separato: un processo attivo può stare aspettando un servizio.
- **Tempo massimo per questo passaggio** indica la scadenza effettiva della sottofase, non una previsione di completamento.
- **Vista orbitale iniziale** è un’anteprima modellata. L’assenza di movimento durante preparazione e calibrazione è prevista.
- Le risorse orbitali e FSO sono modellate; API, TCP, autorità P4 e sonde sono verificate live. Le stime di calibrazione non sono misure del confronto corrente.
- Il carico crescente riguarda soltanto il controller ospitante e parte dall’insediamento verificato. I candidati mantengono il carico base più l’impronta del controller; il tempo trascorso dall’ingresso in luce non li rende automaticamente sovraccarichi. Il trigger anticipa la finestra operativa completa, mantenendo il tempo di recupero sulla sorgente.

## Interrompere o gestire un errore

Usare **Interrompi** vicino allo stato oppure nel pannello dei controlli. La richiesta avvia la messa in sicurezza; attendere l’esito, senza avviare altri comandi Docker in parallelo. Chiudere la scheda non interrompe il job. Riaprendo la pagina si recuperano stato e timeline salvati.

Durante le prove live devono restare attivi PC, sessione Windows e Docker Desktop. La chiusura del PC o della sessione termina i processi; non equivale a chiudere una scheda. Una sessione orbitale interrotta non viene ricostruita come se avesse continuato a misurare: richiede recupero e un nuovo avvio esplicito. Il collaudo completo può occupare il laboratorio per diverse ore.

Un errore di preparazione identifica operazione, tempo consumato, limite e servizi coinvolti. L’esito del processo e quello scientifico sono separati: un worker può terminare regolarmente dopo avere registrato un confronto fallito. Nessun nuovo confronto viene avviato automaticamente dopo un fallimento.

Se appare **Ripristino necessario**, il lock resta attivo: usare **Ripristina laboratorio**, quando disponibile, e attendere la verifica. Un recupero incompleto non deve essere aggirato cancellando il lock. Le evidenze storiche rimangono conservate; le informazioni non registrate dalle versioni precedenti sono mostrate come non disponibili.

## Verificare ed esportare i dati

In **Report e dati**, aprire il report leggibile oppure scaricare risultati JSON, piano condiviso e CSV. I file sono marcati parziali durante il lavoro e definitivi alla conclusione, anche se fallita. Verificare identificativo del confronto, identificativi delle sessioni, hash SHA-256 del piano, calibrazioni e metriche per evento. Il downtime del controller e il ripristino del forwarding sono grandezze distinte.

## Budget operativi e riproduzione del collaudo

I limiti in secondi sono configurabili in `live.preparation_budgets_s` nello scenario. Valori predefiniti: infrastruttura 120; avvio sorgente 180; avvio destinazione 180; pulizia destinazione 120; pulizia sorgente 120; scenario iniziale 120; autorità P4 60; arresto destinazione 45; baseline 60; ripristino del servizio sulla rete esistente 120. Il budget del caricamento viene calcolato dal numero di dispositivi, collegamenti, regole e servizi, salvo override esplicito. Il tetto complessivo è la somma dei limiti effettivi; ogni sottofase resta soggetta al proprio limite. Le scadenze orbitali sono separate.

Da una shell nella cartella del simulatore, con il laboratorio libero:

```powershell
.\.venv\Scripts\python.exe tools/validate_guided_flow.py --live
```

Il verificatore esegue le tre velocità in sequenza e si ferma al primo errore, conservando `results/guided-validation/<data UTC>/summary.json`. Non avvia retry. Per verificare un confronto esistente senza eseguire il laboratorio:

```powershell
.\.venv\Scripts\python.exe tools/validate_guided_flow.py --comparison pair-<identificativo>
```

Il controllo verifica piano, configurazione iniziale, baseline, tre migrazioni valide per modalità, provenienza e corrispondenza dei valori JSON/CSV. L’ispezione visiva della UI e del report HTML resta parte del collaudo.

Il launcher cerca una sola partenza comune alle tre velocità e riutilizza i piani congelati della selezione. Non accetta più argomenti per imporre satellite o tempo. Le API pubbliche rifiutano anche campi iniziali impostati a null. `selection.json` conserva la ricerca, i margini, le identità degli input e gli hash dei piani; `resolved_configuration` espone la partenza effettiva separata dalla richiesta. Una variazione degli input ferma il tentativo senza sostituzioni automatiche.

Per un collaudo lungo su Windows, aprire `tools/run_guided_validation.cmd` da Esplora file e lasciare aperta la sua finestra fino all’esito. Questo mantiene l’esecuzione indipendente dalla durata del terminale gestito di Codex. Il launcher imposta UTF-8 e conserva il riepilogo anche al primo errore. Se occorre riaprire il server della console, usare `tools/start_gui.cmd`; non avviare un secondo verificatore mentre il laboratorio è occupato.
