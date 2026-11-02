# Partenza automatica: implementazione e verifica

## Comportamento introdotto

Console e launcher richiedono soltanto la velocità e l’avvio. Le API pubbliche rifiutano satellite e tempo iniziali, anche null. Il selettore cerca una sequenza completa nel replay congelato: prima campiona ogni 300 secondi, poi visita i secondi rimanenti. Il limite configurabile è `live.departure_search_budget_s`, inizialmente 600 secondi. I controlli del pianificatore interrompono anche il lavoro interno a un candidato.

La valutazione massimizza il minimo margine fisico su contatto e disponibilità operativa di sorgente e destinazione, rispettando la riserva della sorgente. La fine programmata del piano non è usata come perdita fisica di disponibilità. Gli ex aequo favoriscono tempo e NORAD minori. Entro un budget, la migliore soluzione verificata è dichiarata parziale e non ottima globalmente; una ricerca senza candidati e non esaustiva non dimostra impossibilità.

`selection.json` conserva ricerca, input, piani e hash; `resolved_configuration` distingue i valori scelti dai parametri richiesti. Il launcher include tutte le velocità nella prima ricerca e riutilizza la selezione tramite il primo identificativo del confronto. Una variazione degli input o un piano alterato impedisce il riutilizzo. Il verificatore controlla anche l’identità della partenza fra velocità. Gli originali storici non sono riscritti.

## Prove effettuate il 22 ottobre 2026

- Suite integrata: 196 test, OK, nove saltati per i protobuf P4 non presenti sul PC. Log locale `.test-tmp/automatic-start-suite.log` nella radice del workspace.
- Dieci regressioni mirate successive: ordinamento per margine/ex aequo, tutte le velocità sulla stessa partenza, esaurimento budget, assenza esaustiva, cancellazione, rifiuto coordinate pubbliche, riutilizzo congelato, rilevamento alterazioni e CSV con diagnostica per container. Tutte passate.
- 19 test HTTP locali passati. I test richiedono accesso ai socket localhost; nel sandbox erano impediti da WinError 10013, quindi sono stati rieseguiti con i permessi necessari.
- 17 test JavaScript passati, inclusi ricerca, cause leggibili, timeout distinto dall’impossibilità e assenza di errori di piano ereditati da progressi precedenti.
- Prova soltanto modellata con effemeridi e misure precedenti: entro 20 secondi trovati tre eventi per ciascuna delle tre velocità sulla stessa partenza. Non è una nuova calibrazione compatibile né un confronto live e non costituisce accettazione scientifica.

## Revisione Impeccable

Due assessment indipendenti con ispezioni IAB hanno rilevato: controller attribuito prima della selezione, codici inglesi nelle esclusioni e ambiguità fra storico e confronto attivo. Correzioni: anteprima senza controller, etichette italiane delle esclusioni, intestazioni con riferimento esplicito al confronto e rimozione dei dizionari tecnici dal riepilogo operativo. Verificata nel browser la nuova risposta backend senza assegnazione iniziale. Assessment B ha controllato desktop e mobile 390×844 senza overflow osservato e senza errori console raccolti.

Context e detector realmente tentati, ma il motore Impeccable 0.1.5 non era installato. Nessun overlay, conteggio automatico o audit completo WCAG viene dichiarato. Questions skipped: le criticità sono state integrate nell’implementazione autorizzata.

## Limiti ancora aperti

Il collaudo precedente `pair-9f4ba7b447474019930b62e7aa2352b7` ha superato la pianificazione e avviato Hot. Dopo il cutover, autorità su sat-b ma nessun percorso geometrico del servizio in tutte le 30 osservazioni successive; nessuna risposta ping. Non si può attribuire la perdita al solo controller. Evidenza separata, senza riscrivere gli originali: `results/guided-validation/20261022T174625Z/forwarding-diagnosis.json`.

L’errore CSV relativo al campo `containers` è corretto: il CSV usa le colonne dichiarate e la diagnostica dettagliata resta nel JSON originale. Eventuali errori futuri di report vengono registrati separatamente e non sostituiscono la causa sperimentale; il verificatore rifiuta esportazioni incomplete.

