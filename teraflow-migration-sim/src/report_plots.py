"""Scientific figures derived exclusively from saved measurements."""
from collections import defaultdict


def plots(directory, runs):
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    available = []
    specifications = [
        ('service-recovery','Time to stable service recovery (s)',
         lambda r:r.get('probes',{}).get('ping',{}).get('time_to_stable_recovery_s')),
        ('throughput','Measured useful image throughput (Gbit/s)',
         lambda r:r.get('image_throughput_bps')/1e9 if r.get('image_throughput_bps') is not None else None),
        ('retries','Payload attempts after first attempt',lambda r:max(0,r['attempt']-1) if 'attempt' in r else None),
        ('disk-content','Modeled host logical disk content (GiB)',lambda r:r.get('disk_accounting',{}).get('disk_gib')),
        ('contact-margin','Residual contact margin (s)',lambda r:r.get('event',{}).get('contact_window_s')-r['total_operation_s']
            if r.get('total_operation_s') is not None and r.get('event',{}).get('contact_window_s') is not None else None)]
    for name,label,value in specifications:
        measured = [(run,value(run)) for run in runs if value(run) is not None]
        if not measured:continue
        figure,axis = plt.subplots(figsize=(max(7,len(measured)*.45),4))
        axis.bar(range(len(measured)),[v for _,v in measured],
            color=['#176b66' if r['method']=='hot' else '#a35435' for r,_ in measured])
        axis.set_ylabel(label)
        axis.set_xticks(range(len(measured)),[r['method']+' '+r['run_id'][-6:] for r,_ in measured],rotation=60,ha='right')
        axis.axhline(0,color='#333',linewidth=.6);axis.grid(axis='y',alpha=.25)
        figure.tight_layout();filename=name+'.svg';figure.savefig(directory/filename);plt.close(figure)
        available.append((filename,label))
    measured = [r for r in runs if r.get('operations')]
    if measured:
        phases = sorted({p['operation'] for r in measured for p in r['operations']})
        figure,axis=plt.subplots(figsize=(max(9,len(measured)*.5),5))
        totals=[0.]*len(measured)
        for phase in phases:
            values=[sum(p['elapsed_s'] for p in r['operations'] if p['operation']==phase) for r in measured]
            axis.bar(range(len(measured)),values,bottom=totals,label=phase)
            totals=[a+b for a,b in zip(totals,values)]
        axis.set_ylabel('Measured phase durations (s)')
        axis.set_xticks(range(len(measured)),[r['run_id'][-6:] for r in measured],rotation=60)
        axis.legend(fontsize=7,loc='upper left',bbox_to_anchor=(1,1))
        figure.tight_layout();figure.savefig(directory/'phase-durations.svg');plt.close(figure)
        available.append(('phase-durations.svg','Tempi delle operazioni misurate; attività concorrenti possono sovrapporsi'))
    return available
