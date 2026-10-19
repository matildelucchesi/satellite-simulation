# Diagnosi CPU TeraFlow — risultati del 19 ottobre 2026

Implementazione e coppia diagnostica completate. Hot e cold riuscite al primo tentativo con API, autorità della destinazione e almeno dieci ping freschi consecutivi verificati. Tutte le finestre stabili sono complete; nessun errore del collettore e nessuna lacuna oltre cinque secondi. Il job non richiede recupero e il lock è stato rilasciato.

## Consumo nelle finestre a geometria ferma

Ogni finestra dura 120 secondi, dopo l'assestamento iniziale o dopo migrazione e osservazione finale. Valori in core equivalenti Docker, per singolo slot completo di dipendenze.

| Metodo | Finestra / slot | Mediana | P95 | Massimo | Campioni >2,4 / totali |
|---|---|---:|---:|---:|---:|
| Hot | Sorgente / sat-a | 1,1897 | 3,0508 | 4,4724 | 31 / 242 |
| Hot | Destinazione / sat-b | 1,0267 | 3,0364 | 3,8705 | 29 / 242 |
| Cold | Sorgente / sat-a | 1,1967 | 3,1313 | 4,0911 | 32 / 242 |
| Cold | Destinazione / sat-b | 1,0817 | 3,2458 | 4,1442 | 22 / 241 |

I campioni sopra soglia non sono una misura esatta del tempo trascorso sopra soglia. Percentili: indice floor(0,95*(N-1)). I dati sono campioni Docker, potenzialmente correlati o ripetuti, non medie temporali da contatori cumulativi.

## Quali componenti contribuiscono ai picchi

Nei quattro massimi delle finestre stabili, Kafka è il maggior contributore del singolo slot:

| Finestra | Totale | Kafka | CockroachDB | DeviceService |
|---|---:|---:|---:|---:|
| Hot sorgente | 4,4724 | 2,4848 | 0,7353 | 0,7468 |
| Hot destinazione | 3,8705 | 1,9992 | 0,7702 | 0,6950 |
| Cold sorgente | 4,0911 | 2,5682 | 0,8159 | 0,6446 |
| Cold destinazione | 4,1442 | 2,3646 | 0,7614 | 0,6877 |

I componenti restanti spiegano la differenza rispetto al totale. I massimi individuali dei componenti non vanno sommati se appartengono a istanti differenti: questa tabella usa contributi del medesimo batch.

Kafka ha mediane di circa 0,018–0,020 core nelle finestre attive ma massimi individuali di circa 2,47–2,57 core. Il deployment esegue `kafka-topics.sh --bootstrap-server localhost:9092 --list` come healthcheck ogni dieci secondi: è un candidato da investigare per i picchi periodici, non una causalità dimostrata. Non sono stati modificati né disabilitati healthcheck o servizi.

Esistono anche picchi transitori differenti: NBI raggiunge circa 6,94 core durante la preparazione hot e circa 6,14 durante la migrazione cold. I dettagli delle operazioni contemporanee sono nel file delle fasi; non bastano a provare quale chiamata interna abbia causato il consumo. Le risorse CPU dei container non sono limitate dal profilo orbitale astratto di sei core: il laboratorio misura sul processore ospite.

## Cosa possiamo concludere

Il valore storico di 4,08 core non rappresenta una domanda permanente. Tuttavia i superamenti dei 2,4 core non riguardano soltanto avvio o migrazione: sono presenti anche durante il servizio a geometria ferma. Sostituire automaticamente il massimo con la mediana nel planner non sarebbe giustificato.

Il prossimo intervento da valutare è una verifica controllata del costo dei controlli di salute e delle dipendenze; successivamente si potrà scegliere come distinguere domanda normale e picchi nel modello. In questa fase planner, risorse dei satelliti, criteri di ammissione, manifest e calibrazioni restano invariati. Non sono state avviate campagne di calibrazione o handover continui.

Una coppia e quattro finestre di due minuti costituiscono una diagnosi del deployment di laboratorio, non una caratterizzazione statistica completa né una previsione delle prestazioni su processori satellitari. Sono esclusi i costi del daemon Docker esterni ai container; il daemon e il computer ospite sono condivisi.

## Evidenze e provenienza

- Job: `job-b02c28df95274126b05a409acef77139`, 07:52:53–08:17:31 UTC.
- Diagnosi: `resource-ecda5db267b94f4e929547edc5071cbd`.
- Hot: `run-9fc28d4d941f44aab61201b7df605547`.
- Cold: `run-fc0d676806b64b389ccde469d31cd8eb`.
- Evento comune: quello salvato in `inputs.json`; velocità utile FSO 1 Gbit/s, ordine hot poi cold.
- [Risultato originale completo](result.json) e [rapporto originale dei riepiloghi](report.md).
- [Analisi hot derivata](presentation/run-9fc28d4d941f44aab61201b7df605547/resource-analysis.json), [CSV dei campioni hot](presentation/run-9fc28d4d941f44aab61201b7df605547/resource-samples.csv), [grafico hot SVG](presentation/run-9fc28d4d941f44aab61201b7df605547/resource-timeline.svg).
- [Analisi cold derivata](presentation/run-fc0d676806b64b389ccde469d31cd8eb/resource-analysis.json), [CSV dei campioni cold](presentation/run-fc0d676806b64b389ccde469d31cd8eb/resource-samples.csv), [grafico cold SVG](presentation/run-fc0d676806b64b389ccde469d31cd8eb/resource-timeline.svg).

Le viste derivate correggono esclusivamente il collegamento grafico attraverso periodi senza campioni o container fermi. Le misure, gli esiti e i file originali restano conservati. Il fingerprint di acquisizione rimane quello del risultato originale; quello dell'analisi finale è registrato in `verification.json`. Dopo la prova sono cambiati soltanto tracciamento grafico e possibilità di salvare un'analisi derivata, senza modificare raccolta, protocollo o formule statistiche.

Conservate anche le esecuzioni precedenti: `job-552edb663d16414b90df45a4e9ac3c5c`, interrotta per correggere il parsing delle righe vuote Docker, e `job-0b616bdbf50f48228b243ac166c22b3a`, con migrazioni riuscite ma diagnosi incompleta per pause di 5,5 e 9,6 secondi nella raccolta. Queste hanno motivato i test di regressione e la separazione fra lettura dello stream e inventario Docker.

Validazione software: 123 test raccolti, 114 superati sull'host e nove P4 superati nel container; controllo JavaScript positivo. I grafici finali sono stati ispezionati visivamente.
