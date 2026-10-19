# Implementation status — 2026-10-02

> Aggiornamento 16 ottobre 2026: il percorso principale è **Confronto FSO hot/cold**, su un evento a 1 Gbit/s con verifica API e ping. Simulazione continua e campagne rimangono funzioni avanzate con validazione separata. Avvio e criteri di successo sono nella [guida operativa](operating-guide.md).

## Consolidamento di procedure, esiti e metriche — 2026-10-16

Correzioni implementate: propagazione del recupero fino al lock del job, checkpoint del figlio attivo, verifica API/autorità/ping condivisa fra prova e continuo, esiti e metriche comuni, lettura compatibile dei risultati storici. Le responsabilità sono descritte in [Responsabilità e risultati](consolidated-results.md).

La nuova coppia FSO e sei calibrazioni sono riuscite. La suite aggiornata comprende 112 test, verificati fra host e container P4. Il continuo resta **non validato**: ammissione hot e cold rifiutata per risorse CPU. Picco misurato 4,0817 core contro 2,4 core disponibili al controller nel profilo da 6 core, con fondo 40% e riserva 20%. Non sono stati eseguiti handover continui né modificati i parametri scientifici per forzare il risultato.

Evidenze, identificatori dei job e misure sono nel [riepilogo del consolidamento](../results/validation/consolidation-2026-10-16.md).

## Confronto FSO e correzione Mininet — 2026-10-16

Il percorso principale della console è il confronto hot/cold sullo stesso evento a 1 Gbit/s. La coppia conserva input orbitali comuni, ricostruisce la fixture prima di ogni modalità e salva le misure aggregate e le differenze cold meno hot. Il successo richiede equivalenza API, ACK/cutover, autorità della destinazione e dieci ping freschi consecutivi; UDP è diagnostico.

La diagnosi live ha riprodotto il blocco della baseline: chiudere amministrativamente una singola interfaccia dello switch BMv2 arresta la ricezione anche sulle altre porte. Con le stesse regole installate, il test è passato da 2/2 ping con la porta attiva a 0/2 abbassando una porta non usata dal percorso. I contatti sono ora chiusi con `tc netem loss 100%` in entrambe le direzioni, mantenendo attive le interfacce. Il controllo live ha confermato la disciplina di perdita sul contatto chiuso e la baseline valida con dieci ping consecutivi.

La coppia live `compare-3367d7d511574e6798a7a4a6f08c4285` è riuscita, con un tentativo per modalità e baseline valide. Evento `functional-53848-53913-4378`: NORAD 53848 (piano 1) verso 53913 (piano 2), TCP utile configurato a 1 Gbit/s. Il controller ha downtime 17,435 s in hot e 283,314 s in cold; durata trigger→cutover rispettivamente 452,813 s e 346,205 s. In hot la conferma di ripristino ping richiede 13,646 s dalla prima perdita; in cold il forwarding continua senza perdite osservate. L'indisponibilità del controller e quella del servizio dati sono misure distinte. Questi due casi sono una validazione funzionale con daemon Docker condiviso, non una campagna replicata.

Entrambe le prove hanno verificato equivalenza API, ACK, autorità B e almeno dieci ping freschi consecutivi dopo il cutover. Il job `job-4f9bb5ebd3584fd8aea5f203c15fbeba` è concluso con `application_success=true` e lock rilasciato. Riepilogo: `results/comparisons/compare-3367d7d511574e6798a7a4a6f08c4285/metadata.json`; prove `run-3d344ec3bef348949cbeea8ffbb6a39c` (hot) e `run-6e38db1cbce9438490eaace1f621e28d` (cold). Le precedenti baseline fallite rimangono conservate.

La suite host comprende 96 test: esito positivo, nove test specifici di ambiente saltati. Il log è `results/fso-tests-final.log`. Queste verifiche non sostituiscono l'esito della coppia live né una campagna sperimentale replicata.

## Live verification — 2026-10-14

The deployment was subsequently consolidated into the single `teraflow` Compose project. SAT-A/SAT-B keep separate private networks and existing external state volumes. All 20 permanent containers pass their health checks; the two Kafka initialization containers exit normally. Live selective SAT-B stop/start preserves SAT-A and BMv2 availability. The repeated API restore/service preflight passed with 50/50 pings and 512/514 UDP packets. Resource sampling still attributes nine containers to each host; disk selection requires both project and role labels. Evidence: `results/unified-compose-verification-2026-10-14.json`. This deployment check is separate from the migration trial below.

After removal of the previous simulator, the TeraFlow/P4 laboratory and local console were restarted. The stale workflow job was recovered through the normal job service; its source orbital window had expired, so the controllers were fenced before a new trial.

The restart exposed a missing-pipeline recovery defect: BMv2 starts without its P4 pipeline, while the proxy retains desired state. Recovery now installs the checkpointed pipeline before reading/reconciling rules; an existing conflicting pipeline is rejected. Eight P4 tests pass in the pinned proxy container. The host suite passes 56 tests with those eight container-only tests skipped.

The first diagnostic hot trial was interrupted after a 180-second Docker image-load timeout and rollback. A direct load of the unchanged authorized bundle succeeded. Image import now has a 600-second ceiling bounded by the remaining source operational deadline. The subsequent hot trial `run-c680093ed93447bcb7a5b6323c6dd7c8` succeeded on its first attempt: verified transfers, API equivalence, ACK and P4 cutover. Measured useful image throughput was 999.265 Mbit/s, image load 460.271 s, total operation 627.651 s and controller downtime 20.936 s. The final authority is SAT-B; 320/320 ping replies were observed after cutover.

