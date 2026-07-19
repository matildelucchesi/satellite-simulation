# Satellite Network Simulation

Scaffold iniziale per una simulazione modulare di una costellazione di cinque
satelliti ispirata a Starlink. I componenti applicativi sono volutamente
limitati a un'app Flask e a un endpoint di health check: la logica di
simulazione verrà aggiunta in una fase successiva.

## Componenti

- `simulator`: motore futuro della simulazione orbitale con Skyfield.
- `satellite_agent`: immagine riutilizzata per i cinque agenti satellitari.
- `controller`: microservizio Controller associato logicamente a `SAT-1`.
- `dashboard`: base per la futura interfaccia di monitoraggio.
- `common`: configurazioni e utilità condivise tra i servizi.
- `config`: configurazione JSON della costellazione.
- `logs`: destinazione locale dei log generati dai container.

## Avvio

```bash
docker compose up --build
```

Endpoint iniziali:

- Simulator: `http://localhost:8000/health`
- Controller: `http://localhost:8001/health`
- Dashboard: `http://localhost:8080/health`
- Satelliti SAT-1 ... SAT-5: porte `8101` ... `8105`, percorso `/health`

Per arrestare lo stack:

```bash
docker compose down
```

