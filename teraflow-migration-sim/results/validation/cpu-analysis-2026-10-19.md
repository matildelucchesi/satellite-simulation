# Analisi CPU delle sei calibrazioni FSO

Analisi offline del 19 ottobre 2026; nessuna modifica al modello o al laboratorio.

## Risultato principale

Il massimo di 4,0817 core equivalenti compare il 16 ottobre alle 11:38:04,545 UTC (13:38:04 ora italiana), nello slot sorgente sat-a della prima calibrazione hot, `run-bbfd97d308f2468fbcf4fdc43cc6b2b8`. È precedente di 13,414 secondi al riferimento di inizio migrazione salvato nei metadata e appartiene alla finestra di baseline, prima degli eventi di protocollo.

Campioni dello stesso slot attorno al picco:

| Secondi rispetto all'inizio migrazione | Core equivalenti |
|---:|---:|
| -27,62 | 1,6329 |
| -20,26 | 0,8730 |
| -13,41 | 4,0817 |
| -6,07 | 1,2806 |
| +0,41 | 0,9208 |
| +7,71 | 0,8232 |

Il picco è isolato nei campioni adiacenti. Non è possibile ricostruirne la durata esatta: `docker stats --no-stream` fornisce una misura su un intervallo interno e il collettore attende altri cinque secondi dopo la chiamata. Le letture qui distano circa 6–7 secondi, senza copertura continua.

## Massimi per prova

| Prova (prefisso ID) | Metodo | Massimo core | Slot | Operazione contemporanea / finestra |
|---|---|---:|---|---|
| run-6432dfbc | cold | 3,5874 | sat-b | api_restore |
| run-4f8b3691 | cold | 3,3594 | sat-b | api_restore |
| run-da5ae7d6 | cold | 3,9704 | sat-b | queued_topology_apply |
| run-bbfd97d3 | hot | 4,0817 | sat-a | baseline |
| run-ec606f1f | hot | 3,3307 | sat-a | baseline |
| run-8c3ca5d5 | hot | 3,7189 | sat-a | image_load_shared_daemon |

La fase descrive l'operazione globale contemporanea, non identifica la causa della CPU nello slot. Ad esempio, mentre si caricano immagini per la destinazione può lavorare anche la sorgente. Prima della migrazione sono già attivi osservazione e aggiornamenti del controller.

## Distribuzione osservata

Applicando lo stesso filtro della calibrazione (almeno nove container attivi nello slot), risultano 245 campioni slot-tempo: mediana 1,2806 core, percentile 95 empirico 3,2805 core (indice floor(0,95*(N-1))), 32 campioni sopra 2,4 core, circa il 13,1%. Non sono percentuali del tempo: campionamento e presenza dei due slot variano, specialmente fra hot e cold. La mediana non è una misura del solo regime stabile.

Sono presenti superamenti anche nelle finestre di allineamento e dopo il completamento del protocollo. Non è quindi corretto attribuire tutti i picchi al solo avvio o alla sola migrazione.

## Cosa misuriamo e cosa manca

`src/measurements.py` somma le percentuali CPU Docker di tutti i container con prefisso sat-a- o sat-b-, dividendole per cento. I JSON conservano soltanto il totale dello slot e il numero di container, non le misure dei singoli componenti. Sono inclusi workload e dipendenze; non sono misurati direttamente i costi esterni ai container, come il daemon Docker. Non è una misura della capacità equivalente di un processore satellitare.

`src/preparation.py` prende il massimo di tutti questi campioni come domanda CPU del controller. Il planner usa poi quel massimo come domanda fissa. L'esclusione attuale è quindi coerente con la regola conservativa implementata, ma i dati non dimostrano un fabbisogno costante di 4,0817 core.

Per decidere una diversa politica con sufficiente evidenza serve una misura per container e per fase, includendo una finestra stabile dopo l'assestamento, e idealmente contatori CPU cumulativi per stimare medie temporali. Andrebbero distinti regime, ripristino e picchi prima di cambiare ammissione o risorse. La soglia di 2,4 core viene realmente superata più volte: sostituire semplicemente il massimo con la mediana non è giustificato.

## Fonti e riproducibilità

Identificatori in `results/calibration.json`; per ciascun run, `resources.jsonl`, `metadata.json` e `operations.jsonl`. Le operazioni vengono datate alla conclusione: l'inizio è ricostruito sottraendo `elapsed_s`. Fuori dagli intervalli delle operazioni si usa l'ultimo evento di protocollo; prima del primo evento la finestra è denominata baseline.

La proiezione dei 245 campioni analizzati, con ID completo, slot, timestamp, CPU e fase, è in `cpu-samples-analysis.json`. Non sono state avviate nuove prove né modificati i parametri scientifici.
