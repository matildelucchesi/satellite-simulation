# Satellite Network Simulation

A containerised simulation of a seven-satellite network inspired by Starlink. The project propagates real TLE orbital data, models inter-satellite links and eclipse conditions, elects a logical Controller, and moves that Controller between satellites using comparable **hot** and **cold** migration protocols. It is built as a repeatable experiment: select a migration mode and a number of completed handovers, inspect the live dashboard, and compare the generated reports.

> This is a distributed-systems simulation, not flight software. The Controller is a logical service whose placement is represented by the satellite agent currently hosting it; the orbital geometry is physically modelled.

## What it demonstrates

- **Orbital awareness:** Skyfield propagates local TLE data and calculates GCRS position and velocity, WGS84 coordinates, sunlight/shadow state, time to eclipse, and pairwise distances.
- **Dynamic topology:** an inter-satellite link (ISL) exists only when satellites satisfy the configured distance and Earth line-of-sight constraints.
- **Controller placement:** seven independent agents collect orbital state and send heartbeats; the Simulator elects a Controller host and migrates it before its host enters eclipse.
- **Comparable handovers:** the same geometry and candidate-selection rules govern hot and cold migrations, allowing objective comparison of duration, downtime, acknowledgements, alignment, and rollback.

The default scenario includes seven satellites (`SAT-1` through `SAT-7`) selected from a Starlink 2022-175 launch in a roughly 53-degree shell. The simulation starts at `2026-07-20T23:57:30Z`.

## Architecture

```text
                         +------------------------------+
                         |           Dashboard          |
                         | live SVG view, tables, events |
                         +---------------+--------------+
                                         | aggregates REST data
                                         v
 +----------------+    orbital state   +-------------------+    checkpoint/state   +----------------+
 | Satellite      | <----------------> |     Simulator     |                       | Controller REST |
 | agents SAT-1..7| -- heartbeats ---> | scoring, election |                       | gateway         |
 +----------------+                    | migrations/reports|                       +----------------+
        ^                              +-------------------+
        |                                        |
        +-------- migration REST protocol -------+
        |        (source and target agents)       |
        +--- active satellite runs Controller ----+
```

| Component | Responsibility |
| --- | --- |
| `simulator` | Flask service and headless coordinator. Runs the orbital clock, retains the latest constellation snapshot, evaluates candidate scores, controls Controller election/migration, and exports metrics. |
| `satellite_agent` | Reusable Flask image instantiated seven times. It polls its orbital record, sends heartbeats, exposes migration endpoints, and contains a dormant Controller instance that is activated when that satellite is elected. |
| `controller` | Flask REST gateway that forwards heartbeat, topology, routing, and checkpoint operations to the active satellite's Controller instance. |
| `dashboard` | Flask UI which concurrently aggregates Simulator and Controller data. Its dependency-free frontend refreshes twice per second. |
| `common` | Shared environment-based settings. |
| `config` | Versioned constellation, TLE, scoring, and migration parameters. |
| `logs` | Host-mounted location for logs and completed-experiment JSON/PDF reports. |

Every service has an `app/__init__.py` composition root that constructs its dependencies. Flask routes in `app/routes.py` are thin HTTP/JSON adapters; application logic lives in modules including `orbit_engine`, `score_manager`, `migration_manager`, `experiment_manager`, `agent`, and `service`. HTTP and filesystem interactions use dedicated adapters, making the core behaviours testable without live containers.

## Simulation lifecycle

