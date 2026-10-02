# TeraFlowSDN controller migration simulation

This is a greenfield experiment workspace. It does not use the existing simulator implementation.

The experiment compares hot and cold migration of a TeraFlowSDN Release 7 controller workload over a direct FSO/TCP link. The orbital inputs are frozen Starlink TLEs, propagated with SGP4. Mininet/BMv2/P4 is planned as the functional service data plane; its links follow orbital visibility, while the controller binding moves only after SAT-B passes restoration checks and ACKs.

## Reproducible orbital preflight

The frozen source is [`data/starlink_2026-10-01.tle`](data/starlink_2026-10-01.tle); retrieval URL, SHA-256, record count, epoch, and screening notes are in [`data/source_manifest.json`](data/source_manifest.json). The TLE is from CelesTrak's public Starlink GP query. The selected records and the full screening report are in [`config/selected_constellation.json`](config/selected_constellation.json).

The selector propagates each TLE to the latest common epoch before grouping by orbital plane. It screens for inclination 52.5–53.5 degrees and SGP4 mean semi-major-axis altitude 520–580 km, then selects two planes with RAAN separation 10–30 degrees and keeps every candidate in those two groups. For this frozen snapshot that produces **17 satellites**, 6 in one plane and 11 in the other. Their RAAN centers are approximately 90.00 and 110.03 degrees at the reference epoch. The selected altitudes are about 521.9–540.1 km; 550 km remains the nominal shell label, while the stored TLE controls actual propagation. The 520–580 km screen is intentional: a tighter 530–570 km filter removes the multiple direct SAT-B choices needed for score-based election. STARLINK-3527 (NORAD 51726, 521.9 km) stays in the primary sample and will be identified as a boundary case; an optional sensitivity run can omit it.

The one-day, one-second preflight yields **168 direct FSO contact windows** within 1,700 km and without spherical-Earth occultation. It contains 7 distinct satellite pairs; 3 satellites have at least two direct candidate neighbors over the day. This is enough to exercise single-hop destination election on selected events. It remains a reduced two-plane sample, not a complete Starlink constellation.

