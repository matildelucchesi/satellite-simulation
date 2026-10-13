import ast
import unittest
from pathlib import Path
from types import SimpleNamespace


class ServicePatchTests(unittest.TestCase):
    def test_delete_rules_reverse_dependencies_with_stable_keys(self):
        source = Path(__file__).parents[1]/'deploy/patches/p4_fabric_tna_l2_simple_service_handler.py'
        method = next(node for node in ast.walk(ast.parse(source.read_text(encoding='utf-8')))
                      if isinstance(node, ast.FunctionDef) and node.name == '_create_rules')
        namespace = {'ConfigActionEnum': SimpleNamespace(CONFIGACTION_SET=1, CONFIGACTION_DELETE=2)}
        def helper(key):
            return lambda **kw: [{'custom': {'resource_key': key+'[0]', 'resource_value': {'port': 2}}}]
        for name, key in [('rules_set_up_port_host', '/tables/port'),
                          ('rules_set_up_port_switch', '/tables/port'),
                          ('rules_set_up_fwd_bridging', '/tables/bridging'),
                          ('rules_set_up_next_profile_hashed_output', '/action_profiles/member'),
                          ('rules_set_up_next_hashed', '/tables/hashed')]:
            namespace[name] = helper(key)
        exec(compile(ast.Module(body=[method], type_ignores=[]), str(source), 'exec'), namespace)
        handler = SimpleNamespace(_get_vlan_id_of_switch_port=lambda *args: 4094,
                                  _is_host_facing_port=lambda *args: True,
                                  _get_fwd_list_of_switch_port=lambda *args: ['00:00:00:00:00:02'])
        device = SimpleNamespace(name='sat-53848')
        inserted = namespace['_create_rules'](handler, device, 2, 1)
        deleted = namespace['_create_rules'](handler, device, 2, 2)
        keys = lambda rules: [rule['custom']['resource_key'] for rule in rules]
        self.assertEqual(keys(inserted), list(reversed(keys(deleted))))
        self.assertTrue(deleted[0]['custom']['resource_key'].startswith('/tables/hashed'))
        self.assertTrue(deleted[1]['custom']['resource_key'].startswith('/action_profiles/member'))
        self.assertTrue(all(rule['action'] == 2 for rule in deleted))
