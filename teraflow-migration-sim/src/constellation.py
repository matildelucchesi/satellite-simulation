"""Explicit, archived expansion using real records from the frozen catalog."""
import copy
import json
import math
import shutil
from dataclasses import asdict
from pathlib import Path
from .storage import atomic_json
from .artifacts import file_digest


def expanded_selection(original, candidates, targets=None):
    from tools.select_constellation import phase_at
    from sgp4.api import Satrec
    result=copy.deepcopy(original);metadata=result['metadata']
    reference=metadata['reference_epoch'];rows=[];bounds={}
    for plane in (1,2):
        old=[row for row in original['satellites'] if row['plane']==plane]
        low=min(row['raan_deg'] for row in old)-.1
        high=max(row['raan_deg'] for row in old)+.1
        if targets and targets[plane-1]>len(old):
            center=metadata['selected_plane_raan_centers_deg'][plane-1]
            low=min(low,center-1.5);high=max(high,center+1.5)
        bounds[str(plane)]=[low,high]
        selected=[row for row in candidates if low<=row.raan_deg<=high and
            52.5<=row.inclination_deg<=53.5 and 450<=row.screening_altitude_km<=580]
        center=math.radians(metadata['selected_plane_raan_centers_deg'][plane-1])
        inclination=math.radians(sum(row['inclination_deg'] for row in old)/len(old))
        first=(math.cos(center),math.sin(center),0)
        second=(-math.sin(center)*math.cos(inclination),math.cos(center)*math.cos(inclination),math.sin(inclination))
        phases={}
        for row in selected:
            error,position,_=Satrec.twoline2rv(row.tle_line1,row.tle_line2).sgp4(reference['jd'],reference['fraction'])
            if error:raise ValueError('SGP4 error in real candidate')
            phases[row.norad_id]=math.atan2(sum(a*b for a,b in zip(position,second)),sum(a*b for a,b in zip(position,first)))%(2*math.pi)
        if targets:
            target=targets[plane-1]
            if target<len(old) or target>len(selected):raise ValueError('Unavailable real satellite target')
            keep={row['norad_id'] for row in old}
            chosen=[row for row in selected if row.norad_id in keep]
            while len(chosen)<target:
                angles=[phases[row.norad_id] for row in chosen]
                def separation(row):
                    angle=phases[row.norad_id]
                    return (min(abs((angle-other+math.pi)%(2*math.pi)-math.pi) for other in angles),-row.norad_id)
                chosen.append(max((row for row in selected if row not in chosen),key=separation))
            selected=chosen
        selected.sort(key=lambda row:(phases[row.norad_id],row.norad_id))
        for rank,candidate in enumerate(selected,1):
            row=asdict(candidate);row.pop('tle_line1');row.pop('tle_line2')
            rows.append({**row,'plane':plane,'phase_rank':rank,
                'orbital_phase_rad_at_reference':phases[candidate.norad_id],
                'mean_anomaly_rad_at_reference':phase_at(candidate,reference['jd'],reference['fraction']),
                'tle_age_hours_at_reference':((reference['jd']+reference['fraction'])-
                    (candidate.epoch_jd+candidate.epoch_jd_fraction))*24})
    identifiers=[row['norad_id'] for row in rows]
    if len(set(identifiers))!=len(identifiers) or not {row['norad_id'] for row in original['satellites']}.issubset(identifiers):
        raise ValueError('Expansion must preserve every original satellite without duplicates')
    if len(rows)<=len(original['satellites']):raise ValueError('No additional real satellites')
    metadata['screen']['screening_altitude_km']=[450,580]
    metadata['original_screened_count']=metadata['screened_count']
    metadata['screened_count']=sum(52.5<=row.inclination_deg<=53.5 and 450<=row.screening_altitude_km<=580 for row in candidates)
    metadata['original_raan_groups']=metadata.pop('raan_groups',metadata.get('original_raan_groups',[]))
    metadata['selected_plane_raan_centers_deg']=[math.degrees(math.atan2(
        sum(math.sin(math.radians(row['raan_deg'])) for row in rows if row['plane']==plane),
        sum(math.cos(math.radians(row['raan_deg'])) for row in rows if row['plane']==plane)))%360 for plane in (1,2)]
    metadata['selected_tle_age_hours']={'minimum':min(row['tle_age_hours_at_reference'] for row in rows),
        'maximum':max(row['tle_age_hours_at_reference'] for row in rows)}
    metadata['selected_plane_satellite_counts']=[sum(row['plane']==plane for row in rows) for plane in (1,2)]
    metadata['expansion']={'policy':'real-frozen-same-plane-bounds-v2' if targets else 'real-frozen-same-plane-bounds-v1','original_count':len(original['satellites']),
        'targets':targets,'phase_selection':'greedy maximum minimum SGP4 position-angle separation at common epoch, retaining originals' if targets else 'all eligible records',
        'plane_raan_bounds_deg':bounds,'synthetic_satellites':False}
    result['satellites']=rows
    return result