To reproduce the artifacts (Python 3.11+ and `sgp4==2.27`; tested here with Python 3.13.9):

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe tools/select_constellation.py
.\.venv\Scripts\python.exe tools/check_direct_links.py
```

The orbital preflight does not yet select the final migration events: those require the trigger/deadline timeline and the measured controller workload manifest. The current contact-window count is a geometry check, not the number of migration trials.

The exact screening and percentile rules are documented in [`docs/orbital-selection.md`](docs/orbital-selection.md). The API order and the unresolved policy-rule write path are documented in [`docs/tfs-v7-state-adapter.md`](docs/tfs-v7-state-adapter.md).

## Migration model and fail-closed inputs

[`config/scenario.json`](config/scenario.json) stores the agreed common parameters: nominal 6-core/12-GiB/80-GiB node, 20% reserve, 1-second orbit step, 60-second FSO alignment, 1,700-km link range, TCP, three useful rates (100 Mbit/s, 1 Gbit/s, 10 Gbit/s), 120-second no-progress timeout, three total attempts, and restart-from-zero after interrupted copy.

[`src/migration_model.py`](src/migration_model.py) computes transfer time, total operation time, controller downtime, contact/deadline completion, and both orbital and migration margins. It uses decimal useful bit/s and measured bytes. Cold downtime begins after the source snapshot and includes transfer, destination startup, restore, verification, and ACK/cutover. Hot migration includes image and initial-state pre-copy while SAT-A stays active; downtime is the final freeze, delta transfer/application, verification, and cutover.

[`src/score_model.py`](src/score_model.py) applies the agreed 35/30/20/15 score weights. Candidate eligibility requires reachable network nodes and post-placement CPU/RAM/disk free capacity at or above the reserve. Latency utility is inverse min-max normalized among eligible candidates for the same event; if all candidate latencies are equal, they all receive 1. Connectivity is reachable managed nodes divided by modeled nodes. Continuity is predicted time until control reachability is lost, capped at the common forecast horizon. Resource utility is the weakest CPU/RAM/disk headroom above the reserve, normalized to [0,1]. Ties break by shorter FSO distance then lower NORAD ID. This is a transparent experimental ranking policy, not a claim that Starlink uses these weights.

[`src/resource_model.py`](src/resource_model.py) computes the common forecast horizon as `ceil(1.2 × slowest completion estimate)` and the deterministic 55%→85% background-load ramp over two horizons. The 80% crossing forecast must persist for 30 one-second samples; the trigger clears below 70% for 60 s. [`src/failure_model.py`](src/failure_model.py) withholds ACK and the active role after failure, preserves the hot source, or restarts the cold source from its local state when operational; retries are limited to three total attempts.

The final matrix is intentionally gated on real measurements. Copy [`config/artifact_manifest.template.json`](config/artifact_manifest.template.json) to `config/artifact_manifest.json`, then record the exact Release 7 source commit; image references, OCI digests and bytes actually sent; dependency placement; operational state export sizes/checksum; restore and verification timings; resource measurements; and measurement method/date. `tools/validate_artifact_manifest.py` reports all missing fields. The template values are null: no placeholder sizes are treated as real results.

## TeraFlow Docker Compose configuration

The two independent SAT-A/SAT-B stacks are defined in [deploy/compose.yaml](deploy/compose.yaml), with local NBI ports 18080 and 18081. See [the deployment notes](docs/teraflow-compose.md) for build and launch commands. Official v7.0.0 manifests require six workload images for the five logical components: PathComp has separate frontend and backend images. CockroachDB, NATS and Kafka are preinstalled independently per host. The source commit is recorded in [config/teraflow-source.json](config/teraflow-source.json). Runtime verification remains required.

## Remaining work before final results

1. Pin and build the exact TeraFlowSDN `v7.0.0` source; measure the five component artifacts and decide which supporting services are transferred or preinstalled.
2. Implement and exercise the Release 7 API adapter against the exact build: export contexts/topologies, devices/links, services/connections/policies; recreate them on SAT-B; check operational state; only then ACK.
3. Measure cold snapshot, hot initial restore/freeze/delta, controller startup, API restore/verification, and ACK times. Populate the artifact manifest from those runs.
4. Fix the score utility normalization and the starting SAT-A. The score implementation uses within-event latency normalization, connected-network reachability, predicted control-continuity over the common horizon, and the weakest CPU/RAM/disk headroom above reserve. Confirm the chosen initial host and that each selected event has multiple eligible SAT-B candidates before treating the score comparison as meaningful.
5. Generate eclipse/resource triggers and choose distinct P10/P50/P90 migration events from eligible triggers, then run the paired hot/cold × three-rate matrix. Add separately labelled controlled FSO-loss and destination-start failure trials.
6. Integrate the actual Mininet/BMv2 service probe and TeraFlow service restore, then confirm controller recovery and data-plane recovery separately.

Until these measurements and integration checks are complete, the output is an orbital preflight and a parametric model, not final performance evidence for a running TeraFlowSDN deployment.

## Sources

- CelesTrak, [Current GP Element Sets and query documentation](https://celestrak.org/NORAD/documentation/gp-data-formats.php) and [TLE field format](https://celestrak.org/NORAD/documentation/tle-fmt.php).
- ETSI TeraFlowSDN, [Release 7.0 Deployment Guide](https://tfs.etsi.org/documentation/v7.0.0/deployment_guide/) and [controller v7.0.0 source tag](https://labs.etsi.org/rep/tfs/controller/-/tree/v7.0.0).
- A. U. Chaudhry and H. Yanikomeroglu, “Temporary Laser Inter-Satellite Links in Free-Space Optical Satellite Networks,” *IEEE Open Journal of the Communications Society*, 2022, [DOI 10.1109/OJCOMS.2022.3198391](https://doi.org/10.1109/OJCOMS.2022.3198391). The paper evaluates 1,700 km among its temporary-LISL range scenarios; this does not make 1,700 km a universal hardware limit.
- ETSI TeraFlowSDN, [Supported SBIs and Network Elements](https://tfs.etsi.org/documentation/latest/supported_sbis_and_network_elements/), [Supported Service Handlers](https://tfs.etsi.org/documentation/latest/supported_service_handlers/), and [TFS#3 Mininet/P4 Hackfest](https://tfs.etsi.org/news/hackfest-3/).
- [Mininet overview](https://mininet.org/overview/) and [P4 BMv2](https://github.com/p4lang/behavioral-model).
