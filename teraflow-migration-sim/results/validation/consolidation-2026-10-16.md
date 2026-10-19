# Consolidamento: esiti e validazione — 16 ottobre 2026

Implementate le correzioni di recupero e checkpoint, la verifica condivisa del servizio dopo ogni handover, il contratto degli esiti, le metriche comuni e i controlli condivisi di preparazione. Endpoint e comandi esistenti sono conservati. I confini sono descritti in [Responsabilità e risultati](../../docs/consolidated-results.md).

## Verifiche riuscite

- Suite: 112 test raccolti, 103 passati nell'ambiente locale e i 9 P4 passati nel container. Parsing di 89 file Python e controllo sintattico JavaScript riusciti.
- Corrispondenza numerica verificata fra API, CSV e riepilogo hot/cold.
- [Coppia FSO](../comparisons/compare-f7846866871e459499cd0dbaabe10e2c/metadata.json): stesso evento, 1 Gbit/s, un tentativo per modalità, baseline e servizio verificati, osservazione completata.
- [Sei calibrazioni](../calibration.json) riuscite: tre cold e tre hot, con fingerprint corrispondente al codice corrente. Orizzonte calibrato: 560 s.

| Misura | Hot | Cold |
|---|---:|---:|
| Downtime controller (s) | 21.037 | 232.446 |
| Trigger → cutover (s) | 278.588 | 293.839 |
| Verifica servizio (s) | 1.248 | 1.101 |

## Validazione continua non completata

Il [job di validazione](../jobs/job-b91cb685c3034bc89e411c051f8e44d0/result.json) ha rifiutato l'ammissione hot prima di modificare il laboratorio. Un [controllo separato cold, solo di pianificazione](continuous-cold-admission/admission.json), ha confermato il rifiuto. Nessun handover live continuo è stato eseguito; non viene dichiarato un successo di tre handover per modalità.

La CPU di picco misurata è 4.0817 core. Il profilo attuale è 6 core; carico di fondo candidato 40% e riserva 20% lasciano al controller 2,4 core. Il carico proiettato è quindi circa 108% della capacità: nessun candidato soddisfa la riserva. Il modello e i parametri non sono stati cambiati per ottenere un'ammissione.

Questa condizione va risolta con una decisione successiva sulle ipotesi di risorse o sul carico del controller. Il continuo resta non validato fino al superamento delle prove richieste.

## Stato finale

Lock rilasciato, autorità su B, 17 switch attivi e 17 master P4 confermati, sonde terminate. Le evidenze precedenti sono conservate. Il [report generale](../report/index.html) è stato rigenerato.

[Riepilogo completo JSON](consolidation-2026-10-16.json).
