"""Shared Compose identity and per-satellite selectors."""
PROJECT = 'teraflow'
ROLE_LABEL = 'org.teraflow.role'
ROLES = ('sat-a', 'sat-b')
VOLUMES = ('sat-a_crdb-data', 'sat-a_kafka-data', 'sat-b_crdb-data',
           'sat-b_kafka-data', 'migration-lab_proxy-state')


def compose_command(*arguments):
    return ['docker', 'compose', '--env-file', 'deploy/lab.env', '-p', PROJECT,
            '-f', 'deploy/stack.yaml', *arguments]


def role_services(role, services):
    if role not in ROLES:
        raise ValueError('Unknown laboratory host')
    return [role + '-' + service for service in services]


def container_filters(role):
    if role not in ROLES:
        raise ValueError('Unknown laboratory host')
    return ['--filter', 'label=com.docker.compose.project=' + PROJECT,
            '--filter', 'label=' + ROLE_LABEL + '=' + role]
