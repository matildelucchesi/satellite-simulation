"""P4Runtime fencing proxy. Standby reads/writes are explicit shadow operations.

Run inside the pinned TeraFlow Device image, which supplies matching P4 protobufs.
The L2 experiment supports tables and action-profile members/groups.
"""
from __future__ import annotations

import copy
import json
import queue
import threading
import socket
import logging
import base64
import os
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import grpc
from google.protobuf import text_format
from p4.v1 import p4runtime_pb2 as pb, p4runtime_pb2_grpc as rpc
from .authority import Authority
from .storage import atomic_json


def canonical_entity(entity):
    result = pb.Entity()
    result.CopyFrom(entity)
    if result.WhichOneof("entity") == "action_profile_group":
        members = sorted(result.action_profile_group.members, key=lambda member: member.member_id)
        del result.action_profile_group.members[:]
        result.action_profile_group.members.extend(members)
        return result
    if result.WhichOneof("entity") == "action_profile_member":
        action = result.action_profile_member.action
        for parameter in action.params:
            parameter.value = parameter.value.lstrip(b"\x00") or b"\x00"
        ordered = sorted(action.params, key=lambda item: item.param_id)
        del action.params[:]; action.params.extend(ordered)
        return result
    entry = result.table_entry
    for match in entry.match:
        operation = match.WhichOneof("field_match_type")
        if operation:
            value = getattr(match, operation)
            for field in ("value", "mask", "low", "high"):
                if hasattr(value, field):
                    raw = getattr(value, field)
                    setattr(value, field, raw.lstrip(b"\x00") or b"\x00")
    for parameter in entry.action.action.params:
        parameter.value = parameter.value.lstrip(b"\x00") or b"\x00"
    ordered = sorted(entry.match, key=lambda item: item.field_id)
    del entry.match[:]; entry.match.extend(ordered)
    ordered = sorted(entry.action.action.params, key=lambda item: item.param_id)
    del entry.action.action.params[:]; entry.action.action.params.extend(ordered)
    return result


def entry_key(entity):
    if entity.WhichOneof("entity") == "action_profile_group":
        group = entity.action_profile_group
        return ("group", group.action_profile_id, group.group_id)
    if entity.WhichOneof("entity") == "action_profile_member":
        member = entity.action_profile_member
        return ("member", member.action_profile_id, member.member_id)
    if entity.WhichOneof("entity") != "table_entry":
        raise ValueError("Only table entries are supported by the L2 fixture")
    entry = canonical_entity(entity).table_entry
    matches = sorted((match.field_id, match.SerializeToString(deterministic=True)) for match in entry.match)
    return "table", entry.table_id, entry.priority, entry.is_default_action, tuple(matches)


def content(entity):
    result = canonical_entity(entity)
    # Read-back counters/time-since-last-hit are operational, not desired config.
    if result.WhichOneof("entity") == "table_entry":
        result.table_entry.ClearField("counter_data")
        result.table_entry.ClearField("time_since_last_hit")
    return result.SerializeToString(deterministic=True)


class Backend:
    def __init__(self, endpoint, device_id):
        self.device_id = device_id
        self.channel = grpc.insecure_channel(endpoint)
        grpc.channel_ready_future(self.channel).result(timeout=30)
        self.stub = rpc.P4RuntimeStub(self.channel)
        self.messages = queue.Queue()
        self.election = pb.Uint128(high=1, low=1)
        self.master = threading.Event()
        def requests():
            while True:
                value = self.messages.get()
                if value is None: return
                yield value
        self.stream = self.stub.StreamChannel(requests())
        def receive():
            try:
                for response in self.stream:
                    if response.HasField("arbitration"):
                        if response.arbitration.status.code == 0: self.master.set()
                        else: self.master.clear()
            except grpc.RpcError:
                self.master.clear()
            finally:
                self.master.clear()
        threading.Thread(target=receive, daemon=True).start()
        request = pb.StreamMessageRequest()
        request.arbitration.device_id = device_id
        request.arbitration.election_id.CopyFrom(self.election)
        self.messages.put(request)

    def require_master(self):
        if not self.master.wait(10):
            raise RuntimeError("Proxy has no confirmed upstream P4Runtime mastership")

    def read_all(self):
        request = pb.ReadRequest(device_id=self.device_id)
        request.entities.add().table_entry.table_id = 0
        request.entities.add().action_profile_member.action_profile_id = 0
        request.entities.add().action_profile_group.action_profile_id = 0
        return [entity for response in self.stub.Read(request, timeout=10) for entity in response.entities]

    def write(self, updates):
        self.require_master()
        request = pb.WriteRequest(device_id=self.device_id)
        request.election_id.CopyFrom(self.election)
        request.updates.extend(updates)
        if updates:
            try: self.stub.Write(request, timeout=10)
            except grpc.RpcError as exc:
                logging.error("Hardware rejected updates %s metadata=%r", request, exc.trailing_metadata())
                raise


