# Verifica dei costi e delle ridondanze nella preparazione

Verifica del 4 novembre 2026, basata sul codice corrente e sui log locali.
Non sono stati modificati codice applicativo, controller o configurazioni.

## Ambito e limite della verifica

Il job `job-491a66551ab047778309088be9c2cfd7` risultava in esecuzione
durante l'analisi, nella preparazione Cold della calibrazione. Non sono state
eseguite prove live che saltano fasi: interferirebbero con le misure in corso.
L'audit identifica costi osservati e candidati, non dimostra l'equivalenza
sperimentale di un percorso abbreviato.

## Misure della prova corrente

Fonte: `results/jobs/job-491a66551ab047778309088be9c2cfd7/events.jsonl`.
I tempi sono arrotondati; il caricamento era ancora parziale.

| Operazione | Secondi |
| --- | ---: |
| Disponibilità Mininet/P4 | 0,11 |
| Arresto destinazione | 0,60 |
| Avvio sorgente complessivo | 87,92 |
| di cui attivazione API | 48,00 |
| Pulizia sorgente | 62,14 |
| 44 POST di creazione dispositivi | 272,17 |
| 44 GET di verifica dispositivi | 5,36 |

Avvio complessivo e sottofase API non si sommano. I tempi API sono somme
delle richieste completate nel campione, non una misura dell'intero caricamento.

## Risultati sul codice

1. `LiveBackend.reset()` esegue sempre `cleanup(export())`, poi `restore(initial)`.
   `cleanup()` elimina servizi, collegamenti, dispositivi, topologie e contesti
   del documento. Il percorso forza pertanto la ricostruzione dell'inventario,
   anche se una parte fosse già corretta. È il candidato principale, ma i log
   non conservano un confronto completo prima della pulizia che consenta di
   dire quanti oggetti fossero effettivamente riutilizzabili in questa prova.
2. `TfsAdapter.restore()` sa già saltare oggetti uguali e aggiornare dispositivi
   esistenti. `reconcile()` gestisce anche rimozioni e regole residue. Questo
   offre una base per una preparazione incrementale, ma non è una sostituzione
   già validata: impostazioni di connessione cambiate e dispositivi non validi
   richiedono trattamento specifico. Lo stato hardware P4 va verificato oltre
   all'inventario API.
3. Nel restore i contesti desiderati sono scritti prima delle topologie e poi
   attraversati nuovamente nel ciclo generale che usa l'inventario precedente
   alla creazione. Con inventario vuoto un contesto desiderato viene quindi
   inviato due volte. Duplicazione di scrittura confermata dal flusso di codice;
   eliminabilità e assenza di effetti collaterali richiedono un test mirato.
   Il guadagno atteso è piccolo rispetto alla ricreazione dei dispositivi.
4. `export()` legge fino a due snapshot consecutivi equivalenti; `cleanup()`
   rilegge poi lo stato. Sono letture sovrapposte ma con finalità diverse
   (stabilità e presenza corrente): non sono automaticamente eliminabili.
5. `start_source()` esegue sei gruppi Compose in ordine con `--wait`.
   Dai soli tempi non si distingue avvio necessario da attesa ridondante.
   Inoltre `shutdown()` può arrestare i controller: tra prove successive
   non si può presumere che siano già avviati.
6. Controlli infrastrutturali, ripristino autorità e baseline sono distinti:
   verificano rispettivamente connessioni, proprietà del controllo e forwarding.
   Non sono duplicati. `baseline_ready()` richiede ping freschi consecutivi e
   autorità P4; l'UDP è diagnostico, non una condizione di ammissione.
7. `reset()` confronta alla fine gli identificativi delle entità attese e lette.
   Questa verifica da sola non prova che configurazioni, regole e hardware siano
   identici: non basta come criterio per saltare pulizia e ricostruzione.

## Riscontro storico

Fasi concluse con `success: true` nei file
`results/runs/*/preparation-operations.jsonl` al momento dell'analisi:

| Fase | Campioni | Min / mediana / max, secondi |
| --- | ---: | --- |
| infrastruttura | 45 | 0,06 / 0,13 / 0,29 |
| avvio sorgente | 39 | 3,36 / 60,24 / 94,95 |
| pulizia sorgente | 36 | 2,80 / 17,08 / 78,63 |
| caricamento scenario | 31 | 29,69 / 36,10 / 536,15 |
| ripristino autorità | 31 | 0,64 / 0,86 / 26,09 |
| baseline | 31 | 1,10 / 1,25 / 1,48 |

Campioni eterogenei, potenzialmente di revisioni e dimensioni di scenario
diverse; una fase riuscita non implica che l'intera prova sia riuscita.
Non usare queste mediane come previsione del caso corrente a 64 dispositivi.

## Validazione ancora necessaria

A laboratorio libero, acquisire lo stato API e P4 prima della pulizia e
confrontarlo con il documento desiderato. Eseguire poi un confronto completo
contro incrementale, cambiando una sola fase alla volta, con gli stessi input.
Verificare configurazioni e regole, assenza di oggetti residui, isolamento della
destinazione, autorità, ping freschi e risultato della migrazione. Ripetere con
avvio pulito, esecuzione consecutiva e recupero dopo interruzione. Confrontare
anche lo stato delle cache e le condizioni iniziali delle misure Cold/Hot.
Fino a queste prove non è dimostrato un risparmio sicuro end-to-end.
