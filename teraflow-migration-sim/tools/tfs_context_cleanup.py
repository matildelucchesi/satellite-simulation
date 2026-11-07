"""List (default) or remove (--remove) the migration-lab inventory through the Context gRPC API.

Runs inside a TeraFlow contextservice container. Removes only lab-owned entities: services and
topologies of the 'migration-lab' context, links named isl-*, devices named sat-*, then the
'migration-lab' context itself. The 'admin' context and topology are left in place.
"""
import json
import sys

from common.proto.context_pb2 import Empty
from context.client.ContextClient import ContextClient

remove = '--remove' in sys.argv
client = ContextClient(host='127.0.0.1', port=1010)
report = {'remove': remove}

contexts = client.ListContexts(Empty()).contexts
lab = [c for c in contexts if c.name == 'migration-lab']
report['contexts'] = [c.name for c in contexts]

services, topologies = [], []
for context in lab:
    services += list(client.ListServices(context.context_id).services)
    topologies += list(client.ListTopologies(context.context_id).topologies)
links = [l for l in client.ListLinks(Empty()).links if l.name.startswith('isl-')]
devices = [d for d in client.ListDevices(Empty()).devices if d.name.startswith('sat-')]
others = [d.name for d in client.ListDevices(Empty()).devices if not d.name.startswith('sat-')]
report.update(services=len(services), topologies=[t.name for t in topologies], links=len(links),
              devices=len(devices), device_names_sample=sorted(d.name for d in devices)[:5], other_devices=others)

connections = [c for s in services for c in client.ListConnections(s.service_id).connections]
report['connections'] = len(connections)

if remove:
    for connection in connections:
        client.RemoveConnection(connection.connection_id)
    for service in services:
        client.RemoveService(service.service_id)
    for link in links:
        client.RemoveLink(link.link_id)
    for device in devices:
        client.RemoveDevice(device.device_id)
    for topology in topologies:
        client.RemoveTopology(topology.topology_id)
    for context in lab:
        client.RemoveContext(context.context_id)
    after_devices = [d.name for d in client.ListDevices(Empty()).devices if d.name.startswith('sat-')]
    after_links = [l.name for l in client.ListLinks(Empty()).links if l.name.startswith('isl-')]
    report['after'] = {'devices': len(after_devices), 'links': len(after_links),
                       'contexts': [c.name for c in client.ListContexts(Empty()).contexts]}
print(json.dumps(report))
