# Confronto continuo Hot/Cold

La console `http://127.0.0.1:18092/` propone una sola operazione. Impostare la durata in secondi **per ciascuna modalità**, quindi avviare il confronto. Il trasporto della console è fissato a 1 Gbit/s. Dieci minuti per modalità richiedono circa venti minuti complessivi, più preparazione, calibrazione eventualmente necessaria e ripristino.

## Esecuzione

1. Riutilizzare una calibrazione valida per l'implementazione corrente oppure eseguire automaticamente verifica funzionale e sei calibrazioni. Una campagna già congelata non viene cancellata per forzare la calibrazione.
2. Cercare una sequenza con almeno una migrazione, fattibile per Hot e Cold. Il margine di ammissione comprende il caso più lento, la verifica del servizio e una riserva per il ripristino.
3. Salvare `plan.json` e il suo SHA-256 prima delle esecuzioni. Partenza orbitale, satellite iniziale, trigger, sorgenti, destinazioni e deadline sono condivisi. Anche l’identità del bundle di immagini, la configurazione dello scenario e la fixture iniziale vengono fissate e controllate.
4. Eseguire l'intera sessione Hot, arrestare e mettere in sicurezza i workload, quindi ricostruire lo stato iniziale e verificare nuovamente la baseline prima di Cold.
5. Eseguire Cold sullo stesso piano. Nessuna ripianificazione è consentita; un evento mancato di oltre un secondo, una deadline superata o una verifica fallita ferma il confronto. Non si cambia evento per ottenere un esito positivo.

Le due sessioni proseguono fino alla durata richiesta anche dopo l'ultima migrazione. Sono esecuzioni live sequenziali a velocità 1×, non due processi contemporanei e non un'animazione accelerata.

## Risultati e controllo

La mappa segue automaticamente la modalità in corso. Nello storico si possono selezionare Hot o Cold e consultare il replay; «Segui esecuzione in corso» riattiva l'inseguimento automatico. I pulsanti delle misure per evento aprono il replay al relativo trigger.

La tabella confronta gli eventi e mostra Cold meno Hot solo quando entrambe le prove dell'evento sono valide. Il totale del downtime del controller somma le migrazioni riuscite di una sessione completata: non rappresenta il downtime del servizio. Il forwarding deriva dalle sonde, separatamente dalla geometria e dalla conferma di autorità del controller. Valori assenti restano vuoti o `—`.

Risultati, piano, CSV e report HTML sono in `results/continuous-comparisons/pair-*/`. I dettagli delle due esecuzioni rimangono in `results/simulations/sim-*/`; i loro identificativi e lo SHA-256 comune sono registrati nel confronto. Le evidenze parziali sono conservate anche in caso di errore o interruzione. Il ripristino dopo perdita del worker conclude il confronto interrotto; non riprende il vecchio clock.

## CLI e API

```powershell
.\.venv\Scripts\python.exe tools/experiment.py compare_continuous --duration-s 600 --wait
```

`POST /api/v1/jobs` accetta `operation: "compare_continuous"` e `parameters: {"duration_s": 600, "rate_bps": 1000000000}` con la normale sessione same-origin. Il confronto non accetta un parametro `method` indipendente. La CLI conserva le opzioni di partenza, satellite iniziale e limite migrazioni; un limite incompatibile con la durata viene rifiutato.

`GET /api/v1/continuous-comparisons` elenca i confronti; `GET /api/v1/continuous-comparisons/pair-ID` restituisce lo stato e le misure. Le API precedenti di sessioni singole e prove funzionali restano disponibili per compatibilità e diagnostica da CLI, ma non compaiono più come operazioni nella console.
