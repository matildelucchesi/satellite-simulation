# Responsabilità e risultati delle migrazioni

Il protocollo hot/cold rimane in `orchestrator.py`. Il modulo `handover.py` aggiunge il controllo del servizio dopo il cutover ed è usato sia dalle prove singole sia dalle sessioni continue. Il backend esegue operazioni Docker, API e sonde; i coordinatori decidono quale esperimento eseguire. `jobs.py` conserva l'esclusività del laboratorio.

## Accettazione

I nuovi risultati delle migrazioni hanno schema 4:

- `migration_completed`: il protocollo ha confermato il cutover.
- `service_verification.success`: autorità della destinazione, API disponibile e dieci ping freschi consecutivi verificati dopo il cutover.
- `observation_complete`: osservazione prevista completata. Nel continuo la conferma del servizio costituisce la finestra di osservazione dell'handover; la sessione continua poi a osservare il laboratorio.
- `experimental_valid`: throughput del bundle almeno pari al 90% del rate richiesto.
- `recovery_required`: il laboratorio richiede recupero prima di un altro job.
- `success`: accettazione complessiva, derivata dai campi precedenti e dall'assenza di interruzioni o errori finali.

Un cutover può essere avvenuto anche quando la prova è interrotta o non valida. L'ACK registrato non prova da solo l'accettazione. Una cancellazione dopo la verifica del servizio interrompe l'osservazione, conserva la destinazione verificata e non provoca un rollback per il solo annullamento.

I risultati storici mantengono gli esiti originali; il lettore aggiunge `null` per le evidenze mancanti senza inventare nuove verifiche. I riepiloghi delle sessioni hanno schema 2, i confronti schema 3. Endpoint e comandi restano gli stessi.

## Recupero

Ogni job salva `active-checkpoint.json` prima di modificare il laboratorio. Il checkpoint identifica prova o sessione, input, slot e fase. Gli eventi aggiornano fase e tempo del solo figlio attivo. Fra due prove viene scritto uno stato esplicito.

Un risultato figlio che richiede recupero viene propagato fino al job e conserva il lock. Anche un errore di cleanup conserva il lock. Il recupero di una sessione non riprende mai il clock. Per i vecchi job con più prove e senza checkpoint non si sceglie una prova arbitraria: vengono revocate le autorità, fermati entrambi i workload e mantenuta la richiesta di recupero.

## Misure

Il downtime è stop/freeze → cutover del tentativo riuscito. La durata della migrazione è trigger → cutover. Verifica del servizio e osservazione finale hanno durate separate. Errori, recuperi e indisponibilità dei tentativi falliti restano nella cronologia.

Il throughput delle immagini considera il solo bundle; i tentativi includono il primo trasferimento e i retry sono tentativi meno uno. Il recupero ping è una latenza di conferma di dieci risposte consecutive dopo la prima perdita, non una misura esatta del downtime. I campioni sono limitati alla finestra della migrazione. Nessuna perdita, recupero non osservato e misura mancante sono condizioni distinte.

Console e report usano la proiezione comune delle metriche. Le campagne registrano identità, run e casi attesi della propria esecuzione; casi estranei e duplicati non completano la matrice. Una campagna completamente eseguita può contenere fallimenti sperimentali validi, ma non prove interrotte o non valide.

## Confini mantenuti

Geometria, trigger e formule scientifiche non vengono cambiati da questo consolidamento. Rimangono separati il modello FSO e il trasferimento TCP reale, le risorse sintetiche dei satelliti e quelle misurate dei due slot Docker. La comunicazione radio non è introdotta. L'uso dei file ricevuti come fonte del restore e la revisione degli strumenti di manutenzione restano interventi successivi.
