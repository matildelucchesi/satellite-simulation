# Validazione del flusso guidato TeraFlow

## Criterio di accettazione

Il rilascio richiede tre confronti live completi (100 Mbit/s, 1 Gbit/s e 10 Gbit/s), ciascuno con tre migrazioni valide per modalità sullo stesso piano, oltre a interruzione e recupero. I test automatici e la revisione visiva non sostituiscono questo criterio.

## Evidenze raccolte durante l’implementazione

| Prova | Evidenza | Esito osservato |
|---|---|---|
| Riproduzione originale | `pair-16731fd9a26946d0ae91bee91f1298aa` | Preparazione fallita; budget residuo del comando Docker circa 47 ms; nessuna baseline e nessuna esecuzione Hot/Cold. |
| Diagnostica delle dipendenze | `job-5cda4f8cd8434904b899764ac5b293b4` | Individuato Kafka unhealthy. Il comando di verifica reale completava in circa 13,7 s, oltre il vecchio timeout di 10 s. Conservata la verifica del protocollo; aggiornati timeout e frequenza dell’healthcheck. |
| Interruzione in preparazione | `job-2113c5207dc64aa2a31a077add8c1a86` | Individuato plugin Compose figlio rimasto attivo su Windows; necessaria chiusura mirata del client in questa prova. Correzione successiva verificata da test sul processo figlio. |
| Interruzione dopo la correzione Windows | `job-825307afcf714a07a66188a1bc624445` | Richiesta ricevuta, worker terminato come interrupted, lock rilasciato. Nessun confronto promosso a riuscito. |
| Baseline e operazione reale | `job-c4114afa93534416b559f26903610b1e` | Baseline valida con 11 ping consecutivi e 83 pacchetti UDP; avviato allineamento FSO della calibrazione Cold, poi interrotto intenzionalmente. |
| Separazione delle versioni | `job-326f7fe19029417d8afb58d31873daf3` | Accettazione fermata intenzionalmente dopo una correzione rilevata dalla suite; non costituisce un confronto scientifico completo. |
| Calibrazioni Cold reali | `job-363ee3b17b5c496682ff11d4a52ad6a8` | Tre repliche Cold con baseline, forwarding, validità sperimentale e osservazione completa. Downtime controller: 382,601 s; 282,149 s; 318,199 s. Sono calibrazioni individuali, non un confronto completo. |
| Perdita del processo durante Hot | `run-f2a183dcff8f46edbdd7ee396d1cc37c` | Durante il trasferimento della quarta calibrazione sono terminati worker, server e verificatore avviati dall’host gestito. Nessun risultato terminale inventato; lock conservato. Non è stata accertata una causa nel trasporto. |
| Recupero dopo perdita del processo | `job-e21970e1e6754930a4efccf8cc11542f` | Recupero esplicito completato il 21 ottobre alle 08:50:57 UTC: snapshot equivalente, autorità sorgente ripristinata, recovery_required false e lock rilasciato. |
| Avvio indipendente del collaudo | `job-6be485f5305e49efac2dfb7d61aae46b` / `pair-f472ef1b5fe04622b4592efcbeed75d1` | Sei calibrazioni riuscite. Alle 09:55:27 UTC il worker ha concluso senza avviare le sessioni: nessuna sequenza ammissibile da 53848 a 0 s. Il verificatore si è fermato prima delle altre velocità. Il suo riepilogo ha oscurato la causa con un errore del controllo processo; originale conservato e diagnosi separata in `results/guided-validation/20261021T085600Z/admission-diagnosis.json`. |
| Collaudo con partenza approvata | `job-734c571721d34befb67947aed554a0ff` | Avviato alle 14:47 UTC del 21 ottobre, NORAD 51726 a 2979 s. Tre calibrazioni Cold e due Hot valide e complete; registrazione interrotta il 21 ottobre alle 15:35:44 UTC dopo la baseline della sesta. Il 22 ottobre l’utente ha confermato la chiusura del PC o della sessione Windows. Nessuna sessione del confronto avviata, nessuna velocità certificata. |
| Recupero dopo chiusura del PC/sessione | `job-2501a93f66a6459f9467606c6907c3ff` | Tentato esplicitamente il 22 ottobre alle 12:37 UTC, esito recovery_required: proxy non raggiungibile, motore Docker assente. Avvio Docker Desktop tentato con limite di 120 s; il backend si è fermato sul socket runtime `dockerInference` non accessibile. Solo i client CLI rimasti bloccati sono stati terminati; lock ed evidenze conservati. Nessun reset dei dati Docker eseguito. |

Sono stati corretti anche i conflitti transitori Windows nella sostituzione e lettura dei file di stato. I tentativi sono limitati nel tempo e il segnale di vita non disabilita la cancellazione.

