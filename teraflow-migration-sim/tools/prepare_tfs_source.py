"""Prepare the pinned upstream build context from downloaded GitLab archives.

Requires Python 3.12+ for tarfile's safe data extraction filter.
Downloads must finish successfully before running this tool.
"""
from __future__ import annotations

import hashlib
import json
import shutil
import tarfile
from pathlib import Path, PurePosixPath

ROOT = Path(__file__).resolve().parents[1]
REFERENCE = ROOT / '.reference'


def main() -> None:
    source = json.loads((ROOT / 'config/teraflow-source.json').read_text())
    commit = source['commit']
    context = REFERENCE / 'build-context'
    if context.exists():
        raise SystemExit('Build context already exists; preserve it and inspect before replacing.')
    inputs = [REFERENCE / 'tfs-src.tar.gz', REFERENCE / 'tfs-proto.tar.gz']
    inputs += [REFERENCE / name for name in ('common_requirements.in', 'common_requirements_py313.in', 'LICENSE')]
    for path in inputs:
        if not path.is_file():
            raise SystemExit(f'Missing input: {path}')
    # Validate every archive before writing the build context.
    for path in inputs[:2]:
        with tarfile.open(path, 'r:gz') as archive:
            for member in archive:
                parts = PurePosixPath(member.name).parts
                if not parts or commit not in parts[0]:
                    raise ValueError(f'Unexpected archive root: {member.name}')
                if member.isfile():
                    stream = archive.extractfile(member)
                    while stream.read(1024 * 1024):
                        pass
    context.mkdir()
    for path in inputs[:2]:
        with tarfile.open(path, 'r:gz') as archive:
            for member in archive:
                parts = PurePosixPath(member.name).parts[1:]
                if not parts:
                    continue
                member.name = '/'.join(parts)
                archive.extract(member, context, filter='data')
    for path in inputs[2:]:
        shutil.copyfile(path, context / path.name)
    evidence = {
        'commit': commit,
        'archives_and_files_sha256': {
            path.name: hashlib.file_digest(path.open('rb'), 'sha256').hexdigest()
            for path in inputs
        },
    }
    (ROOT / 'config/teraflow-source-downloads.json').write_text(json.dumps(evidence, indent=2) + '\n')
    print(f'Prepared {context}')


if __name__ == '__main__':
    main()
