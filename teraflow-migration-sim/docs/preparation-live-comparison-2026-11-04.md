# Confronto live: preparazione completa e incrementale

## Esito

Il 4 novembre 2026 il riutilizzo di uno scenario operativo invariato ha superato
le verifiche del programma impiegando 42,40 s, contro 554,23 s della ricostruzione
completa: 511,83 s risparmiati (92,35%, circa 13 volte più rapido).
È un singolo confronto sul caso caldo e invariato, non una validazione generale
del riutilizzo dopo migrazioni, interruzioni o cambiamenti di scenario.

| Misura | Incrementale | Completo |
| --- | ---: | ---: |
| Preparazione fino alla baseline valida, s | 42,40 | 554,23 |
| GET API, inclusi controlli aggiuntivi | 80 | 155 |
| POST API | 4 | 287 |
| PUT API | 0 | 1 |
| DELETE API | 0 | 283 |
| Inventario equivalente al riferimento | sì | sì |
| Controller destinazione arrestato | sì | sì |
| Ping consecutivi riusciti nella baseline | 11 | 11 |
| Pacchetti UDP ricevuti, diagnostici | 103 | 101 |

Non sono stati misurati tempi di migrazione Hot/Cold in questo confronto.
Il codice di preparazione applicativo non è stato modificato.

## Procedura ed evidenze

Su richiesta dell'utente è stato interrotto il precedente job di calibrazione
`job-491a66551ab047778309088be9c2cfd7`. Il risultato registrava
`cleanup_verified: true` e `recovery_required: false`: non è stato necessario
un ulteriore recupero. Nessun lock è stato cancellato manualmente.

Il confronto è il job `job-4e035e53fd91488e8013a076d7b4cc64`:

1. Acquisizione atomica del lock del laboratorio, con PID proprietario e
   possibilità di richiedere l'interruzione attraverso il normale cancel.json.
2. Preparazione completa iniziale del carico funzionale: 64 dispositivi,
   216 collegamenti e un servizio. Tempo 607,22 s, escluso dal confronto diretto
   perché parte da condizioni diverse. Salvataggio dello snapshot operativo.
3. Verifica del riferimento; preparazione incrementale che mantiene gli oggetti:
   controlli infrastrutturali, arresto destinazione, avvio sorgente, impostazione
   dei collegamenti allo stesso tick orbitale, `source.reconcile(snapshot)`,
   ripristino autorità, pulizia standby e baseline fresca.
4. Verifica che l'inventario di partenza sia ancora equivalente al riferimento;
   preparazione completa tramite `LiveBackend.reset()` e baseline fresca.
5. Verifica finale e messa in sicurezza con `shutdown()`. Il job è terminato
   `completed`, con `complete: true`, `cleanup_verified: true` e lock rilasciato.

Tempi dall'inizio di ciascuna prova fino alla baseline, inclusa la verifica
iniziale del riferimento. I conteggi API includono anche le verifiche finali
eseguite fuori da tale intervallo. Ordine fisso incrementale → completo,
una sola replica per percorso; nessuna stima statistica della variabilità.

Lo script sperimentale è `results/preparation-audit/compare_live.py`.
Le evidenze sono in `results/jobs/job-4e035e53fd91488e8013a076d7b4cc64/`:

- `inputs.json`, `events.jsonl`, `result.json`, `job.json`;
- per `seed_full`, `incremental`, `full`: snapshot, verifica e chiamate API;
- file di preparazione e startup per i percorsi completi;
- sonde in `results/lab/baseline-job-4e035e53fd91488e8013a076d7b4cc64-*`.

## Cosa è stato verificato

`TfsAdapter.verify()` confronta i contenuti canonici di contesti, dispositivi,
collegamenti, topologie, servizi e connessioni, escludendo gli ID delle
connessioni generate. Nessun tipo di entità risultava diverso.

La baseline conferma API sorgente disponibili, autorità P4 della sorgente,
switch con mastership confermata e ping freschi consecutivi. Il ripristino
P4 usa la riconciliazione hardware con rilettura delle regole. Non è stato
eseguito un dump indipendente di tutte le tabelle hardware tra le prove.
L'arresto del workload della destinazione è stato verificato via Compose;
non sono state tentate scritture ostili dalla destinazione. L'UDP è diagnostico.

## Implicazioni e limiti

Nel caso di stato già corretto, cancellazione e ricreazione integrali sono
evitabili senza perdere le verifiche qui eseguite. L'incrementale ha ricevuto
lo snapshot operativo già verificato, non il documento della fixture grezza:
questa prova non dimostra che basti sostituire una chiamata nel percorso attuale.

Il carico di calibrazione deve comunque esistere per misurare una migrazione
reale rappresentativa. Lo scenario finale della simulazione viene preparato
separatamente dopo la calibrazione. Un futuro percorso ottimizzato dovrebbe
riutilizzare lo stato solo dopo verifiche, riconciliare differenze e mantenere
il ripristino completo quando non può garantirne l'equivalenza.

Restano da provare: transizione reale Cold → Hot, ripristino dopo interruzione,
variazioni di topologia/configurazione e ripetibilità delle misure di migrazione.
Il laboratorio è stato lasciato con controller arrestati e autorità revocata;
la calibrazione interrotta non è stata riavviata automaticamente.

## Verifica dell'implementazione della nuova sequenza

La sequenza applicativa ora predispone la rete prima delle calibrazioni e
riutilizza l'inventario nella preparazione delle prove e della sorgente finale.
Il servizio viene ricreato per eliminare percorsi precedenti. Le impostazioni
di connessione incompatibili richiedono il ripristino completo.

La prima verifica del nuovo percorso (`job-8b7a1acbbc324b09992da100bf6127a1`)
ha rilevato perdita delle regole di configurazione degli endpoint scoperte dal
driver: traffico valido, ma inventario diverso. La correzione include nel
documento desiderato queste regole, ricavandole dalle impostazioni di connessione,
senza conservare le vecchie regole di inoltro del servizio.

La verifica successiva (`job-f21152fb67d94de1a4953886f1efec40`) è riuscita:
inventario equivalente, destinazione arrestata, autorità P4 verificata,
12 ping consecutivi riusciti, 107 pacchetti UDP diagnostici. Tempo 232,35 s,
inclusi riavvio da controller arrestato e ripristino dei metadati endpoint
mancanti. Nessuna creazione o cancellazione di dispositivi; le cinque POST
sono relative a contesti/topologie e servizio. `cleanup_verified: true`, lock
rilasciato. Questo tempo non è direttamente confrontabile con i 42,40 s della
precedente prova su snapshot operativo invariato.

Verifiche automatiche: 254 test Python, 9 esclusioni previste; 27 test JavaScript
superati. Non è stata ripetuta una calibrazione live Cold/Hot completa con la
nuova sequenza.
