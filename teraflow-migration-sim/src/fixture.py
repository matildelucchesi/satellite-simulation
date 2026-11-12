"""Stable satellite ports and a genuine Release 7 L2NM intent."""
from __future__ import annotations
import copy
import json
from pathlib import Path
from uuid import UUID, uuid5
from .snapshot import snapshot

# Service hosts; each is attached to one of the domain's service endpoints.
HOSTS = [{"name": "h1", "ip": "10.0.0.1/24", "mac": "00:00:00:00:00:01"},
         {"name": "h2", "ip": "10.0.0.2/24", "mac": "00:00:00:00:00:02"}]


NAMESPACE = UUID("200e3a1f-2223-534f-a100-758e29c37f40")
def stable_id(name): return str(uuid5(NAMESPACE, name))
CONTEXT_UUID = stable_id("migration-lab")
# Preserve the logical topology identity when membership expands.
TOPOLOGY_UUID = stable_id(CONTEXT_UUID + "/starlink-17")
TOPOLOGY_ID = {"context_id": {"context_uuid": {"uuid": CONTEXT_UUID}}, "topology_uuid": {"uuid": TOPOLOGY_UUID}}
def device_id(sid): return {"device_uuid": {"uuid": stable_id(f"sat-{sid}")}}
def endpoint_id(sid, port):
    did = device_id(sid)
    return {"device_id": did, "endpoint_uuid": {"uuid": stable_id(TOPOLOGY_UUID+"/"+did["device_uuid"]["uuid"]+"/"+str(port))},
            "topology_id": TOPOLOGY_ID}


def hosts(fixture):
    """The two service hosts of this fixture, with the satellite each one is attached to."""
    return fixture["emulator"]["hosts"]


def service_endpoints(fixture):
    first, second = hosts(fixture)
    return first["satellite"], second["satellite"]


def hop_distances(graph, origin):
    """Fewest hops from ``origin`` to every reachable node, as TeraFlow's PathComp counts them."""
    if origin not in graph:
        return {}
    distance, frontier = {origin: 0}, [origin]
    while frontier:
        following = []
        for node in frontier:
            for neighbor in graph[node]:
                if neighbor not in distance:
                    distance[neighbor] = distance[node] + 1
                    following.append(neighbor)
        frontier = following
    return distance


def connection_path(document, connection):
    """Satellite NORAD ids crossed by a TeraFlow connection, in order (``sat-<id>`` device names)."""
    names = {row["device_id"]["device_uuid"]["uuid"]: row["name"] for row in document["entities"]["devices"]}
    path = []
    for hop in connection.get("path_hops_endpoint_ids", []):
        name = names.get(hop["device_id"]["device_uuid"]["uuid"])
        satellite = int(name.split("-", 1)[1]) if name and name.startswith("sat-") else name
        if not path or path[-1] != satellite:
            path.append(satellite)
    return path


def build(root: Path):
    """Emulated network: only the controller's domain; the rest of the constellation stays modeled."""
    windows = json.loads((root / "results/direct_link_windows.json").read_text())["windows"]
    domain = json.loads((root / "config/domain.json").read_text())
    ids = sorted(domain["plane_1"] + domain["plane_2"])
    service_hosts = [{**HOSTS[index], "satellite": sid} for index, sid in enumerate(domain["service_endpoints"])]
    members = set(ids)
    pairs = sorted({tuple(sorted((row["sat_a"], row["sat_b"]))) for row in windows
                    if row["sat_a"] in members and row["sat_b"] in members})
    ports = {sid: {} for sid in ids}
    devices = []
    for index, sid in enumerate(ids):
        neighbors = sorted(b if a == sid else a for a, b in pairs if sid in (a, b))
        ports[sid] = {str(neighbor): port+1 for port, neighbor in enumerate(neighbors)}
        host = next((host for host in service_hosts if host["satellite"] == sid), None)
        if host: ports[sid][host["name"]] = len(neighbors)+1
        devices.append({"norad": sid, "dpid": index+1, "name": f"s{index+1}",
                        "grpc_port": 50001+index, "proxy_port": 51001+index, "ports": ports[sid]})
    return {"schema_version": 1, "context": "migration-lab", "topology": f"starlink-{len(ids)}", "forwarding": "service-path-only",
            "service": "migration-l2", "emulator": {"devices": devices, "pairs": pairs, "hosts": service_hosts},
            "controller_proxy": "p4-proxy", "pipeline_binary": "/experiment/deploy/p4/bmv2.json",
            "pipeline_info": "/experiment/deploy/p4/p4info.txt"}