class SwitchState:
    def __init__(self, backend, authority):
        self.backend = backend
        self.authority = authority
        self.pipeline = {}
        self.entries = {"sat-a": {}, "sat-b": {}}
        directory = os.environ.get('P4_STATE_DIRECTORY')
        self.checkpoint = Path(directory)/('switch-'+str(backend.device_id)+'.json') if directory else None
        # Recover the existing hardware configuration on proxy restart without
        # resetting a live pipeline or silently losing the active desired state.
        backend.require_master()
        try:
            request = pb.GetForwardingPipelineConfigRequest(device_id=backend.device_id,
                        response_type=pb.GetForwardingPipelineConfigRequest.ALL)
            config = backend.stub.GetForwardingPipelineConfig(request, timeout=10).config
            if config.p4info.tables:
                self.pipeline["sat-a"] = copy.deepcopy(config)
                self.entries["sat-a"] = {entry_key(entity): entity for entity in backend.read_all()
                                          if not entity.table_entry.is_default_action}
        except grpc.RpcError as exc:
            if exc.code() not in (grpc.StatusCode.NOT_FOUND, grpc.StatusCode.FAILED_PRECONDITION):
                raise
        if self.checkpoint and self.checkpoint.exists():
            saved = json.loads(self.checkpoint.read_text())
            self.pipeline = {role: pb.ForwardingPipelineConfig.FromString(base64.b64decode(value))
                             for role, value in saved['pipeline'].items()}
            self.entries = {role: {entry_key(entity): entity for entity in
                           [pb.Entity.FromString(base64.b64decode(value)) for value in values]}
                            for role, values in saved['entries'].items()}
        self.persist()

    def persist(self):
        if self.checkpoint:
            encode = lambda value: base64.b64encode(value.SerializeToString(deterministic=True)).decode()
            atomic_json(self.checkpoint, {'pipeline': {role: encode(value) for role, value in self.pipeline.items()},
                'entries': {role: [encode(value) for value in rows.values()] for role, rows in self.entries.items()}})

    def ready(self, role):
        if role not in self.pipeline: return False
        try:
            for value in self.entries[role].values(): self.validate(role, value)
            for value in self.entries[role].values():
                if value.WhichOneof('entity') != 'table_entry': continue
                table = next(t for t in self.pipeline[role].p4info.tables if t.preamble.id == value.table_entry.table_id)
                action = value.table_entry.action
                kind = action.WhichOneof('type')
                if kind in ('action_profile_member_id', 'action_profile_group_id'):
                    target = ('member' if kind.endswith('member_id') else 'group', table.implementation_id, getattr(action, kind))
                    if target not in self.entries[role]: return False
            return True
        except (ValueError, StopIteration): return False

    def validate(self, role, entity, staged_entries=None, deleting=False):
        key = entry_key(entity)
        if role not in self.pipeline:
            raise ValueError("No validated P4Info pipeline for role")
        info = self.pipeline[role].p4info
        if key[0] == "group":
            group = entity.action_profile_group
            profile = next((p for p in info.action_profiles if p.preamble.id == group.action_profile_id), None)
            if profile is None or not profile.with_selector or group.group_id <= 0:
                raise ValueError("Invalid selector group")
            if deleting: return key
            ids = [member.member_id for member in group.members]
            if len(ids) != len(set(ids)) or any(member.weight <= 0 for member in group.members):
                raise ValueError("Duplicate group members or invalid weights")
            available = self.entries[role] if staged_entries is None else staged_entries
            if any(("member", group.action_profile_id, member) not in available for member in ids):
                raise ValueError("Selector group references an unavailable member")
            return key
        if key[0] == "member":
            member = entity.action_profile_member
            profile = next((p for p in info.action_profiles if p.preamble.id == member.action_profile_id), None)
            if profile is None or member.member_id <= 0: raise ValueError("Invalid action profile member")
            if deleting: return key
            tables = [t for t in info.tables if t.preamble.id in profile.table_ids]
            if member.action.action_id not in {a.id for table in tables for a in table.action_refs}:
                raise ValueError("Action not valid for action profile")
            definition = next(a for a in info.actions if a.preamble.id == member.action.action_id)
            params = {p.id: p for p in definition.params}
            if {p.param_id for p in member.action.params} != set(params): raise ValueError("Incomplete member action")
            for param in member.action.params:
                if int.from_bytes(param.value, "big") >= 2**params[param.param_id].bitwidth:
                    raise ValueError("Member action exceeds width")
            return key
        table = next((table for table in info.tables if table.preamble.id == key[1]), None)
        if table is None: raise ValueError("Unknown P4 table ID")
        fields = {field.id: field for field in table.match_fields}
        for match in entity.table_entry.match:
            if match.field_id not in fields: raise ValueError("Unknown P4 match field")
            field = fields[match.field_id]
            operation = match.WhichOneof("field_match_type")
            if operation is None: raise ValueError("Missing match operation")
            value = getattr(match, operation)
            raw = value.value if hasattr(value, "value") else value.low
            if int.from_bytes(raw, "big") >= 2**field.bitwidth:
                raise ValueError("P4 match exceeds field width")
        action = entity.table_entry.action
        if action.WhichOneof("type") == "action":
            definition = next((a for a in info.actions if a.preamble.id == action.action.action_id), None)
            if definition is None or action.action.action_id not in {a.id for a in table.action_refs}:
                raise ValueError("Action is not valid for table")
            parameters = {p.id: p for p in definition.params}
            if {p.param_id for p in action.action.params} != set(parameters):
                raise ValueError("Incomplete action parameters")
            for parameter in action.action.params:
                if int.from_bytes(parameter.value, "big") >= 2**parameters[parameter.param_id].bitwidth:
                    raise ValueError("Action parameter exceeds width")
        return key

    def reconcile(self, destination):
        backend = self.backend
        backend.require_master()
        if destination not in self.pipeline: raise RuntimeError("Destination pipeline missing")
        current = {entry_key(entity): entity for entity in backend.read_all()}
        desired = self.entries[destination]
        updates = []
        # Remove dependents before dependencies; create in the reverse order.
        deletion_order = {"table": 0, "group": 1, "member": 2}
        for key, entity in sorted(current.items(), key=lambda item: deletion_order[item[0][0]]):
            if key not in desired and not entity.table_entry.is_default_action:
                updates.append(pb.Update(type=pb.Update.DELETE, entity=entity))
        for key, entity in sorted(desired.items(), key=lambda item: -deletion_order[item[0][0]]):
            if key not in current:
                updates.append(pb.Update(type=pb.Update.INSERT, entity=entity))
            elif content(current[key]) != content(entity):
                updates.append(pb.Update(type=pb.Update.MODIFY, entity=entity))
        backend.write(updates)
        actual = {entry_key(entity): content(entity) for entity in backend.read_all()
                  if not entity.table_entry.is_default_action}
        expected = {key: content(entity) for key, entity in desired.items() if not entity.table_entry.is_default_action}
        if actual != expected:
            raise RuntimeError("Hardware read-back differs after reconciliation")