## Verifiche automatiche e interfaccia

- La suite completa successiva alla correzione del modello comprende 186 test, esito OK e nove saltati sul PC per i protobuf P4. Tutti e nove erano già passati nel container Device con le dipendenze fissate dal progetto. Le verifiche mirate successive comprendono 19 test web e regressioni sul rifiuto del piano, sulle scadenze effettive dopo la riserva di rollback e sulla configurazione iniziale esplicita.
- I test mirati coprono budget indipendenti, scadenza prima dell’avvio Docker, diagnostica, cancellazione dei processi figli, letture concorrenti Windows, validità della baseline e rifiuto delle calibrazioni raccolte su implementazioni differenti.
- I test del verificatore di accettazione controllano anche che una modifica ai dati CSV venga rilevata. Il verificatore confronta provenienza, piano, metriche JSON/CSV e tabella HTML.
- Nel browser sono stati verificati riapertura durante il lavoro, recupero della timeline, controlli con nome accessibile, navigazione da tastiera con focus visibile ed espansione dei countdown da 3 a 17 e ritorno.
- La verifica responsive ha incluso viewport mobile 390×844 senza overflow orizzontale osservato. Le screenshot di sviluppo precedenti alle ultime correzioni non sono presentate come evidenze dello stato finale.
- Due valutazioni Impeccable indipendenti hanno confermato il miglioramento del flusso guidato e richiesto di separare stato dell’esperimento e vista orbitale, chiarire le calibrazioni Cold preliminari e avvicinare Interrompi allo stato. Questi punti sono stati integrati. Il detector automatico non era installato; nessun overlay o audit WCAG completo viene dichiarato eseguito.

## Stato dell’accettazione live

**In corso: nessun confronto completo alle tre velocità è ancora certificato in questo documento.** Le prove interrotte e i test simulati non valgono come confronti riusciti.

Il 22 ottobre, dopo il riavvio completo Windows eseguito dall’utente, Docker è tornato operativo. Riavviati soltanto Mininet e proxy P4 per il recupero, il job `job-be25b3d9faf643d98c368a41055a5627` ha completato alle 13:14:34 UTC la revoca dell’autorità e l’arresto dei controller: `controllers_fenced: true`, `source_expired: true`, `recovery_required: false`; lock rilasciato. Il vecchio esperimento non è stato ripreso. Il riepilogo originale `results/guided-validation/20261021T144659Z/summary.json` resta conservato come registrato dal launcher interrotto; la diagnosi successiva è separata. La UI distingue un job di recupero fallito dalla vecchia fase di calibrazione, mantiene la configurazione dell’esperimento originario e blocca l’avvio durante il recupero. La regressione JavaScript aggiornata comprende 14 test passati. La lettura Windows dei processi è stata protetta anche da output assente, senza dichiarare morto un proprietario non verificato; la regressione mirata passa.

Il 21 ottobre l’utente ha chiarito il modello scientifico: crescita del carico sul controller ospitante dall’insediamento, candidati con carico base più impronta del controller. Sono stati corretti l’ancoraggio del carico, il trigger rispetto alla finestra operativa completa e il contratto delle riserve: il contatto copre l’operazione, mentre il rollback richiede disponibilità della sorgente; le scadenze tra eventi tengono conto della riserva che il backend sottrae. Le politiche nuove hanno identificativi distinti dallo storico.

Con queste regole e le ultime misure disponibili, una ricerca soltanto modellata ha trovato tre eventi per ciascuna velocità da NORAD 51726 a 2979 s. L’utente ha approvato esplicitamente questa partenza per il nuovo collaudo. La precedente partenza 53848 a 0 s ha contatti iniziali di 464 e 525 s, insufficienti per la finestra operativa richiesta. Le calibrazioni precedenti restano evidenze individuali; le modifiche all’implementazione richiedono nuove calibrazioni compatibili prima dell’accettazione live.

Le esecuzioni del verificatore salvano riepiloghi indipendenti in `results/guided-validation/<data UTC>/summary.json`. Un riepilogo con `complete: false` conserva un errore o una prova interrotta; non costituisce accettazione. Il rapporto verrà completato con gli identificativi dei tre confronti e i controlli finali solo dopo il loro effettivo superamento.

## Partenza esclusivamente automatica e ampliamento

Il profilo corrente è a 64 satelliti reali (28+36), selezionati nella fascia autorizzata 450–580 km. La partenza 51726/2979 citata sopra è storica e non è più imposta. La selezione esclude la perdita geometrica del servizio durante una migrazione. Implementazione, archivi, test e limiti della nuova consegna sono descritti in `automatic-start-validation.md`; nessun confronto live completo sul nuovo profilo è ancora certificato.
