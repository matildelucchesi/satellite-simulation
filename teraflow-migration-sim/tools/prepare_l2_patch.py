"""Generate an auditable local patch against the frozen Release 7 handler."""
import difflib
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RELATIVE = 'src/service/service/service_handlers/p4_fabric_tna_l2_simple/p4_fabric_tna_l2_simple_service_handler.py'
REPLACEMENT = '''    def _create_rules(self, device_obj, port_id, action):
        # Local migration-lab patch: next IDs are actual egress port IDs.
        # L2 frames retain both host MACs; output_hashed selects a single port.
        import hashlib
        import json
        dev_name = device_obj.name
        make = ConfigActionEnum.CONFIGACTION_SET
        vlan = self._get_vlan_id_of_switch_port(dev_name, port_id)
        setup = rules_set_up_port_host if self._is_host_facing_port(dev_name, port_id) else rules_set_up_port_switch
        rules = setup(port=port_id, vlan_id=vlan, action=make)
        destinations = self._get_fwd_list_of_switch_port(dev_name, port_id)
        for mac in destinations:
            rules += rules_set_up_fwd_bridging(port_id=port_id, vlan_id=vlan,
                                              eth_dst=mac, next_id=port_id, action=make)
        if destinations:
            rules += rules_set_up_next_profile_hashed_output(port_id=port_id, next_id=port_id, action=make)
            rules += rules_set_up_next_hashed(port_id=port_id, next_id=port_id, action=make)
        # Stable device rule keys permit deletion/replay across fresh processes;
        # upstream's process-global sequential cache does not identify a rule.
        for rule in rules:
            custom = rule['custom']
            value = custom['resource_value']
            value = json.loads(value) if isinstance(value, str) else value
            base = custom['resource_key'].rsplit('[', 1)[0]
            identity = json.dumps(value, sort_keys=True, separators=(',', ':')).encode()
            index = int.from_bytes(hashlib.sha256(identity).digest()[:4], 'big') or 1
            custom['resource_key'] = base + '[' + str(index) + ']'
            rule['action'] = action
        # Delete table references before their action-profile members.
        return list(reversed(rules)) if action == ConfigActionEnum.CONFIGACTION_DELETE else rules
'''


def main():
    source = ROOT/'.reference/build-context'/RELATIVE
    original = source.read_text(encoding='utf-8')
    marker = '    def _create_rules('
    if original.count(marker) != 1 or 'next_id = 2 if port_id == 1 else 1' not in original:
        raise ValueError('Unexpected upstream handler; patch refused')
    updated = original[:original.index(marker)] + REPLACEMENT
    directory = ROOT/'deploy/patches'; directory.mkdir(exist_ok=True)
    output = directory/source.name
    output.write_text(updated, encoding='utf-8', newline='\n')
    patch = directory/'l2nm-port-forwarding.patch'
    patch.write_text(''.join(difflib.unified_diff(original.splitlines(True), updated.splitlines(True),
                                              fromfile='a/'+RELATIVE, tofile='b/'+RELATIVE)), encoding='utf-8', newline='\n')
    metadata = {'upstream_commit': 'fb8707871eba26806cac7ac373c70b2bb5bd26fc',
                'upstream_file': RELATIVE, 'upstream_sha256': hashlib.sha256(original.encode()).hexdigest(),
                'patched_sha256': hashlib.sha256(output.read_bytes()).hexdigest(),
                'patch_sha256': hashlib.sha256(patch.read_bytes()).hexdigest(),
                'authorization': 'User approved tracked local L2NM compatibility patch on 2026-10-02'}
    (directory/'manifest.json').write_text(json.dumps(metadata, indent=2)+'\n')
    print(json.dumps(metadata, indent=2))


if __name__ == '__main__': main()