class Proxy(rpc.P4RuntimeServicer):
    def __init__(self, state, role):
        self.state = state
        self.role = role

    def _check(self, request, context):
        if request.device_id != self.state.backend.device_id:
            context.abort(grpc.StatusCode.INVALID_ARGUMENT, "Wrong device ID")

    def SetForwardingPipelineConfig(self, request, context):
        self._check(request, context)
        with self.state.authority.lock:
            config = pb.ForwardingPipelineConfig()
            config.CopyFrom(request.config)
            other = self.state.pipeline.get("sat-a")
            if other and config != other:
                context.abort(grpc.StatusCode.FAILED_PRECONDITION, "Standby pipeline differs from active pipeline")
            if self.state.authority.writable(self.role) and other is None:
                forwarded = pb.SetForwardingPipelineConfigRequest()
                forwarded.CopyFrom(request)
                forwarded.election_id.CopyFrom(self.state.backend.election)
                self.state.backend.require_master()
                self.state.backend.stub.SetForwardingPipelineConfig(forwarded, timeout=10)
            self.state.pipeline[self.role] = config
            self.state.persist()
            logging.warning('P4 pipeline device=%s role=%s state=%s',request.device_id,self.role,
                            'active' if self.state.authority.writable(self.role) else 'staged')
            return pb.SetForwardingPipelineConfigResponse()

    def GetForwardingPipelineConfig(self, request, context):
        self._check(request, context)
        config = self.state.pipeline.get(self.role)
        if config is None:
            context.abort(grpc.StatusCode.FAILED_PRECONDITION, "Pipeline not configured")
        return pb.GetForwardingPipelineConfigResponse(config=config)

    def Write(self, request, context):
        self._check(request, context)
        with self.state.authority.lock:
            desired = dict(self.state.entries[self.role])
            forwarded_updates = []
            for update in request.updates:
                try: key = self.state.validate(self.role, update.entity, desired, update.type == pb.Update.DELETE)
                except ValueError as exc: context.abort(grpc.StatusCode.INVALID_ARGUMENT, str(exc))
                old = desired.get(key)
                if update.type == pb.Update.DELETE:
                    desired.pop(key, None)
                elif update.type in (pb.Update.INSERT, pb.Update.MODIFY):
                    desired[key] = copy.deepcopy(update.entity)
                else: context.abort(grpc.StatusCode.INVALID_ARGUMENT, "Invalid update operation")
                if self.state.authority.writable(self.role):
                    if update.type == pb.Update.DELETE and old is None: continue
                    if old is not None and content(old) == content(update.entity) and update.type != pb.Update.DELETE: continue
                    forwarded = pb.Update()
                    forwarded.CopyFrom(update)
                    if forwarded.type == pb.Update.INSERT and old is not None: forwarded.type = pb.Update.MODIFY
                    forwarded_updates.append(forwarded)
            if self.state.authority.active == self.role and self.state.authority.frozen:
                context.abort(grpc.StatusCode.PERMISSION_DENIED, "Source fenced")
            if self.state.authority.writable(self.role): self.state.backend.write(forwarded_updates)
            self.state.entries[self.role] = desired
            self.state.persist()
            logging.warning('P4 write device=%s role=%s state=%s updates=%s forwarded=%s generation=%s',
                request.device_id,self.role,'active' if self.state.authority.writable(self.role) else 'staged',
                len(request.updates),len(forwarded_updates),self.state.authority.generation)
            return pb.WriteResponse()

    def Read(self, request, context):
        self._check(request, context)
        with self.state.authority.lock:
            hardware_request = pb.ReadRequest()
            hardware_request.CopyFrom(request)
            for entity in hardware_request.entities:
                kind = entity.WhichOneof("entity")
                if kind in {"counter_entry", "meter_entry"}:
                    entry = getattr(entity, kind)
                    # The Release 7 client uses -1 for wildcard. P4Runtime
                    # specifies an absent Index for wildcard reads.
                    if entry.HasField("index") and entry.index.index < 0:
                        entry.ClearField("index")
            desired_kinds = {"table_entry", "action_profile_member", "action_profile_group"}
            if self.state.authority.writable(self.role) or all(
                    entity.WhichOneof("entity") not in desired_kinds for entity in request.entities):
                # Counter reads never confer control authority and are always
                # hardware observations, including from a standby driver.
                yield from self.state.backend.stub.Read(hardware_request, timeout=10)
                return
            rows = self.state.entries[self.role].values()
            logging.warning('P4 read device=%s role=%s source=staged generation=%s',
                            request.device_id,self.role,self.state.authority.generation)
            selected = []
            for pattern in request.entities:
                kind = pattern.WhichOneof("entity")
                if kind not in desired_kinds:
                    context.abort(grpc.StatusCode.UNIMPLEMENTED, "Mixed shadow and hardware reads unsupported")
                for entity in rows:
                    if entity.WhichOneof("entity") != kind:
                        continue
                    if kind == "action_profile_group":
                        pattern_group, group = pattern.action_profile_group, entity.action_profile_group
                        if (not pattern_group.action_profile_id or pattern_group.action_profile_id == group.action_profile_id) and (
                                not pattern_group.group_id or pattern_group.group_id == group.group_id):
                            selected.append(entity)
                        continue
                    if kind == "action_profile_member":
                        pattern_member, member = pattern.action_profile_member, entity.action_profile_member
                        if (not pattern_member.action_profile_id or pattern_member.action_profile_id == member.action_profile_id) and (
                                not pattern_member.member_id or pattern_member.member_id == member.member_id):
                            selected.append(entity)
                        continue
                    table = pattern.table_entry.table_id
                    if table == 0 or table == entity.table_entry.table_id:
                        if not pattern.table_entry.match or entry_key(pattern) == entry_key(entity):
                            selected.append(entity)
            yield pb.ReadResponse(entities=selected)

    def StreamChannel(self, requests, context):
        for request in requests:
            if request.HasField("arbitration"):
                response = pb.StreamMessageResponse()
                response.arbitration.CopyFrom(request.arbitration)
                response.arbitration.status.code = 0
                response.arbitration.status.message = "proxy-active" if self.state.authority.writable(self.role) else "proxy-standby-staged"
                yield response
            elif request.WhichOneof("update"):
                context.abort(grpc.StatusCode.UNIMPLEMENTED, "Packet I/O outside L2 fixture")

    def Capabilities(self, request, context):
        return pb.CapabilitiesResponse(p4runtime_api_version="1.3.0")