L’utente ha richiesto l’esclusione delle sequenze con perdita del percorso geometrico durante una migrazione e autorizzato l’aumento del numero di satelliti se necessario. La politica `automatic-start-service-v2` / `continuous-paired-service-v3` impone un percorso fra gli estremi del servizio per l’intera operazione prudenziale, inclusa la verifica. Il pianificatore considera anche gli istanti di riapertura del percorso come opportunità di partenza. Il contatto controller-controller resta diretto; l’inoltro del servizio può usare i normali percorsi della rete.

Nel replay attuale l’intervallo continuo massimo del servizio è 1.905 s; l’operazione condivisa a 100 Mbit/s è stimata in 936 s, con riserva sorgente separata di 276 s. Questi valori sono diagnosi modellata da misure precedenti, non un nuovo collaudo. Due test aggiuntivi verificano i confini delle finestre del servizio e impediscono di sostituirvi il solo contatto fra controller.

I 17 oggetti sono già tutti quelli nei due gruppi e nella fascia 520–580 km del catalogo congelato. Entro i limiti RAAN esistenti più 0,1°, estendere la quota minima a 450 km porta a 42 candidati reali (6+36); questa estensione modifica il campione scientifico. L’utente ha successivamente scelto il campione reale. L’installazione e il successivo riequilibrio a 64 satelliti sono descritti nella sezione seguente. Nessun nuovo collaudo live viene dichiarato completato; la matrice reale resta da eseguire con calibrazioni compatibili con l’implementazione finale.


## Ampliamento autorizzato e stato finale dell’implementazione

L’utente ha scelto satelliti reali nella fascia di selezione 450–580 km. Espansioni completate sotto lock: `job-b1efb37936934a3f82e699a97b068a92` (42 oggetti) e `job-feca056e2ccc43cdbaa0a735b0a149f2` (64 oggetti, 28+36). Prima di ogni aggiornamento sono stati revocati l’autorità e arrestati controller e infrastruttura; originali copiati e hash conservati. Nessun volume Docker è stato eliminato. La verifica funzionale precedente è stata archiviata e invalidata esplicitamente, oltre all’invalidità delle calibrazioni rilevata dal fingerprint.

La ricerca completa a 17 satelliti ha escluso tutte le combinazioni nel replay sotto la politica corrente e le vecchie stime. La ricerca parziale a 42 ha trovato una soluzione con 6 s di margine. La configurazione meglio distribuita a 64 ha trovato, in una ricerca parziale di 30 s, una partenza comune con 123 s di margine minimo; tutti i piani hanno tre eventi e continuità geometrica del servizio. Sono diagnosi modellate, non nuove misure accettate. Il collaudo sceglierà nuovamente la partenza dalle calibrazioni compatibili, senza imporre questi valori diagnostici.

Stack a 64: tutti gli healthcheck passati; API Mininet `switch_count: 64`, `switches_alive: true`; 64 canali P4 e `active: null`. Suite successiva all’ampliamento: **204 test, OK, nove saltati** per protobuf P4 assenti sul PC; log `.test-tmp/automatic-start-64-suite.log`. Passati anche 12 test mirati del selettore/contratto/CSV, tre dell’espansione reale e 17 JavaScript. La successiva correzione del controllo tra configurazione risolta e piano è coperta dai test mirati del contratto.

Console verificata a desktop e 390×844: zero campi iniziali manuali, gruppo SVG di 64 satelliti, nessun controller assegnato prima della selezione, nessun overflow orizzontale osservato (documento 375 px, viewport effettivo 391 px). Per la costellazione estesa i NORAD restano leggibili su selezione/focus/hover e sui controller; le ripetizioni “Score —” non affollano la mappa. Tutti i nodi mantengono nome accessibile, tastiera e selettore alternativo. Ultimo confronto e risultati selezionati sono datati esplicitamente.

**Accettazione live ancora da eseguire sul profilo finale.** Servono nuove verifiche funzionali e sei calibrazioni; non è stato promosso alcun confronto precedente a riuscito. Il launcher unico cerca una partenza comune alle tre velocità, conserva la selezione e si ferma al primo fallimento.
