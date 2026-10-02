# TeraFlowSDN v7.0.0: state export and restore contract

This document records the documented API surface that the experiment adapter targets. It does not claim that the adapter has been run against a live TeraFlowSDN deployment.

## Export on SAT-A

Use the Release 7 TFS API NBI (`/tfs-api`), not the WebUI-only dummy import/export mode.

1. `GET /contexts` and `GET /context/{context_uuid}/topologies` to export contexts and topologies.
2. `GET /devices` and `GET /links` to export device/link inventory.
3. For each context, `GET /context/{context_uuid}/services` and `GET /context/{context_uuid}/slices` to export service/slice intents.
4. For each service, `GET /context/{context_uuid}/service/{service_uuid}/connections` to record the connection state that SAT-B is expected to recreate and verify.
5. `GET /policyrules` to export the visible policy rules.
6. Serialize a versioned snapshot, record Release 7 tag/commit and a SHA-256, and measure the serialized bytes.

The endpoint `/tfs-api/dummy_contexts` returns a snapshot intended for the WebUI's dummy mode. ETSI documents that this mode populates only the Context database and does not interact with Device, Service, or Slice components, so it is not a complete operational restore path.

## Restore on SAT-B

The adapter should use idempotent upsert logic where the API supports it, preserve stable UUIDs, and record each response for rollback. Restore in dependency order:

1. POST contexts to `/contexts`.
2. POST devices to `/devices`, then links to `/links`.
3. POST each topology to `/context/{context_uuid}/topologies`.
4. POST service and slice intents to `/context/{context_uuid}/services` and `/context/{context_uuid}/slices`. Service creation asks TeraFlowSDN to provision/recompute the service on its southbound devices; connections are expected to be recreated by the service workflow, not POSTed from the old connection snapshot.
5. GET the contexts, topologies, devices, links, services, slices and connections again. Compare stable IDs and required fields with the snapshot, then check service status and the Mininet/P4 end-to-end probes.
6. Send the migration ACK only after all required checks succeed.

The v7.0.0 TFS API page documents GET/POST for contexts, topologies, services, slices, devices and links, and GET for connections and policy rules. It does not document a policy-rule POST endpoint. Before claiming policy-rule restore, inspect the exact `v7.0.0` PolicyService protobuf and test its create/update calls, or classify those rules as static configuration included in the service intent/image. This remains a concrete adapter implementation task.

## API surface and known boundary

The v7.0.0 Supported NBIs page says TFS API exposes management of contexts, topologies, devices, links, services, slices, connections and policies. It lists `GET /tfs-api/policyrules`, but no matching POST. It also identifies `/tfs-api/dummy_contexts` as WebUI dummy mode only. The exact JSON schemas and success-status semantics must be taken from the v7.0.0 OpenAPI/implementation and validated against a running build before the adapter can ACK.

## Required integration checks

- The SAT-A export can be parsed and checked for required entity types and stable identifiers.
- A clean SAT-B accepts restore requests in dependency order; replaying a snapshot does not create duplicates.
- Service POST leads to an active service and the expected connections; read-back matches the snapshot.
- An injected failure at every restore stage suppresses ACK and leaves SAT-A active (hot) or permits SAT-A restart/rollback (cold).
- Adapter completion, HTTP/gRPC errors, retries and bytes are recorded in the run manifest.

Reference: [ETSI TeraFlowSDN v7.0.0 Supported NBIs](https://tfs.etsi.org/documentation/v7.0.0/supported_nbis/).