The independent preflight verified 50/50 pings and 498/506 UDP packets. The migration trial's initial service baseline was unavailable, so its service recovery duration remains non-attributable; the trial is a functional diagnostic, not a primary campaign result. Cold mode was not rerun in this verification. Calibration and the 18-case primary campaign remain incomplete. Raw evidence is in the run/job directories, the regenerated summary in `results/report/`, and final checks in `results/runtime-verification-2026-10-14.json`.

The experiment is incomplete. No 18-case live campaign or completed calibration is claimed.

## Verified implementation

- Canonical snapshots, additions/modifications/deletions, empty deltas and receiver checksum/inventory checks have unit coverage.
- Migration tests cover both protocols, denied ACK after copy/verification/staging failure, bounded retries, alignment deadlines and unsuccessful recovery. If target fencing or source recovery fails, the state machine records metadata and stops retries.
- Probe analysis preserves unavailable measurements instead of treating them as zero loss. Ping recovery and the live preflight gate require consecutive successes. Pure UDP probes do not depend on a TCP handshake.
- Cleanup deletes devices before their topology to respect the live CockroachDB foreign key.
- P4 standby reads include staged members and selector groups. Reconciliation orders dependency removal and creation. A batch may create a member followed by its group without forwarding standby writes.
- Event tests retain nonmigrable events for every source once per operational period, including sources initially in shadow. Cylindrical eclipse tests distinguish the solar and antisolar sides.

At this checkpoint, 37 tests pass on the host; five additional P4 tests pass inside the pinned Device container and are skipped on the host because its P4 protobufs are unavailable. The patch regression tests exercise insert/update/delete dispatch, indirect table references, propagated hardware errors and dependency ordering.

## Live evidence and compatibility corrections

Both independent controller stacks and the dedicated Mininet/proxy lab have been launched. The tracked local Service handler patch was authorized by the user and built as `tfs-migration/service:7.0.0-fb870787-lab1` (image configuration digest `sha256:308a16e353f4f845f75b6983ae4a6273947a35e4d87c2bec72f1263fd1ef470b`). Its source, unified diff and checksums are in `deploy/patches/`; its generator is `tools/prepare_l2_patch.py`.

The previous API-only preflight did not prove forwarding: the saved ping log contains 18 unsuccessful probes and the previous UDP tool delivered no measured payload. `results/preflight/previous-probe-analysis.json` records this independently.

The user subsequently requested correction of the Device error. The tracked Device patch now selects member versus group parsing and supports indirect table actions containing `member-id` or `group-id`. It rejects ambiguous references and propagates hardware failures. Source/diff checksums are in `deploy/patches/device-manifest.json`; the generator is `tools/prepare_device_patch.py`. Both hosts use `tfs-migration/device:7.0.0-fb870787-lab2`.

Both hosts also use `tfs-migration/service:7.0.0-fb870787-lab2`, which deletes table references before profile members. The proxy accepts identity-only P4 DELETE requests. The proxy was restarted and its fixture re-established for live validation. Standby state must be re-established after a proxy restart; crash recovery is still an outstanding experiment gate.

Packet tracing at BMv2's default trace level on the Windows-mounted logs caused severe processing delays; the emulator now uses warning level. The UDP failure was independently identified through 526 `UdpInCsumErrors` at h2 for 526 sent packets. Host checksum/segmentation offload is disabled because BMv2's packet sockets forward bytes without completing deferred host checksums.

The successful live preflight `preflight-1790974558637618200` verified the API restore and real forwarding: 17 devices, 10 links, one service and one connection; 50/50 successful consecutive pings (mean RTT 4.4564 ms); 512/514 received UDP packets (998030.54 bit/s). These are five-second functional observations, not migration performance results. Evidence is in `results/preflight/live-preflight.json` and raw logs under `results/lab/`.

A second complete reset/recreation passed without restarting the drivers: `preflight-1790975583765116100`, 50/50 successful consecutive pings (mean RTT 4.5002 ms), 515/516 received UDP packets (999977.74 bit/s). This validates the corrected deletion order against the populated live fixture. The preflight JSON contains this latest execution; both runs retain their raw probe logs.

The final compatibility bundle is stored separately in `artifacts/images-l2-patched-v2/`; its manifest identifies the actual six image variants and both patch manifests. The earlier upstream and first compatibility bundles are preserved.

## Completion gates

As of 2026-10-08, the live backend and shared CLI/GUI job service are implemented. Functional cold `run-be3c5a3f29484ae0b15a71b1ec1a98cd` and hot `run-0a3533e9251349d69b907bf4028b568c` completed API equivalence, ACK and hardware cutover. Their controller downtimes were approximately 207.8 s and 19.53 s respectively; baseline service was already unavailable, so these runs do not establish migration-attributable service downtime. They are separate diagnostics with one observation each.

An initial hot restore exposed duplicate generated connections when updating a provisioned intent. Owned changed services are now deleted and recreated before restoring the desired intent; the repeat hot run passed. The failed/interrupted evidence remains saved.

The environment throughput gate completed real transfers at all three configured rates. Calibration was interrupted with recovery to correct disk accounting to include dependency image layers. The full workflow must run again with that corrected implementation before freezing results. The six calibrations, ten fault cases, principal 18 cases and modeled sensitivity remain acceptance gates until their saved results confirm completion. The report is preliminary until then.

The GUI is served locally on port 18092, with same-origin commands, session tokens, durable SSE replay and registered artifact downloads. See [operating guide](operating-guide.md). Unit tests cover restore failure injection, snapshot/delta, transport, authority fencing, job exclusivity and web protection. P4 tests run in the Linux proxy container because its protobuf environment differs from the host.
