"""Operational Release 7 NBI adapter; no dummy or database restoration."""
from __future__ import annotations

import json
import threading
import copy
import time
from contextlib import contextmanager
from urllib.error import HTTPError
from urllib.parse import quote
from urllib.request import Request, urlopen
from pathlib import Path

from .artifacts import canonical_bytes
from .snapshot import KINDS, identity, snapshot, validate


def uuid(identifier: dict, key: str) -> str:
    return identifier[key]["uuid"]


def service_intent(row):
    result = {key: row.get(key, []) if key in ("service_constraints", "service_endpoint_ids") else row.get(key)
            for key in ("service_id", "name", "service_type", "service_endpoint_ids", "service_constraints", "service_config")}
    result["service_config"] = {"config_rules": [rule for rule in row.get("service_config", {}).get("config_rules", [])
        if not rule.get("custom", {}).get("resource_key", "").startswith("/device[")]}
    return result


def route(kind: str, item: dict, collection: bool = False) -> str:
    esc = lambda value: quote(value, safe="")
    if kind in {"contexts", "devices", "links"}:
        singular = {"contexts": "context", "devices": "device", "links": "link"}[kind]
        if collection:
            return "/" + kind
        return f"/{singular}/{esc(uuid(item[singular + '_id'], singular + '_uuid'))}"
    singular = {"topologies": "topology", "services": "service"}[kind]
    identifier = item[singular + "_id"]
    context = uuid(identifier["context_id"], "context_uuid")
    base = f"/context/{esc(context)}"
    return f"{base}/{kind}" if collection else f"{base}/{singular}/{esc(uuid(identifier, singular + '_uuid'))}"


