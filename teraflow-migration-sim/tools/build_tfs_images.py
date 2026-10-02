"""Build the pinned TFS v7 images on Linux while preserving case-sensitive paths.

On Windows, the source tree contains distinct `ACL` and `acl` folders. Extracting
it to a standard Windows directory merges them, so extraction and Docker builds
run from a Docker-managed Linux volume instead.
"""
from __future__ import annotations

import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REFERENCE = ROOT / '.reference'
VOLUME = 'tfs-v7-build-context'
BUILDER = 'docker:29-cli'
LINUX = 'alpine:3.22'
TAG = '7.0.0-fb870787'
IMAGES = (
    ('context', 'src/context/Dockerfile', None),
    ('device', 'src/device/Dockerfile', None),
    ('pathcomp-frontend', 'src/pathcomp/frontend/Dockerfile', None),
    ('pathcomp-backend', 'src/pathcomp/backend/Dockerfile', 'release'),
    ('service', 'src/service/Dockerfile', None),
    ('nbi', 'src/nbi/Dockerfile', None),
)


def run(args: list[str]) -> None:
    print('+', ' '.join(args), flush=True)
    subprocess.run(args, cwd=ROOT, check=True)


def main() -> None:
    for name in ('tfs-src.tar.gz', 'tfs-proto.tar.gz', 'common_requirements.in',
                 'common_requirements_py313.in', 'LICENSE'):
        if not (REFERENCE / name).is_file():
            raise SystemExit(f'Missing pinned source input: {REFERENCE / name}')
    run(['docker', 'volume', 'create', VOLUME])
    mount = str(REFERENCE.resolve()) + ':/input:ro'
    script = (
        'set -eu; '
        'mkdir -p /ctx /tmp/proto; '
        'tar -xzf /input/tfs-src.tar.gz -C /ctx --strip-components=1; '
        'tar -xzf /input/tfs-proto.tar.gz -C /tmp/proto --strip-components=1; '
        'cp -a /tmp/proto/proto /ctx/proto; '
        'cp /input/common_requirements.in /input/common_requirements_py313.in /input/LICENSE /ctx/; '
        'test -f /ctx/src/device/service/drivers/openconfig/templates/acl/acl_adapter.py; '
        'test -f /ctx/src/device/service/drivers/openconfig/templates/ACL/openconfig_acl.py'
    )
    run(['docker', 'run', '--rm', '-v', f'{VOLUME}:/ctx', '-v', mount,
         LINUX, 'sh', '-ec', script])
    build_commands = []
    for name, dockerfile, target in IMAGES:
        image = f'tfs-migration/{name}:{TAG}'
        command = f'docker build -f /ctx/{dockerfile}'
        if target:
            command += f' --target {target}'
        command += f' -t {image} /ctx'
        build_commands.append(command)
    run(['docker', 'run', '--rm', '-v', f'{VOLUME}:/ctx',
         '-v', '/var/run/docker.sock:/var/run/docker.sock', BUILDER,
         'sh', '-ec', ' && '.join(build_commands)])
    print('Built all six TeraFlow workload images from the pinned Linux source tree.')


if __name__ == '__main__':
    main()