def contact_windows(orbit, alignment_s, check=lambda:None):
    """Vectorized equivalent of Orbit.graph on the same one-second replay."""
    import numpy as np
    rows=[]
    for ai,a in enumerate(orbit.ids):
        check()
        for bi in range(ai+1,len(orbit.ids)):
            b=orbit.ids[bi];first=orbit.positions[:,ai];difference=orbit.positions[:,bi]-first
            squared=np.sum(difference*difference,axis=1)
            fraction=np.clip(-np.sum(first*difference,axis=1)/np.maximum(squared,1e-30),0,1)
            nearest=first+fraction[:,None]*difference
            available=(squared>0)&(squared<=orbit.max_range**2)&(np.sum(nearest*nearest,axis=1)>orbit.radius**2)
            changes=np.diff(np.concatenate(([False],available,[False])).astype(np.int8))
            for start,end in zip(np.flatnonzero(changes==1),np.flatnonzero(changes==-1)):
                rows.append({'sat_a':a,'sat_b':b,'start_s':int(start),'end_s':int(end),
                    'duration_s':int(end-start),'alignment_fits':bool(end-start>=alignment_s)})
    return {'inputs':{'duration_s':orbit.duration,'step_s':1,'range_km':orbit.max_range,'alignment_s':alignment_s},
        'sgp4_errors_by_norad':{},'window_count':len(rows),
        'windows_at_least_alignment_count':sum(row['alignment_fits'] for row in rows),'windows':rows}


def expand(app):
    from tools.select_constellation import parse_tle
    from .deployment import compose_command
    from .live_backend import Compose,http
    from .processes import run_process
    from .orbit import generate,Orbit
    from .fixture import build
    root=app.root
    def check():
        if app.cancel and app.cancel.is_set():raise InterruptedError('Constellation update interrupted')
    def stage(label):
        check();app.publish({'phase':'constellation_update','label':label})
    original=json.loads((root/'config/selected_constellation.json').read_text())
    targets=(28,36) if len(original['satellites'])==42 else None
    selection=expanded_selection(original,parse_tle(root/app.scenario['orbital']['tle_file']),targets)
    profile=root/('artifacts/constellation-profiles/real-450-580-64' if targets else 'artifacts/constellation-profiles/real-450-580')
    if profile.exists():raise ValueError('Archived expansion already exists; inspect it before another update')
    stage('Revoca autorità e arresto del laboratorio prima del cambio costellazione')
    http(18091,'/revoke',{});http(18090,'/probes/stop',{})
    compose=Compose(root);compose.stop('sat-a');compose.stop('sat-b')
    stopped=run_process(compose_command('stop','-t','10','p4-proxy','mininet'),cwd=root,timeout=60,check=check)
    if stopped.returncode:raise RuntimeError(stopped.stderr)
    app.checkpoint(kind='constellation_update',phase='archiving')
    profile.mkdir(parents=True)
    archived={}
    for name in ('config/scenario.json','config/selected_constellation.json','config/fixture.json',
                 'config/lab-manifest.json','config/artifact_manifest.json','results/calibration.json','results/functional-gate.json',
                 'results/direct_link_windows.json','artifacts/orbit/replay.npz','artifacts/orbit/replay.json'):
        source=root/name
        if source.exists():
            target=profile/'original'/name;target.parent.mkdir(parents=True,exist_ok=True)
            shutil.copy2(source,target);archived[name]=file_digest(target)
    atomic_json(profile/'archive.json',archived)
    atomic_json(root/'config/selected_constellation.json',selection)
    scenario=copy.deepcopy(app.scenario);orbital=scenario['orbital']
    orbital.update(satellites_total=len(selection['satellites']),
        selected_raan_centers_deg=selection['metadata']['selected_plane_raan_centers_deg'],
        satellites_per_plane=selection['metadata']['selected_plane_satellite_counts'],
        sgp4_mean_semi_major_axis_altitude_screening_km=[450.0,580.0],
        selected_altitude_range_km=[min(row['screening_altitude_km'] for row in selection['satellites']),
                                   max(row['screening_altitude_km'] for row in selection['satellites'])],
        constellation_profile='real-450-580-64' if targets else 'real-450-580')
    atomic_json(root/'config/scenario.json',scenario)
    stage('Propagazione SGP4 dei satelliti reali e calcolo illuminazione')
    destination=profile/'replay.npz';generate(root,destination)
    stage('Calcolo finestre di contatto sul nuovo replay')
    orbit=Orbit(destination,max_range_km=scenario['fso']['max_range_km'])
    windows=contact_windows(orbit,scenario['fso']['alignment_s'],check)
    windows['inputs']['start_epoch']=scenario['orbital']['reference_epoch_utc']
    atomic_json(root/'results/direct_link_windows.json',windows)
    atomic_json(root/'config/fixture.json',build(root))
    lab=json.loads((root/'config/lab-manifest.json').read_text())
    from .artifacts import describe
    lab['fixture']=describe(root/'config/fixture.json');atomic_json(root/'config/lab-manifest.json',lab)
    shutil.copy2(destination,root/'artifacts/orbit/replay.npz')
    shutil.copy2(destination.with_suffix('.json'),root/'artifacts/orbit/replay.json')
    invalidate_functional_gate(root,profile)
    result={'complete':True,'controllers_fenced':True,'laboratory_restart_required':True,
        'satellites':len(orbit.ids),'per_plane':orbital['satellites_per_plane'],
        'profile':str(profile),'windows':len(windows['windows']),'original_archive':archived,
        'new_calibration_required':True}
    atomic_json(profile/'expansion.json',result)
    app.checkpoint(kind='between_runs',phase='constellation_updated')
    return result


def invalidate_functional_gate(root, profile):
    gate=root/'results/functional-gate.json'
    archived=profile/'original/results/functional-gate.json'
    if gate.exists() and not archived.exists():
        archived.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(gate,archived)
    atomic_json(gate,{'complete':False,'reason':'Costellazione aggiornata: nuova verifica funzionale richiesta',
        'previous_evidence':str(archived)})