1. At startup the orbital clock is paused and the Dashboard asks for `hot` or `cold` mode and a migration limit (1–100; UI default: 3).
2. The Simulator resets state, starts TLE propagation, and agents poll their state every second. By default, agents heartbeat every five seconds.
3. The initial-election manager waits for a sunlit satellite with more than 300 seconds remaining before eclipse and at least one reachable neighbour. It selects the eligible satellite with the **least** remaining sunlight, stops Controller instances on all others, activates the selected satellite's local Controller instance, and records the host in the gateway.
4. Heartbeats contain CPU use, time to eclipse, Controller status, and current physical-neighbour IDs. The gateway forwards them to the active satellite's Controller instance, which builds topology/routing data; the Simulator maintains a separate cache for scoring.
5. Before the current host reaches eclipse, the scoring manager selects the best eligible physical neighbour and queues a handover when it passes the configured improvement and cooldown rules.
6. The migration first establishes a continuous contact window. Source and target must remain within 5,500 km, with clear line of sight, for 60 consecutive seconds. Broken contact or a sample gap above 2.5 seconds resets alignment.
7. The asynchronous migration requires a final `200 OK` acknowledgement from the target before cutover. Failures trigger rollback and remain visible in the event timeline.
8. Once the requested number of migrations completes, the Simulator stops the clock and writes `metrics-<mode>-<timestamp>.json` and `.pdf` to `logs/`. APIs and Dashboard remain available. **New simulation** logically resets the scenario without rebuilding Docker.

## Orbital and link model

The Simulator updates an in-memory JSON snapshot every `SIMULATOR_TICK_SECONDS` (one second by default). Per-satellite state includes:

- GCRS `position_km`, `velocity_km_s`, and scalar speed;
- WGS84 latitude, longitude, and altitude;
- illumination (`sunlight` or `shadow`) and time to the next eclipse;
- distance from every other satellite;
- `physical_neighbors`, `physical_neighbor_count`, and constellation-wide `physical_links`.

TLE data is local, so orbital-data downloads are unnecessary. To substitute a constellation, provide a valid three-line-per-object TLE and keep its object count aligned with `satellite_count` and the satellite IDs in `config/constellation.json`.

Controller scoring is always relative to the **current** host. It uses weights `w1`–`w4` from `config/scoring.json` and considers only an unambiguous current Controller and physically reachable targets. The default eclipse trigger combines 60 seconds of required contact alignment, a 90-second protocol budget, and a 60-second safety margin: 210 seconds. The target must have sufficient remaining sunlight and satisfy the link conditions. The migration manager maintains a completion deadline so it cancels or rolls back rather than completing after the source enters shadow.

## Controller handover protocols

Only one migration is active at a time. Both protocols record every REST step with timestamps, status, HTTP result, retries, transferred bytes, duration, and downtime. Retrieve the full operation at `GET /api/v1/migrations/<migration_id>`.

### Hot migration

1. The source registers the outgoing request; the target remains passive and is prepared with an initial checkpoint (**pre-copy**).
2. After the contact channel is aligned, the Controller is briefly quiesced and a second checkpoint captures the final delta.
3. The target receives final Controller state and must return `200 OK` for the expected final sequence number.
4. Only then is the source Controller instance stopped, the checkpoint restored into the target's local Controller instance, that instance activated, and the gateway host updated.

The channel established for pre-copy is reused for the delta; it is not aligned a second time.

### Cold migration

1. The source request is registered and the target is prepared passively.
2. The Controller is quiesced, a complete checkpoint is taken, and the source is stopped/shut down before transferring state.
3. The target acknowledges that state with `200 OK`; the Controller is restored, the target starts it, and the host is updated.

Cold migration therefore interrupts service for longer, while hot migration copies its initial working set before cutover. When any required action or acknowledgement fails, the manager restores the checkpoint and attempts to resume/restart the source; the migration is retained as `failed` with its rollback outcome.

## Timing and measurement model

`config/migration.json` controls REST timeouts/retries, contact constraints, and a deterministic parametric timing model. The model does not change migration ordering or geometry; it determines the simulated duration of the actual protocol phases.

It models:

- ISL base/distance latency, link processing, bandwidth, and bounded bandwidth variation;
- Controller working-set size (base, per-satellite, per-route); hot migration uses `hot_delta_fraction` for the delta;
- serialization/deserialization throughput, checkpoint/control/staging/startup processing, and per-satellite CPU load;
- bounded Gaussian jitter seeded by `timing_model.seed`.

Given the same seed, topology, and migration order, timing results are reproducible. Per-migration `metrics.timing_model` stores the real inputs and phase plan, including aggregate contributor totals. The PDF reads those values directly, ensuring it matches the JSON exactly. Default parameters produce a handover of roughly 6–7 seconds and 3–4 seconds of downtime, in addition to the 60-second geometric contact alignment.

