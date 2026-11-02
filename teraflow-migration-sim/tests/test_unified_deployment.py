import unittest
import ipaddress
import re
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
import yaml
from tools.generate_stack import build
from src.live_backend import Compose, WORKLOAD
from src.deployment import container_filters


class UnifiedDeploymentTests(unittest.TestCase):
    def test_controller_cpu_limits_fit_six_core_host_without_relaxing_reserve(self):
        import json
        stack=build();root=Path(__file__).parents[1]
        controller=json.loads((root/'config/scenario.json').read_text())['controller']
        self.assertEqual(controller['resource_profile']['cpu_cores'],6)
        available=6*(1-controller['background_load_model']['candidate_cpu_start_percent']/100-controller['resource_reserve_fraction'])
        for role in ('sat-a','sat-b'):
            budget=sum(stack['services'][role+'-'+name]['cpus'] for name in ('cockroachdb','nats','kafka',*WORKLOAD))
            self.assertAlmostEqual(budget,2.2)
            self.assertLess(budget,available)

    def test_default_subnets_cannot_overlap_during_parallel_creation(self):
        networks = build()['networks']
        subnets = [ipaddress.ip_network(re.search(r':-([^}]+)',
            network['ipam']['config'][0]['subnet'])[1]) for network in networks.values()]
        for index, subnet in enumerate(subnets):
            for other in subnets[index + 1:]:
                self.assertFalse(subnet.overlaps(other))

    def test_generated_file_matches_templates(self):
        path = Path(__file__).parents[1] / 'deploy/stack.yaml'
        self.assertEqual(yaml.safe_load(path.read_text()), build())

    def test_satellites_keep_separate_dns_and_persistent_data(self):
        stack = build()
        for role in ('sat-a', 'sat-b'):
            for name in ('cockroachdb', 'nats', 'kafka', *WORKLOAD):
                service = stack['services'][role + '-' + name]
                private = set(service['networks']) - {'lab'}
                self.assertEqual(private, {role})
                self.assertEqual(service['networks'][role]['aliases'], [name])
                self.assertEqual(service['labels']['org.teraflow.role'], role)
                for dependency in service.get('depends_on', {}):
                    self.assertTrue(dependency == 'p4-proxy' or dependency.startswith(role + '-'))
                    self.assertIn(dependency, stack['services'])
            volume = stack['volumes'][role + '-crdb-data']
            self.assertTrue(volume['external'])
            self.assertEqual(volume['name'], role + '_crdb-data')
        self.assertEqual(stack['volumes']['proxy-state']['name'], 'migration-lab_proxy-state')
        self.assertEqual(stack['services']['sat-a-nbiservice']['ports'], ['127.0.0.1:18080:8080'])
        self.assertEqual(stack['services']['sat-b-nbiservice']['ports'], ['127.0.0.1:18081:8080'])

    def test_stopping_source_does_not_stop_target_or_dependencies(self):
        with patch('src.live_backend.run_process', return_value=SimpleNamespace(returncode=0, stdout='')) as run:
            Compose(Path('.')).stop('sat-a')
        command = run.call_args.args[0]
        self.assertEqual(command[command.index('-p') + 1], 'teraflow')
        self.assertEqual(command[-len(WORKLOAD):], ['sat-a-' + service for service in WORKLOAD])
        self.assertNotIn('sat-b-nbiservice', command)
        self.assertNotIn('sat-a-cockroachdb', command)
        self.assertNotIn('mininet', command)

    def test_disk_selector_requires_both_project_and_satellite(self):
        self.assertEqual(container_filters('sat-b'), ['--filter', 'label=com.docker.compose.project=teraflow',
            '--filter', 'label=org.teraflow.role=sat-b'])
        with self.assertRaises(ValueError): container_filters('foreign')