def state(fixture, graph, role="sat-a"):
    context_id = {"context_uuid": {"uuid": CONTEXT_UUID}}
    topology_id = TOPOLOGY_ID
    entities = {"contexts": [{"context_id": context_id, "name": fixture["context"]}],
                "devices": [], "links": [], "topologies": [], "services": [], "connections": []}
    ports = {row["norad"]: row["ports"] for row in fixture["emulator"]["devices"]}
    for row in fixture["emulator"]["devices"]:
        sid = row["norad"]
        settings = {"id": row["dpid"], "name": f"sat-{sid}", "vendor": "P4.org", "hw_ver": "BMv2",
                    "sw_ver": "simple_switch_grpc", "timeout": 10,
                    "p4bin": fixture["pipeline_binary"], "p4info": fixture["pipeline_info"]}
        settings["endpoints"] = [{"uuid": endpoint_id(sid, port)["endpoint_uuid"]["uuid"],
                                   "name": str(port), "type": "port", "context_uuid": CONTEXT_UUID,
                                   "topology_uuid": TOPOLOGY_UUID} for port in sorted(row["ports"].values())]
        config = []
        for key, value in (("address", fixture["controller_proxy"]),
                           ("port", row["proxy_port"] + (1000 if role == "sat-b" else 0)), ("settings", settings)):
            config.append({"action": "CONFIGACTION_SET", "custom": {"resource_key": "_connect/"+key,
                "resource_value": json.dumps(value, sort_keys=True) if isinstance(value, dict) else str(value)}})
        entities["devices"].append({"device_id": device_id(sid), "name": f"sat-{sid}",
            "device_type": "p4-switch", "device_drivers": ["DEVICEDRIVER_P4"],
            "device_operational_status": "DEVICEOPERATIONALSTATUS_DISABLED",
            "device_config": {"config_rules": config},
            "device_endpoints": [{"endpoint_id": endpoint_id(sid, port), "endpoint_type": "port", "name": str(port)}
                                 for port in sorted(row["ports"].values())]})
    for a, b in fixture["emulator"]["pairs"]:
        if b not in graph[a]: continue
        for source, target in ((a, b), (b, a)):
            entities["links"].append({"link_id": {"link_uuid": {"uuid": stable_id(f"isl-{source}-{target}")}},
                "name": f"isl-{source}-{target}", "link_type": "LINKTYPE_RADIO",
                "link_endpoint_ids": [endpoint_id(source, ports[source][str(target)]),
                                      endpoint_id(target, ports[target][str(source)])]})
    # Include all devices and currently available directed links.
    entities["topologies"] = [{"topology_id": topology_id, "name": fixture["topology"],
        "device_ids": [row["device_id"] for row in entities["devices"]],
        "link_ids": [row["link_id"] for row in entities["links"]]}]
    # Forwarding follows the path TeraFlow chooses. PathComp gives every link cost 1 and picks one
    # of the fewest-hop paths with an internal tie-break, and the service handler programs only
    # the ports of that connection, each with the host MACs that fwd_list sends through it. So the
    # intent describes every switch on some fewest-hop path between the hosts and, for each host,
    # every port one hop closer to it: whichever of those paths TeraFlow takes, its ports carry the
    # right entries, and no switch of it is missing. With a unique fewest-hop path this is exactly
    # that path. Switches off every such path stay out: describing them would change the intent
    # whenever an irrelevant link changes with the geometry (each change recreates the service).
    switch_info = []
    source, target = service_endpoints(fixture)
    to_source, to_target = hop_distances(graph, source), hop_distances(graph, target)
    length = to_target.get(source)
    on_path = {sid for sid in graph if length is not None and sid in to_source and sid in to_target
               and to_source[sid] + to_target[sid] == length}
    toward = {host["name"]: hop_distances(graph, host["satellite"]) for host in hosts(fixture)}
    for row in fixture["emulator"]["devices"]:
        sid = row["norad"]
        if sid not in on_path:
            continue
        port_list = [{"port_id": port, "port_type": "host" if key in {"h1", "h2"} else "switch", "vlan_id": 4094}
                     for key, port in row["ports"].items()]
        fwd = []
        for host in hosts(fixture):
            if host["satellite"] == sid:
                ports_to_host = [row["ports"][host["name"]]]
            else:
                distance = toward[host["name"]]
                ports_to_host = sorted(row["ports"][str(neighbor)] for neighbor in graph[sid]
                                       if neighbor in on_path and distance.get(neighbor) == distance[sid] - 1)
            fwd.extend({"port_id": port, "host_mac": host["mac"]} for port in ports_to_host)
        if not port_list or not fwd:
            continue
        switch_info.append({f"sat-{sid}": {"arch": "v1model", "dpid": row["dpid"],
                                           "port_list": port_list, "fwd_list": fwd}})
    entities["services"] = [{"service_id": {"context_id": context_id, "service_uuid": {"uuid": stable_id(CONTEXT_UUID+"/"+fixture["service"])}},
        "name": fixture["service"], "service_type": "SERVICETYPE_L2NM",
        "service_endpoint_ids": [endpoint_id(host["satellite"], ports[host["satellite"]][host["name"]]) for host in hosts(fixture)],
        "service_constraints": [], "service_config": {"config_rules": [{"action": "CONFIGACTION_SET", "custom": {
            "resource_key": "/settings", "resource_value": json.dumps({"switch_info": switch_info}, sort_keys=True)}}]}}]
    return snapshot(entities)