class TfsAdapter:
    def __init__(self, base_url: str, context_id: str = "migration-lab", timeout_s: float = 30):
        self.base_url = base_url.rstrip("/") + "/tfs-api"
        self.context_id = context_id
        self.timeout_s = timeout_s
        self.lock = threading.RLock()
        self.calls: list[dict] = []
        selection = json.loads((Path(__file__).parents[1]/'config/selected_constellation.json').read_text())
        self.allowed_device_names = {f"sat-{row['norad_id']}" for row in selection['satellites']}

    def request(self, method: str, path: str, body=None):
        started = time.monotonic()
        request = Request(self.base_url + path, data=None if body is None else canonical_bytes(body),
                          headers={"Content-Type": "application/json"}, method=method)
        record = {"method": method, "path": path, "started_monotonic": started}
        try:
            with urlopen(request, timeout=self.timeout_s) as response:
                record["status"] = response.status
                data = response.read()
                return json.loads(data) if data else None
        except HTTPError as exc:
            record["status"] = exc.code
            record["error"] = exc.read().decode(errors="replace")
            raise RuntimeError(f"NBI {method} {path}: {exc.code}: {record['error']}") from exc
        finally:
            record["elapsed_s"] = time.monotonic() - started
            self.calls.append(record)

    @contextmanager
    def quiescent(self):
        # All orchestrated NBI mutations must acquire this same lock.
        with self.lock:
            yield

    def _read(self) -> dict:
        all_contexts = self.request("GET", "/contexts").get("contexts", [])
        foreign = [row for row in all_contexts if row.get('name') not in ('admin', 'migration-lab')]
        if foreign: raise ValueError('Contexts outside migration perimeter: '+str([row.get('name') for row in foreign]))
        contexts = [row for row in all_contexts if uuid(row["context_id"], "context_uuid") == self.context_id
                    or row.get("name") == self.context_id]
        entities = {kind: [] for kind in KINDS}
        entities["contexts"] = contexts
        devices = self.request('GET','/devices').get('devices',[])
        foreign = [row.get('name') for row in devices if row.get('name') not in self.allowed_device_names]
        if foreign: raise ValueError('Devices outside migration perimeter: '+str(foreign))
        policies = self.request("GET", "/policyrules").get("policy_rules", [])
        if policies: raise ValueError('Independent policy rules outside migration perimeter')
        if not contexts:
            if devices: raise ValueError('Devices exist without migration context; explicit recovery required')
            return snapshot(entities)
        prefix = "/context/" + quote(uuid(contexts[0]["context_id"], "context_uuid"), safe="")
        slices = self.request("GET", prefix + "/slices").get("slices", [])
        if slices or policies:
            raise ValueError("Slices or independent policy rules outside the migration perimeter")
        entities["topologies"] = self.request("GET", prefix + "/topologies").get("topologies", [])
        if any(row.get('name') != 'starlink-17' for row in entities['topologies']):
            raise ValueError('Topologies outside migration perimeter')
        entities["devices"] = devices
        foreign = [row.get('name') for row in entities['devices'] if row.get('name') not in self.allowed_device_names]
        if foreign: raise ValueError('Devices outside migration perimeter: '+str(foreign))
        device_ids = {canonical_bytes(row["device_id"]) for row in entities["devices"]}
        entities["links"] = self.request("GET", "/links").get("links", [])
        if any(not all(canonical_bytes(ep['device_id']) in device_ids for ep in row.get('link_endpoint_ids',[]))
               for row in entities['links']):raise ValueError('Links outside migration perimeter')
        entities["services"] = self.request("GET", prefix + "/services").get("services", [])
        if any(row.get('name') != 'migration-l2' for row in entities['services']):
            raise ValueError('Services outside migration perimeter')
        for service in entities["services"]:
            sid = uuid(service["service_id"], "service_uuid")
            entities["connections"].extend(self.request(
                "GET", prefix + "/service/" + quote(sid, safe="") + "/connections").get("connections", []))
        return snapshot(entities)

    def export(self, settle_timeout_s: float = 30, interval_s: float = 0.2) -> dict:
        with self.quiescent():
            deadline = time.monotonic() + settle_timeout_s
            previous = self._read()
            while time.monotonic() < deadline:
                time.sleep(interval_s)
                current = self._read()
                if canonical_bytes(previous) == canonical_bytes(current):
                    return current
                previous = current
            raise TimeoutError("Operational state did not reach two equivalent reads")

    def restore(self, document: dict, inject_failure_at: str | None = None) -> None:
        validate(document)
        with self.lock:
            # Release 7 SetDevice always associates even endpoint-free devices
            # with admin/admin. This static local scaffold must already exist.
            self.request("POST", "/contexts", {"contexts": [{"context_id": {"context_uuid": {"uuid": "admin"}}, "name": "admin"}]})
            self.request("POST", "/context/admin/topologies", {"topologies": [{"topology_id": {
                "context_id": {"context_uuid": {"uuid": "admin"}}, "topology_uuid": {"uuid": "admin"}}, "name": "admin"}]})
            existing = self._read()["entities"]
            # Endpoint topology memberships are resolved by AddDevice, so create
            # context + empty topology before adding inventory, then reconcile it.
            for context in document["entities"]["contexts"]:
                self.request("POST", "/contexts", {"contexts": [context]})
            for topology in document["entities"]["topologies"]:
                skeleton = {key: value for key, value in topology.items()
                            if key not in {"device_ids", "link_ids", "optical_link_ids"}}
                self.request("POST", route("topologies", topology, True), {"topologies": [skeleton]})
            for kind in ("contexts", "devices", "links", "topologies", "services"):
                if inject_failure_at == kind:
                    raise RuntimeError(f"Injected restore failure: {kind}")
                indexed = {identity(kind, row): row for row in existing[kind]}
                for row in document["entities"][kind]:
                    old = indexed.get(identity(kind, row))
                    if kind == "devices" and old is not None and old.get("device_operational_status") in (
                            None, "DEVICEOPERATIONALSTATUS_UNDEFINED", 0):
                        self.request("DELETE", route(kind, old))
                        old = None
                    if old == row:
                        continue
                    if kind == "services" and old is not None and service_intent(old) == service_intent(row):
                        continue
                    if kind == "devices" and old is not None:
                        old_rules = {rule.get("custom", {}).get("resource_key"): rule
                                     for rule in old.get("device_config", {}).get("config_rules", [])}
                        payload = copy.deepcopy(row)
                        changes = []
                        for rule in row.get("device_config", {}).get("config_rules", []):
                            key = rule.get("custom", {}).get("resource_key", "")
                            if key.startswith("_connect/"):
                                if old_rules.get(key) != rule:
                                    raise ValueError("Connection settings changed on existing device; clean target before restore")
                                continue
                            if old_rules.get(key) != rule: changes.append(rule)
                        payload["device_config"] = {"config_rules": changes}
                        if changes or old.get("device_endpoints", []) != row.get("device_endpoints", []):
                            self.request("PUT", route(kind, row), payload)
                        continue
                    if old is None:
                        payload = copy.deepcopy(row)
                        if kind == "devices":
                            # AddDevice discovers endpoints using the driver;
                            # it explicitly rejects endpoints in its request.
                            payload["device_endpoints"] = []
                            payload["device_config"]["config_rules"] = [rule for rule in payload["device_config"]["config_rules"]
                                if rule.get("custom", {}).get("resource_key", "").startswith("_connect/")]
                        elif kind == "services":
                            # Release 7 CreateService only creates a blank intent;
                            # UpdateService then provisions endpoints and rules.
                            payload["service_endpoint_ids"] = []
                            payload["service_constraints"] = []
                            payload["service_config"] = {"config_rules": []}
                        self.request("POST", route(kind, row, True), {kind: [payload]})
                        if kind == "devices":
                            actual = self.request("GET", route(kind, row))
                            old_rules = {canonical_bytes(rule) for rule in actual.get("device_config", {}).get("config_rules", [])}
                            remaining = [rule for rule in row["device_config"]["config_rules"]
                                if not rule.get("custom", {}).get("resource_key", "").startswith("_connect/")
                                and canonical_bytes(rule) not in old_rules]
                            if remaining:
                                update = copy.deepcopy(row)
                                update["device_config"] = {"config_rules": remaining}
                                self.request("PUT", route(kind, row), update)
                        if kind == "services": self.request("PUT", route(kind, row), row)
                    else:
                        self.request("PUT", route(kind, row), row)

    def cleanup(self, document: dict) -> None:
        validate(document)
        with self.lock:
            current = self._read()["entities"]
            # Endpoints reference topology rows in Release 7. Remove links and
            # devices before topologies or CockroachDB rejects the cleanup.
            for kind in ("services", "links", "devices", "topologies", "contexts"):
                present = {identity(kind, row) for row in current[kind]}
                for row in document["entities"][kind]:
                    if identity(kind, row) in present:
                        self.request("DELETE", route(kind, row))

    def reconcile(self, desired):
        """Apply full desired state, including deleted objects and device rules."""
        validate(desired)
        with self.lock:
            current = self._read()['entities']
            for kind in ('services', 'links', 'devices', 'topologies', 'contexts'):
                wanted_rows = {identity(kind, row):row for row in desired['entities'][kind]}
                for row in current[kind]:
                    target = wanted_rows.get(identity(kind,row))
                    # Release 7 UpdateService creates another generated
                    # connection when changing a provisioned L2 intent. Delete
                    # and recreate this owned intent to avoid stale paths.
                    changed_service = (kind=='services' and target is not None
                        and service_intent(row)!=service_intent(target))
                    if target is None or changed_service:self.request('DELETE',route(kind,row))
            wanted_devices = {identity('devices', row): row for row in desired['entities']['devices']}
            for row in current['devices']:
                target = wanted_devices.get(identity('devices', row))
                if target is None: continue
                keys = {r.get('custom', {}).get('resource_key') for r in target.get('device_config', {}).get('config_rules', [])}
                removed = [copy.deepcopy(r) for r in row.get('device_config', {}).get('config_rules', [])
                           if r.get('custom', {}).get('resource_key') not in keys
                           and not r.get('custom', {}).get('resource_key', '').startswith('_connect/')]
                if removed:
                    def order(rule):
                        key = rule.get('custom', {}).get('resource_key', '')
                        return (0 if key.startswith('/tables/') else 1, key)
                    removed.sort(key=order)
                    for rule in removed: rule['action'] = 'CONFIGACTION_DELETE'
                    update = copy.deepcopy(row); update['device_config'] = {'config_rules': removed}
                    self.request('PUT', route('devices', row), update)
            self.restore(desired)

    def verify(self, expected: dict) -> dict:
        """Strict equality except IDs of generated connections and volatile status."""
        validate(expected)
        actual = self.export()
        errors = []
        for kind in KINDS:
            def projection(row):
                # Keep path order and endpoints; only generated connection ID is omitted.
                row = dict(row)
                if kind == "connections":
                    row.pop("connection_id", None)
                return canonical_bytes(row)
            want = sorted(projection(row) for row in expected["entities"][kind])
            got = sorted(projection(row) for row in actual["entities"][kind])
            if want != got:
                errors.append(kind)
        return {"equivalent": not errors, "mismatched_entity_types": errors, "actual": actual}