def serve(fixture):
    directory = os.environ.get('P4_STATE_DIRECTORY')
    authority = Authority(journal=Path(directory)/'authority.json' if directory else None)
    states = []
    servers = []
    for device in fixture["emulator"]["devices"]:
        state = SwitchState(Backend(f"mininet:{device['grpc_port']}", device["dpid"]), authority)
        states.append(state)
        for role, offset in (("sat-a", 0), ("sat-b", 1000)):
            server = grpc.server(ThreadPoolExecutor(max_workers=8))
            rpc.add_P4RuntimeServicer_to_server(Proxy(state, role), server)
            server.add_insecure_port(f"0.0.0.0:{device['proxy_port'] + offset}")
            server.start()
            servers.append(server)
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(200); self.end_headers()
            self.wfile.write(json.dumps({"active": authority.active, "frozen": authority.frozen,
                                        "ipv4": socket.gethostbyname(socket.gethostname()),
                                        "generation": authority.generation, "ack": authority.ack,
                                        "states": [{"device_id": state.backend.device_id,
                                                    "upstream_master": state.backend.master.is_set(),
                                                    "standby_ready": state.ready('sat-b'),
                                                    "staged_entries": len(state.entries["sat-b"])} for state in states]}).encode())
        def do_POST(self):
            try:
                body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                if self.path == "/freeze": authority.freeze()
                elif self.path == "/ready":
                    if not authority.ready(images=body["images"], api=body["api"],
                                           staged=all(state.ready('sat-b') for state in states)):
                        raise RuntimeError("Readiness checks incomplete")
                elif self.path == "/cutover":
                    authority.cutover("sat-b", lambda: [state.reconcile("sat-b") for state in states])
                elif self.path == "/recover":
                    authority.recover("sat-a", lambda: [state.reconcile("sat-a") for state in states])
                elif self.path == "/revoke":
                    with authority.lock:
                        authority.active = None
                        authority.frozen = True
                        authority.ack = authority.verified = False
                        authority.persist()
                elif self.path == "/clear-standby":
                    with authority.lock:
                        if authority.active != 'sat-a': raise RuntimeError('Source ownership required')
                        authority.ack = authority.verified = False
                        authority.persist()
                        for state in states:
                            state.entries['sat-b'] = {}
                            state.pipeline.pop('sat-b', None)
                            state.persist()
                else: raise ValueError("Unknown operation")
                self.send_response(200); self.end_headers(); self.wfile.write(b'{}')
            except Exception as exc:
                self.send_response(409); self.end_headers(); self.wfile.write(json.dumps({"error": str(exc)}).encode())
    ThreadingHTTPServer(("0.0.0.0", 8090), Handler).serve_forever()


if __name__ == "__main__":
    import sys
    with open(sys.argv[1]) as handle: serve(json.load(handle))
