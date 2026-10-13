"""Exercise the generated upstream method with a recording P4 manager."""
import ast
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock


class DevicePatchTests(unittest.TestCase):
    def test_indirect_table_insert_update_delete_and_failures(self):
        source = Path(__file__).parents[1]/'deploy/patches/p4_manager.py'
        tree = ast.parse(source.read_text(encoding='utf-8'))
        method = next(node for node in ast.walk(tree)
                      if isinstance(node, ast.FunctionDef) and node.name == 'table_entry_operation_from_json')
        for argument in method.args.args: argument.annotation = None
        namespace = {'WriteOperation': SimpleNamespace(insert='insert', update='update', delete='delete'),
                     'parse_resource_string_from_json': lambda row, key: row.get(key),
                     'parse_match_operations_from_json': lambda row: {'next_id': '2'},
                     'P4RuntimeException': RuntimeError, 'P4RuntimeWriteException': RuntimeError}
        exec(compile(ast.Module(body=[method], type_ignores=[]), str(source), 'exec'), namespace)
        for field in ('member-id', 'group-id'):
            for operation in ('insert', 'update', 'delete'):
                with self.subTest(field=field, operation=operation):
                    entry = Mock(); entry.match = {}
                    namespace['TableEntry'] = Mock(return_value=entry)
                    value = {'table-name': 'hashed', field: 2}
                    namespace['table_entry_operation_from_json'](SimpleNamespace(local_client='client'), value, operation)
                    self.assertEqual(getattr(entry, field.replace('-', '_')), 2)
                    getattr(entry, 'modify' if operation == 'update' else operation).assert_called_once_with()
        entry = Mock(); entry.match = {}; entry.insert.side_effect = RuntimeError('PERMISSION_DENIED')
        namespace['TableEntry'] = Mock(return_value=entry)
        with self.assertRaisesRegex(RuntimeError, 'PERMISSION_DENIED'):
            namespace['table_entry_operation_from_json'](SimpleNamespace(local_client='client'),
                                                          {'table-name': 'hashed', 'member-id': 2}, 'insert')
        entry.modify.assert_not_called()
        entry.insert.side_effect = RuntimeError('ALREADY_EXISTS')
        namespace['table_entry_operation_from_json'](SimpleNamespace(local_client='client'),
                                                     {'table-name': 'hashed', 'member-id': 2}, 'insert')
        entry.modify.assert_called_once_with()

    def test_dispatch_for_all_write_operations_and_invalid_entities(self):
        source = Path(__file__).parents[1]/'deploy/patches/p4_driver.py'
        tree = ast.parse(source.read_text(encoding='utf-8'))
        method = next(node for node in ast.walk(tree)
                      if isinstance(node, ast.FunctionDef) and node.name == '__apply_operation')
        method.name = 'apply'
        for argument in method.args.args: argument.annotation = None
        names = {node.id for node in ast.walk(method) if isinstance(node, ast.Name) and node.id.startswith('KEY_')}
        namespace = {name: '/'+name.lower()+'/' for name in names}
        namespace['KEY_ACTION_PROFILE'] = '/action_profiles/'
        exec(compile(ast.Module(body=[method], type_ignores=[]), str(source), 'exec'), namespace)
        for operation in ('insert', 'update', 'delete'):
            for field, called, skipped in (
                ('member-id', 'action_prof_member_entry_operation_from_json', 'action_prof_group_entry_operation_from_json'),
                ('group-id', 'action_prof_group_entry_operation_from_json', 'action_prof_member_entry_operation_from_json')):
                with self.subTest(operation=operation, field=field):
                    manager = Mock()
                    value = {'action-profile-name': 'hashed_profile', field: 2}
                    self.assertTrue(namespace['apply'](SimpleNamespace(__manager=manager),
                                    '/action_profiles/action_profile/hashed_profile[2]', value, operation))
                    getattr(manager, called).assert_called_once_with(value, operation)
                    getattr(manager, skipped).assert_not_called()
        for value in ({}, {'member-id': 2, 'group-id': 2}):
            manager = Mock()
            with self.assertRaises(ValueError):
                namespace['apply'](SimpleNamespace(__manager=manager), '/action_profiles/x', value, 'insert')
            self.assertEqual(manager.mock_calls, [])
