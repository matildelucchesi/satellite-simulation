"""Standalone SVG figures; absent observations are shown as absent."""
def plots(directory, result):
    import matplotlib
    matplotlib.use('Agg')
    from matplotlib.figure import Figure
    measured=[(i+1,r['controller_downtime_s']) for i,r in enumerate(result['migration_summary'])
              if r.get('controller_downtime_s') is not None]
    figure=Figure(figsize=(9,3.5),layout='constrained');axis=figure.subplots()
    if measured:
        axis.bar([p[0] for p in measured],[p[1] for p in measured],color='#2766ae')
        axis.set_xticks([p[0] for p in measured])
    else:axis.text(.5,.5,'Nessun downtime misurato disponibile',ha='center',transform=axis.transAxes)
    axis.set(xlabel='Migrazione',ylabel='Downtime controller (s)',title='Stop/freeze → cutover confermato')
    figure.savefig(directory/'downtime.svg',metadata={'Date':None})
    history=result['controller_history'];figure=Figure(figsize=(9,3.5),layout='constrained');axis=figure.subplots()
    if history:
        identifiers=list(dict.fromkeys(r['satellite_id'] for r in history))
        points=history+[{'orbital_s':result.get('final_orbital_s') or history[-1]['orbital_s'],
                         'satellite_id':history[-1]['satellite_id']}]
        start=history[0]['orbital_s']
        axis.step([r['orbital_s']-start for r in points],
                  [identifiers.index(r['satellite_id']) for r in points],where='post',color='#2766ae')
        axis.set_yticks(range(len(identifiers)),[str(sid) for sid in identifiers])
    else:axis.text(.5,.5,'Nessun posizionamento live confermato',ha='center',transform=axis.transAxes)
    axis.set(xlabel='Tempo orbitale trascorso (s)',ylabel='Satellite NORAD',title='Cronologia del posizionamento del controller')
    figure.savefig(directory/'controller-history.svg',metadata={'Date':None})
