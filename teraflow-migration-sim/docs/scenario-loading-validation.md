# Caricamento dello scenario: budget e diagnosi

Il collaudo `20261023T072421Z` si è fermato durante la preparazione: 20 registrazioni NBI di dispositivi completate, media 5,588 s; la ventunesima è stata interrotta dal limite fisso di 120 s. Gli artefatti originali restano invariati.

## Correzione

Il budget predefinito del ripristino è `120 + 10*dispositivi + 2*link + regole_aggiuntive + 30*servizi` secondi. Le regole aggiuntive sono le regole dei dispositivi diverse da `_connect/`. I coefficienti sono configurabili in `live.restore_budget_coefficients_s` con chiavi `base`, `devices`, `links`, `additional_rules`, `services`; ogni valore deve essere finito e positivo. `live.preparation_budgets_s.restore_scenario` resta un override vincolante, anche se inferiore al calcolato: questa condizione è esplicitata nelle evidenze.

Il totale della preparazione è la somma delle sottofasi effettive. Il calcolo è congelato in `preparation-budget.json`; nessuna scadenza viene estesa in corso d'opera. Ogni chiamata NBI resta limitata a 30 secondi e al residuo disponibile.

`restore-operations.jsonl` conserva inizio/esito delle chiamate, entità, durata, errori e contatori. API ed eventi conservano entità corrente, ultima chiamata, dispositivi/link/servizi completati e verifica finale. Un'entità è contata solo dopo tutte le sue operazioni. Lo snapshot deve raggiungere letture equivalenti e contenere gli identificativi attesi; baseline e verifica del forwarding restano controlli distinti.

La console mostra i contatori reali e i limiti della sottofase, senza percentuali o stime di conclusione. Una risposta HTTP con corpo vuoto resta un fallimento. Un errore di caricamento è `preparation_failed`, mentre `invalid_baseline` identifica il fallimento della verifica iniziale del servizio. Nessun clock o nuovo confronto viene avviato dopo un caricamento incompleto.

## Verifica

Le prove automatiche coprono 64 registrazioni sequenziali da 5,6 s, formula/override, coefficienti non validi, entità fallita non contata, timeout chiamata/sottofase, HTTP, cancellazione, budget esaurito e ricostruzione del progresso. Gli esiti della suite e della prova live sono registrati separatamente. Il successo dei test automatici non equivale al superamento del collaudo scientifico.

La prova live mirata deve precedere il nuovo launcher alle tre velocità. Nessun tentativo è rilanciato automaticamente dopo un errore.