## Dashboard

Open [http://localhost:8081/](http://localhost:8081/) after startup. It refreshes every 500 ms and offers:

- SVG network view with physical links, migration source/target highlights, eclipse countdowns, and transition times;
- satellite, route, heartbeat, candidate-score, and migration tables;
- event stream built from migration steps, heartbeats, upstream errors, and local logs;
- handover timeline for selection, alignment, checkpoints, transfers, acknowledgement, cutover, and rollback;
- experiment controls plus JSON/PDF export listing and preview.

The frontend uses no CDN or external JavaScript library, allowing offline operation once Docker images are present locally.

## Prerequisites

- Docker Engine with Docker Compose v2 (`docker compose`)
- The local ports documented below must be available

Python is required only for running tests outside Docker. Each service supplies its compatible runtime dependencies in its own `requirements.txt`.

## Quick start

```bash
docker compose up --build
```

Visit [http://localhost:8081/](http://localhost:8081/), choose an experiment mode and migration limit, and inspect the run. Verify Simulator readiness with:

```bash
curl http://localhost:8000/health
```

Stop the stack with:

```bash
docker compose down
```

The bind-mounted `logs/` directory is kept by `docker compose down`. Controller checkpoints are stored in each satellite container and transferred to the target during handover.

## Service ports

| Service | Host address | Purpose |
| --- | --- | --- |
| Simulator | `http://localhost:8000` | Orbital state, experiments, scores, migrations, metrics |
| Controller gateway | `http://localhost:8001` | Proxied state, checkpoints, and heartbeats for the active satellite Controller |
| Dashboard | `http://localhost:8081` | Web UI and aggregation (`DASHBOARD_PORT` is configurable) |
| `SAT-1` to `SAT-7` | `http://localhost:8101` to `http://localhost:8107` | Individual satellite-agent APIs |

## Public APIs

### Simulator (`localhost:8000`)

| Method | Path | Description |
| --- | --- | --- |
| `GET` | `/health` | Readiness, run state, and last error. |
| `GET` | `/api/v1/constellation` | Full latest orbital/topology snapshot. |
| `GET` | `/api/v1/satellites` | All satellite records. |
| `GET` | `/api/v1/satellites/SAT-1` | One satellite record. |
| `GET`/`POST` | `/api/v1/heartbeats` | List or submit heartbeats; posts are ignored while no experiment runs. |
| `GET` | `/api/v1/scores` | Candidate scores and migration evaluation. |
| `GET` | `/api/v1/startup-controller` | Initial-election status, candidates, and host. |
| `GET`/`POST` | `/api/v1/migrations` | List migrations or queue one manually. |
| `GET` | `/api/v1/migrations/<id>` | Migration contact status, events, and metrics. |
| `GET`/`POST` | `/api/v1/experiment` | Read state or start an experiment. |
| `POST` | `/api/v1/experiment/reset` | Return to the paused initial scenario. |
| `GET` | `/api/v1/metrics` | Aggregate experiment metrics. |
| `GET` | `/api/v1/metrics/export.json` | Download current metrics as JSON. |
| `GET` | `/api/v1/metrics/export.csv` | Download current metrics as CSV. |

Start an experiment with:

```bash
curl -X POST http://localhost:8000/api/v1/experiment \
  -H "Content-Type: application/json" \
  -d '{"mode":"hot","migration_limit":3}'
```

A manual migration (only while the experiment runs) needs a payload such as:

```json
{
  "source_satellite_id": "SAT-1",
  "target_satellite_id": "SAT-2",
  "mode": "hot"
}
```

### Satellite agent (`localhost:8101`–`8107`)

| Method | Path | Description |
| --- | --- | --- |
| `GET` | `/health` | Agent identity and worker status. |
| `GET` | `/status` | Local Controller, sync, heartbeat, and migration state. |
| `GET` | `/position` | Last Simulator state; returns `503` before first sync. |
| `POST` | `/receive_state` | Accept individual or full orbital snapshot. |
| `POST` | `/start_controller`, `/stop_controller` | Activate/deactivate the Controller instance hosted in this satellite agent. |
| `GET`/`POST` | `/controller/...` | Local Controller API, active only while this satellite hosts the Controller. |
| `POST` | `/migration_request` | Register outbound handover; allowed only for current host. |
| `POST` | `/prepare_migration` | Prepare passive target with initial state. |
| `POST` | `/receive_controller_state` | Receive final state and return required `200 OK`. |
| `POST` | `/reset_simulation` | Clear volatile state while retaining workers. |

### Controller (`localhost:8001`)

| Method | Path | Description |
| --- | --- | --- |
| `GET` | `/health` | Active/quiesced state and logical host. |
| `GET`/`POST` | `/heartbeat` | List (optional `?id=SAT-1`) or accept a heartbeat. |
| `GET` | `/state` | Topology, routes, heartbeats, sequence number, timestamp, host. |
| `POST` | `/host` | Set host with `{"satellite_id":"SAT-1"}`. |
| `POST` | `/checkpoint` | Atomically save this satellite's local Controller state before transfer. |
| `POST` | `/restore` | Restore supplied JSON or the last checkpoint. |
| `POST` | `/shutdown` | Checkpoint and logically deactivate. |
| `POST` | `/quiesce`, `/resume` | Pause/resume mutations around cutover. |
| `POST` | `/reset_simulation` | Clear state and reset host to `UNASSIGNED`. |

### Dashboard (`localhost:8081`)

| Method | Path | Description |
| --- | --- | --- |
| `GET` | `/` | Monitoring UI. |
| `GET` | `/api/dashboard` | Aggregated resilient upstream snapshot. |
| `GET` | `/api/exports` | Available automatic JSON/PDF reports. |
| `GET` | `/exports/<filename>` | Download a listed report (`?download=1` forces attachment). |
| `POST` | `/api/experiment` | Proxy experiment start to the Simulator. |
| `POST` | `/api/experiment/reset` | Proxy logical reset. |
| `GET` | `/health` | Dashboard health. |

## Configuration

Configuration is mounted read-only into the containers.

| File | Key settings |
| --- | --- |
| `config/constellation.json` | Satellite IDs/names, count, fixed simulation start, initial-election strategy. |
| `config/starlink.tle` | Local source orbital elements. |
| `config/scoring.json` | Score weights, heartbeat TTL, improvement/cooldown, eclipse safety rules. |
| `config/migration.json` | Mode, agent endpoint template, retries, contact constraints, execution budget, timing model. |
| `.env.example` | Logging, tick intervals, request timeouts, and Dashboard port defaults. |

To override the Compose defaults, copy `.env.example` to `.env`, edit the desired values, and recreate the stack. Important variables include `SIMULATOR_TICK_SECONDS`, `ECLIPSE_SEARCH_HOURS`, `STATE_SYNC_INTERVAL_SECONDS`, `HEARTBEAT_INTERVAL_SECONDS`, `HTTP_REQUEST_TIMEOUT_SECONDS`, `UPSTREAM_TIMEOUT_SECONDS`, and `DASHBOARD_PORT`.

## Reports and metrics

`GET /api/v1/metrics` returns experiment time, completed/failed migration and heartbeat counts, acknowledgements, total/average downtime, average handover and contact-alignment time, and Controller-election measurements. On automatic completion, the JSON report retains the full migration records. The PDF provides a human-readable summary and phase-level timing explanation.

Reports are named `metrics-hot-YYYYMMDD-HHMMSS.{json,pdf}` or `metrics-cold-YYYYMMDD-HHMMSS.{json,pdf}`. They appear in the Dashboard Export section and remain on the host in `logs/`.

## Tests

The repository has unit/API tests for the orbit engine, contact windows, timing model, scoring, initial election, migration protocols, reports, and the four Flask services. With the required dependencies installed, run each suite from its service directory:

```bash
cd simulator
python -m unittest discover -s tests -v

cd ../controller
python -m unittest discover -s tests -v

cd ../satellite_agent
python -m unittest discover -s tests -v

cd ../dashboard
python -m unittest discover -s tests -v
```

The Compose workflow is recommended for end-to-end execution because it provides the intended service names, private network, mounts, and inter-service URLs.
