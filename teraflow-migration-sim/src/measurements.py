"""Resource content accounting with shared image layers counted once per host."""
import json
import re
import subprocess
import tarfile
import tempfile
from pathlib import Path
from .storage import append_json, atomic_json, utc_now


def size_bytes(text):
    match = re.fullmatch(r'\s*([0-9.]+)\s*([KkMGT]?i?B)\s*', text)
    if not match: raise ValueError('Unrecognized Docker byte quantity: '+text)
    scales = {'B':1,'kB':1000,'KB':1000,'MB':1000**2,'GB':1000**3,'TB':1000**4,
              'KiB':1024,'MiB':1024**2,'GiB':1024**3,'TiB':1024**4}
    return float(match[1])*scales[match[2]]


def unique_layer_bytes(bundle):
    with tarfile.open(bundle, 'r:') as archive:
        manifest = json.load(archive.extractfile('manifest.json'))
        layers = {layer for image in manifest for layer in image['Layers']}
        return sum(archive.getmember(layer).size for layer in layers)


def resources(root):
    process = subprocess.run(['docker','stats','--no-stream','--format','{{json .}}'], cwd=root,
                             capture_output=True,text=True,timeout=20,check=True)
    rows = [json.loads(line) for line in process.stdout.splitlines() if line.strip()]
    result = {'timestamp_utc': utc_now(), 'hosts': {}}
    for role in ('sat-a','sat-b'):
        selected = [row for row in rows if row['Name'].startswith(role+'-')]
        result['hosts'][role] = {'running_containers': len(selected),
            'cpu_cores': sum(float(row['CPUPerc'].rstrip('%'))/100 for row in selected),
            'ram_gib': sum(size_bytes(row['MemUsage'].split('/')[0]) for row in selected)/1024**3}
    return result


def disk_content(root, role, bundle):
    process = subprocess.run(['docker','ps','-aq','--filter',f'label=com.docker.compose.project={role}'],
        cwd=root,capture_output=True,text=True,timeout=20,check=True)
    ids = process.stdout.split()
    if not ids: raise RuntimeError('No containers available for disk measurement')
    rows = json.loads(subprocess.check_output(['docker','container','inspect','--size',*ids],cwd=root,text=True,timeout=30))
    writable = sum(row.get('SizeRw',0) for row in rows)
    volumes = 0
    seen = set()
    for row in rows:
        if not row.get('State',{}).get('Running'): continue
        for mount in row.get('Mounts',[]):
            if mount.get('Type') != 'volume': continue
            # Only project-owned volumes, no emulator or other host volumes.
            if not mount.get('Name','').startswith(role+'_'): continue
            if mount['Name'] in seen: continue
            seen.add(mount['Name'])
            raw = subprocess.check_output(['docker','exec',row['Id'],'du','-sb',mount['Destination']],cwd=root,text=True,timeout=30)
            volumes += int(raw.split()[0])
    # Include the preinstalled dependencies, deduplicating layers across all
    # images on this modeled host. This archive is accounting only: the six
    # workload images remain the sole migration image payload.
    image_ids = sorted({row['Image'] for row in rows})
    cache_path = Path(root)/'artifacts/resource-image-accounting.json'
    cache = json.loads(cache_path.read_text()) if cache_path.exists() else {}
    if cache.get('image_ids') != image_ids:
        with tempfile.TemporaryDirectory(prefix='tfs-disk-') as temporary:
            archive_path = Path(temporary)/'all-host-images.tar'
            subprocess.run(['docker','image','save','-o',str(archive_path),*image_ids],
                cwd=root,check=True,capture_output=True,timeout=600)
            cache = {'image_ids':image_ids,'unique_layer_bytes':unique_layer_bytes(archive_path),
                'measured_utc':utc_now(),'method':'docker save of workload and preinstalled dependency image IDs; unique layer paths counted once'}
        atomic_json(cache_path,cache)
    images = cache['unique_layer_bytes']
    return {'disk_gib': (images+writable+volumes)/1024**3,
            'unique_image_layer_bytes': images, 'container_writable_bytes': writable,
            'dependency_volume_bytes': volumes,
            'image_accounting': cache,
            'method': 'logical content bytes: unique image layer tar entries + container SizeRw + du -sb project volumes; excludes filesystem allocation overhead'}
