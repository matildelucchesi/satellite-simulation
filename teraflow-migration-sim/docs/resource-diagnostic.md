# Diagnosi CPU senza modificare il modello

Avvio: `python tools/experiment.py resource_diagnostic --wait` con l'ambiente Python del progetto e il laboratorio Docker attivo. Il job conserva lock, checkpoint, recupero e cancellazione ordinari.

Esegue hot e cold sul medesimo evento FSO a 1 Gbit/s. Per ciascun run aggiunge 60 secondi di assestamento e 120 secondi di misura sorgente prima del replay; dopo migrazione, verifica e osservazione ordinaria aggiunge 120 secondi sulla destinazione. Nelle finestre diagnostiche l'orologio orbitale è fermo, le sonde restano attive e il tempo di protocollo non è incrementato da queste finestre. Il contesto è un esperimento diagnostico, non una nuova calibrazione.

`container-resources.jsonl` contiene campioni Docker per container etichettato con progetto e ruolo. CPU è espressa in core equivalenti, memoria in GiB; campi non disponibili sono null. `resource-phases.jsonl` registra confini delle finestre e operazioni concorrenti, inclusi aggiornamenti della topologia. I batch di streaming sono ricostruiti alla ripetizione di un container; un totale incompleto resta null. Le statistiche sono su campioni e non sono medie temporali. I costi del daemon Docker esterni ai container non sono compresi.

Ogni run produce analisi JSON, CSV dei campioni e dei riepiloghi per container e slot, grafici SVG/PNG. L'esecuzione produce `results/resource-diagnostics/resource-*/report.md` e un risultato JSON con identità delle prove, fingerprint e input. Non aggiorna gate funzionali, manifest scientifici o calibrazioni. Le vecchie prove senza file dettagliati hanno dettaglio per container non disponibile; non si ricostruiscono componenti dai soli totali storici.

La completezza diagnostica richiede due migrazioni riuscite, finestre stabili di 120 secondi con almeno nove servizi campionati sullo slot attivo, nessun errore di raccolta e nessuna lacuna superiore a cinque secondi nelle serie analizzate. Gli errori di telemetria non cancellano il successo tecnico della migrazione. Se il collettore non si arresta, il laboratorio richiede recupero. Un fallimento del servizio interrompe la coppia.

Il confronto a 2,4 core mostra la soglia attuale; non cambia l'ammissione. Picchi simultanei a un'operazione non dimostrano causalità. Le misure sul PC non stabiliscono automaticamente prestazioni equivalenti su processori satellitari.

Inventario e lettura dello stream usano thread distinti: un'ispezione Docker lenta non deve ritardare il timestamp di ricezione dei campioni. La cadenza registrata è quella delle letture dello stream; Docker può ripetere valori, quindi i campioni non sono necessariamente indipendenti. I grafici interrompono le linee per container sostituiti o intervalli oltre cinque secondi. L'analisi può essere salvata in una nuova directory derivata tramite `analyze(source, output_directory=destination)`, conservando gli artefatti originali.
