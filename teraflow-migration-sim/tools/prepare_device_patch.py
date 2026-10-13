"""Generate the authorized Device action-profile dispatch fix against v7.0.0."""
import difflib
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RELATIVE = 'src/device/service/drivers/p4/p4_driver.py'
OLD = '''        elif KEY_ACTION_PROFILE in resource_key:
            self.__manager.action_prof_member_entry_operation_from_json(
                resource_value, operation)
            self.__manager.action_prof_group_entry_operation_from_json(
                resource_value, operation)
'''
NEW = '''        elif KEY_ACTION_PROFILE in resource_key:
            # A resource represents either a member or a selector group.
            # Parsing both creates an invalid -1 ID for the absent entity.
            member = "member-id" in resource_value
            group = "group-id" in resource_value
            if member == group:
                raise ValueError("Action profile requires exactly one member-id or group-id")
            if member:
                self.__manager.action_prof_member_entry_operation_from_json(
                    resource_value, operation)
            else:
                self.__manager.action_prof_group_entry_operation_from_json(
                    resource_value, operation)
'''
MANAGER_RELATIVE = 'src/device/service/drivers/p4/p4_manager.py'
MANAGER_OLD = '''        match_map = parse_match_operations_from_json(json_resource)
        action_name = parse_resource_string_from_json(
            json_resource, "action-name")
'''
MANAGER_NEW = '''        match_map = parse_match_operations_from_json(json_resource)
        # Indirect table actions reference a profile member or selector group.
        references = [key for key in ("member-id", "group-id") if key in json_resource]
        if references:
            if len(references) != 1 or "action-name" in json_resource:
                raise ValueError("Indirect table requires exactly one action reference")
            identifier = json_resource[references[0]]
            if isinstance(identifier, bool) or not isinstance(identifier, int) or identifier <= 0:
                raise ValueError("Indirect action identifier must be a positive integer")
            entry = TableEntry(self.local_client, table_name)
            for field, value in match_map.items():
                entry.match[field] = value
            setattr(entry, references[0].replace("-", "_"), identifier)
            if "priority" in json_resource:
                entry.priority = parse_resource_integer_from_json(json_resource, "priority")
            if operation == WriteOperation.delete:
                entry.delete()
            elif operation == WriteOperation.update:
                entry.modify()
            elif operation == WriteOperation.insert:
                try:
                    entry.insert()
                except (P4RuntimeException, P4RuntimeWriteException) as exc:
                    if "ALREADY_EXISTS" not in str(exc):
                        raise
                    entry.modify()
            else:
                raise ValueError("Unsupported indirect table operation")
            return entry
        action_name = parse_resource_string_from_json(
            json_resource, "action-name")
'''


def main():
    original = (ROOT/'.reference/build-context'/RELATIVE).read_text(encoding='utf-8')
    if original.count(OLD) != 1:
        raise ValueError('Unexpected upstream Device source; patch refused')
    updated = original.replace(OLD, NEW)
    directory = ROOT/'deploy/patches'
    directory.mkdir(exist_ok=True)
    output = directory/'p4_driver.py'
    output.write_text(updated, encoding='utf-8', newline='\n')
    patch = directory/'device-action-profile-dispatch.patch'
    patch.write_text(''.join(difflib.unified_diff(original.splitlines(True), updated.splitlines(True),
                     fromfile='a/'+RELATIVE, tofile='b/'+RELATIVE)), encoding='utf-8', newline='\n')
    metadata = {'upstream_commit': 'fb8707871eba26806cac7ac373c70b2bb5bd26fc',
                'upstream_file': RELATIVE, 'upstream_sha256': hashlib.sha256(original.encode()).hexdigest(),
                'patched_sha256': hashlib.sha256(output.read_bytes()).hexdigest(),
                'patch_sha256': hashlib.sha256(patch.read_bytes()).hexdigest(),
                'authorization': 'User requested correction of the Device error on 2026-10-02'}
    manager = (ROOT/'.reference/build-context'/MANAGER_RELATIVE).read_text(encoding='utf-8')
    if manager.count(MANAGER_OLD) != 1:
        raise ValueError('Unexpected upstream Manager source; patch refused')
    updated_manager = manager.replace(MANAGER_OLD, MANAGER_NEW)
    manager_output = directory/'p4_manager.py'
    manager_output.write_text(updated_manager, encoding='utf-8', newline='\n')
    manager_patch = directory/'device-indirect-table.patch'
    manager_patch.write_text(''.join(difflib.unified_diff(manager.splitlines(True), updated_manager.splitlines(True),
                     fromfile='a/'+MANAGER_RELATIVE, tofile='b/'+MANAGER_RELATIVE)), encoding='utf-8', newline='\n')
    metadata['related_files'] = [{'upstream_file': MANAGER_RELATIVE,
        'upstream_sha256': hashlib.sha256(manager.encode()).hexdigest(),
        'patched_sha256': hashlib.sha256(manager_output.read_bytes()).hexdigest(),
        'patch_sha256': hashlib.sha256(manager_patch.read_bytes()).hexdigest()}]
    (directory/'device-manifest.json').write_text(json.dumps(metadata, indent=2)+'\n')
    print(json.dumps(metadata, indent=2))


if __name__ == '__main__': main()
