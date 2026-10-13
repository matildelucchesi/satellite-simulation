# Implementation status — 2026-10-02

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