def with_endpoint_rules(document):
    """Include the endpoint metadata that AddDevice derives from its settings.

    Reconciliation must retain these rules even though the raw fixture leaves
    their creation to discovery. Service-generated forwarding rules stay out.
    """
    result = copy.deepcopy(document)
    for device in result['entities']['devices']:
        rules = device.get('device_config', {}).get('config_rules', [])
        keys = {row.get('custom', {}).get('resource_key') for row in rules}
        settings = next((json.loads(row['custom']['resource_value']) for row in rules
                         if row.get('custom', {}).get('resource_key') == '_connect/settings'), {})
        for endpoint in settings.get('endpoints', []):
            key = '/endpoints/endpoint[' + endpoint['uuid'] + ']'
            if key not in keys:
                rules.append({'action':'CONFIGACTION_SET', 'custom':{
                    'resource_key':key, 'resource_value':json.dumps(endpoint, sort_keys=True)}})
    return snapshot(result['entities'])


def for_destination(document, fixture):
    return for_role(document, fixture, 'sat-b')


def for_role(document, fixture, role):
    if role not in ('sat-a', 'sat-b'):
        raise ValueError('Unknown controller slot')
    result = copy.deepcopy(document)
    by_name = {f"sat-{row['norad']}": row for row in fixture["emulator"]["devices"]}
    for device in result["entities"]["devices"]:
        row = by_name[device["name"]]
        for rule in device["device_config"]["config_rules"]:
            custom = rule.get("custom", {})
            if custom.get("resource_key") == "_connect/port":
                custom["resource_value"] = str(row["proxy_port"] + (1000 if role == 'sat-b' else 0))
    return result
