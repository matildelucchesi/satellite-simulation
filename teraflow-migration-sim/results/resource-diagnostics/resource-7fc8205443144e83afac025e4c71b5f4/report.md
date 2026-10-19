# Diagnosi CPU TeraFlow

ID: resource-7fc8205443144e83afac025e4c71b5f4
Migrazioni riuscite: False. Diagnosi completa: False.

Planner, risorse e calibrazioni non modificati. Percentili empirici floor(0.95*(N-1)).
Le coincidenze temporali non dimostrano causalità; i campioni non misurano la durata esatta dei picchi.

## hot — run-3c7bbc31438740e78086a5ec69463df4

### Totali per slot e finestra

| Slot | Finestra | Mediana | P95 | Massimo | Campioni >2,4 |
|---|---|---:|---:|---:|---:|
| sat-a | cleanup | 0.8844000000000001 | 0.8844000000000001 | 2.2745 | 0 |
| sat-a | dynamic_baseline | 1.072 | 3.2102000000000004 | 3.4141 | 9 |
| sat-a | dynamic_observation | 1.0347499999999998 | 2.864 | 3.2731 | 4 |
| sat-a | migration | 1.139 | 3.2824 | 4.2279 | 74 |
| sat-a | preparation | 1.286 | 3.4897 | 4.0731 | 14 |
| sat-a | settling | 1.13315 | 3.2064999999999997 | 3.7051000000000003 | 10 |
| sat-a | source_stable | 1.0595 | 3.2388 | 3.5177 | 27 |
| sat-a | target_stable | 1.0298999999999998 | 3.2805 | 4.147 | 25 |
| sat-b | cleanup | 2.4189 | 3.2666999999999997 | 3.2666999999999997 | 3 |
| sat-b | dynamic_baseline | 0.06725 | 2.2731 | 2.4114 | 3 |
| sat-b | dynamic_observation | 1.1855 | 2.8675 | 3.7281999999999997 | 4 |
| sat-b | migration | 0.3678 | 2.8011 | 6.553400000000001 | 38 |
| sat-b | preparation | 0.4623 | 2.4314 | 3.9828 | 8 |
| sat-b | settling | 0.06505 | 2.3867999999999996 | 3.001 | 6 |
| sat-b | source_stable | 0.0627 | 2.3930000000000002 | 2.7449 | 10 |
| sat-b | target_stable | 1.1300000000000001 | 3.1481 | 3.7117999999999998 | 26 |

Superamenti campionati in regime stabile: True. Completezza delle risorse: False.
Campioni mancanti o totali incompleti non sono consumi nulli.

### Componenti

| Slot | Finestra | Servizio | Mediana | P95 | Massimo | Campioni >2,4 |
|---|---|---|---:|---:|---:|---:|
| sat-b | preparation | sat-b-nbiservice | 0.02945 | 0.19269999999999998 | 0.26280000000000003 | 0 |
| sat-a | preparation | sat-a-nbiservice | 0.046 | 0.2148 | 0.3489 | 0 |
| sat-b | preparation | sat-b-serviceservice | 0.0023 | 0.2227 | 0.24530000000000002 | 0 |
| sat-a | preparation | sat-a-serviceservice | 0.0026 | 0.2248 | 0.2597 | 0 |
| sat-b | preparation | sat-b-deviceservice | 0.0219 | 0.6779999999999999 | 0.8189 | 0 |
| sat-a | preparation | sat-a-deviceservice | 0.6420999999999999 | 0.871 | 0.9745999999999999 | 0 |
| sat-b | preparation | sat-b-pathcompservice | 0.0213 | 0.1891 | 0.201 | 0 |
| sat-a | preparation | sat-a-pathcompservice | 0.0212 | 0.1973 | 0.21969999999999998 | 0 |
| sat-a | preparation | sat-a-contextservice | 0.0432 | 0.377 | 0.511 | 0 |
| sat-b | preparation | sat-b-contextservice | 0.0016 | 0.287 | 0.4454 | 0 |
| sat-b | preparation | sat-b-kafka | 0.0302 | 2.3852 | 2.4922 | 6 |
| sat-a | preparation | sat-a-kafka | 0.0323 | 2.3668 | 2.6563 | 4 |
| sat-a | preparation | sat-a-nats | 0.0005 | 0.031 | 0.0373 | 0 |
| sat-b | preparation | sat-b-pathcomp-backend | 0.0 | 0.0412 | 0.0431 | 0 |
| sat-b | preparation | sat-b-cockroachdb | 0.0264 | 0.732 | 1.1101999999999999 | 0 |
| sat-a | preparation | sat-a-pathcomp-backend | 0.0 | 0.0409 | 0.0452 | 0 |
| sat-a | preparation | sat-a-cockroachdb | 0.1249 | 0.7602 | 1.0072 | 0 |
| sat-b | preparation | sat-b-nats | 0.0005 | 0.029300000000000003 | 0.0391 | 0 |
| sat-a | settling | sat-a-nbiservice | 0.0278 | 0.1338 | 0.158 | 0 |
| sat-a | settling | sat-a-serviceservice | 0.0028000000000000004 | 0.2057 | 0.22640000000000002 | 0 |
| sat-a | settling | sat-a-deviceservice | 0.6758500000000001 | 0.8243 | 0.8728 | 0 |
| sat-a | settling | sat-a-pathcompservice | 0.0208 | 0.1978 | 0.217 | 0 |
| sat-a | settling | sat-a-contextservice | 0.0015500000000000002 | 0.2184 | 0.2463 | 0 |
| sat-b | settling | sat-b-kafka | 0.0137 | 1.9738999999999998 | 2.44 | 4 |
| sat-a | settling | sat-a-kafka | 0.030699999999999998 | 2.1271 | 2.4709 | 2 |
| sat-a | settling | sat-a-nats | 0.0004 | 0.031 | 0.043 | 0 |
| sat-b | settling | sat-b-cockroachdb | 0.02175 | 0.7172 | 0.7764 | 0 |
| sat-a | settling | sat-a-pathcomp-backend | 0.0 | 0.0431 | 0.056299999999999996 | 0 |
| sat-a | settling | sat-a-cockroachdb | 0.0211 | 0.7092 | 0.7911 | 0 |
| sat-b | settling | sat-b-nats | 0.0005 | 0.0334 | 0.0363 | 0 |
| sat-a | source_stable | sat-a-nbiservice | 0.02715 | 0.1333 | 0.16940000000000002 | 0 |
| sat-a | source_stable | sat-a-serviceservice | 0.0025 | 0.21969999999999998 | 0.2657 | 0 |
| sat-a | source_stable | sat-a-deviceservice | 0.6646000000000001 | 0.8336 | 0.9073 | 0 |
| sat-a | source_stable | sat-a-pathcompservice | 0.02085 | 0.19329999999999997 | 0.22699999999999998 | 0 |
| sat-a | source_stable | sat-a-contextservice | 0.0017000000000000001 | 0.2089 | 0.2413 | 0 |
| sat-b | source_stable | sat-b-kafka | 0.012199999999999999 | 2.1449000000000003 | 2.5221 | 4 |
| sat-a | source_stable | sat-a-kafka | 0.026600000000000002 | 2.2622999999999998 | 2.5237 | 6 |
| sat-a | source_stable | sat-a-nats | 0.0005 | 0.0291 | 0.0338 | 0 |
| sat-b | source_stable | sat-b-cockroachdb | 0.0216 | 0.7389 | 0.8565 | 0 |
| sat-a | source_stable | sat-a-pathcomp-backend | 0.0 | 0.037000000000000005 | 0.0499 | 0 |
| sat-a | source_stable | sat-a-cockroachdb | 0.0207 | 0.7178 | 0.8432999999999999 | 0 |
| sat-b | source_stable | sat-b-nats | 0.0005 | 0.029500000000000002 | 0.0365 | 0 |
| sat-a | dynamic_baseline | sat-a-nbiservice | 0.028900000000000002 | 0.1548 | 0.1666 | 0 |
| sat-a | dynamic_baseline | sat-a-serviceservice | 0.0025 | 0.22190000000000001 | 0.2332 | 0 |
| sat-a | dynamic_baseline | sat-a-deviceservice | 0.6879500000000001 | 0.8819 | 1.005 | 0 |
| sat-a | dynamic_baseline | sat-a-pathcompservice | 0.0218 | 0.23670000000000002 | 0.2591 | 0 |
| sat-a | dynamic_baseline | sat-a-contextservice | 0.0018 | 0.2155 | 0.2379 | 0 |
| sat-b | dynamic_baseline | sat-b-kafka | 0.013300000000000001 | 2.2497 | 2.3601 | 0 |
| sat-a | dynamic_baseline | sat-a-kafka | 0.0238 | 2.2646 | 2.386 | 0 |
| sat-a | dynamic_baseline | sat-a-nats | 0.0004 | 0.032 | 0.037000000000000005 | 0 |
| sat-b | dynamic_baseline | sat-b-cockroachdb | 0.023399999999999997 | 0.6546 | 1.2146 | 0 |
| sat-a | dynamic_baseline | sat-a-pathcomp-backend | 0.0 | 0.042 | 0.0434 | 0 |
| sat-a | dynamic_baseline | sat-a-cockroachdb | 0.0227 | 0.7101999999999999 | 0.8432999999999999 | 0 |
| sat-b | dynamic_baseline | sat-b-nats | 0.0004 | 0.0332 | 0.0352 | 0 |
| sat-a | migration | sat-a-nbiservice | 0.031 | 0.1618 | 0.2843 | 0 |
| sat-a | migration | sat-a-serviceservice | 0.0032 | 0.2361 | 0.3043 | 0 |
| sat-a | migration | sat-a-deviceservice | 0.6673 | 0.8739 | 1.0694 | 0 |
| sat-a | migration | sat-a-pathcompservice | 0.023 | 0.2148 | 0.4292 | 0 |
| sat-a | migration | sat-a-contextservice | 0.0018 | 0.2511 | 0.485 | 0 |
| sat-b | migration | sat-b-kafka | 0.017 | 2.1733000000000002 | 2.8994999999999997 | 12 |
| sat-a | migration | sat-a-kafka | 0.025099999999999997 | 2.1943 | 2.5063 | 11 |
| sat-a | migration | sat-a-nats | 0.0005 | 0.0338 | 0.0622 | 0 |
| sat-b | migration | sat-b-cockroachdb | 0.0341 | 0.7757 | 1.6313 | 0 |
| sat-a | migration | sat-a-pathcomp-backend | 0.0 | 0.0408 | 0.06709999999999999 | 0 |
| sat-a | migration | sat-a-cockroachdb | 0.025699999999999997 | 0.7412000000000001 | 1.949 | 0 |
| sat-b | migration | sat-b-nats | 0.0005 | 0.032400000000000005 | 0.0446 | 0 |
| sat-b | migration | sat-b-pathcomp-backend | 0.0 | 0.0381 | 0.042 | 0 |
| sat-b | migration | sat-b-contextservice | 0.08960000000000001 | 0.4208 | 0.564 | 0 |
| sat-b | migration | sat-b-pathcompservice | 0.021900000000000003 | 0.2034 | 0.22210000000000002 | 0 |
| sat-b | migration | sat-b-deviceservice | 0.54935 | 0.7966 | 0.8636 | 0 |
| sat-b | migration | sat-b-serviceservice | 0.004 | 0.2309 | 0.2502 | 0 |
| sat-b | migration | sat-b-nbiservice | 0.0636 | 0.2039 | 6.215800000000001 | 2 |
| sat-a | dynamic_observation | sat-a-nbiservice | 0.028300000000000002 | 0.1521 | 0.1743 | 0 |
| sat-a | dynamic_observation | sat-a-serviceservice | 0.003 | 0.22010000000000002 | 0.23370000000000002 | 0 |
| sat-a | dynamic_observation | sat-a-deviceservice | 0.59545 | 0.7665000000000001 | 0.7785 | 0 |
| sat-a | dynamic_observation | sat-a-pathcompservice | 0.0209 | 0.1865 | 0.19390000000000002 | 0 |
| sat-a | dynamic_observation | sat-a-contextservice | 0.0014000000000000002 | 0.2212 | 0.22940000000000002 | 0 |
| sat-b | dynamic_observation | sat-b-kafka | 0.029249999999999998 | 2.2558000000000002 | 2.4629 | 2 |
| sat-a | dynamic_observation | sat-a-kafka | 0.0223 | 2.2226 | 2.4062 | 2 |
| sat-a | dynamic_observation | sat-a-nats | 0.0006 | 0.031400000000000004 | 0.0363 | 0 |
| sat-b | dynamic_observation | sat-b-cockroachdb | 0.0227 | 0.6817 | 0.6998000000000001 | 0 |
| sat-a | dynamic_observation | sat-a-pathcomp-backend | 0.0 | 0.039900000000000005 | 0.041100000000000005 | 0 |
| sat-a | dynamic_observation | sat-a-cockroachdb | 0.0215 | 0.7021 | 0.8053 | 0 |
| sat-b | dynamic_observation | sat-b-nats | 0.0005 | 0.031400000000000004 | 0.0342 | 0 |
| sat-b | dynamic_observation | sat-b-pathcomp-backend | 0.0 | 0.0387 | 0.039 | 0 |
| sat-b | dynamic_observation | sat-b-contextservice | 0.0012 | 0.2237 | 0.2498 | 0 |
| sat-b | dynamic_observation | sat-b-pathcompservice | 0.0209 | 0.2047 | 0.2151 | 0 |
| sat-b | dynamic_observation | sat-b-deviceservice | 0.58655 | 0.7413 | 0.7609 | 0 |
| sat-b | dynamic_observation | sat-b-serviceservice | 0.0027 | 0.20550000000000002 | 0.212 | 0 |
| sat-b | dynamic_observation | sat-b-nbiservice | 0.031400000000000004 | 0.15 | 0.1718 | 0 |
| sat-a | target_stable | sat-a-nbiservice | 0.0287 | 0.1367 | 0.16670000000000001 | 0 |
| sat-a | target_stable | sat-a-serviceservice | 0.0031 | 0.2198 | 0.2557 | 0 |
| sat-a | target_stable | sat-a-deviceservice | 0.589 | 0.7663 | 0.8126000000000001 | 0 |
| sat-a | target_stable | sat-a-pathcompservice | 0.0202 | 0.20420000000000002 | 0.2268 | 0 |
| sat-a | target_stable | sat-a-contextservice | 0.0016 | 0.2126 | 0.2529 | 0 |
| sat-b | target_stable | sat-b-kafka | 0.0246 | 2.1538999999999997 | 2.8112 | 10 |
| sat-a | target_stable | sat-a-kafka | 0.021 | 2.2107 | 2.479 | 6 |
| sat-a | target_stable | sat-a-nats | 0.0005 | 0.0297 | 0.0346 | 0 |
| sat-b | target_stable | sat-b-cockroachdb | 0.0232 | 0.72 | 1.0726 | 0 |
| sat-a | target_stable | sat-a-pathcomp-backend | 0.0 | 0.0384 | 0.0446 | 0 |
| sat-a | target_stable | sat-a-cockroachdb | 0.0223 | 0.7404000000000001 | 0.9623999999999999 | 0 |
| sat-b | target_stable | sat-b-nats | 0.0005 | 0.0297 | 0.0355 | 0 |
| sat-b | target_stable | sat-b-pathcomp-backend | 0.0 | 0.0415 | 0.04650000000000001 | 0 |
| sat-b | target_stable | sat-b-contextservice | 0.001 | 0.2278 | 0.24480000000000002 | 0 |
| sat-b | target_stable | sat-b-pathcompservice | 0.021 | 0.20190000000000002 | 0.2351 | 0 |
| sat-b | target_stable | sat-b-deviceservice | 0.5821999999999999 | 0.7506999999999999 | 0.7844 | 0 |
| sat-b | target_stable | sat-b-serviceservice | 0.0027 | 0.2152 | 0.2412 | 0 |
| sat-b | target_stable | sat-b-nbiservice | 0.0302 | 0.1457 | 0.1566 | 0 |
| sat-a | cleanup | sat-a-nbiservice | 0.0278 | 0.1722 | 0.1722 | 0 |
| sat-a | cleanup | sat-a-serviceservice | 0.003 | 0.003 | 0.2229 | 0 |
| sat-a | cleanup | sat-a-deviceservice | 0.5611 | 0.6283 | 0.6283 | 0 |
| sat-a | cleanup | sat-a-pathcompservice | 0.0229 | 0.0233 | 0.0233 | 0 |
| sat-a | cleanup | sat-a-contextservice | 0.0013 | 0.0013 | 0.0013 | 0 |
| sat-b | cleanup | sat-b-kafka | 1.5278999999999998 | 1.9319 | 1.9319 | 0 |
| sat-a | cleanup | sat-a-kafka | 0.0227 | 0.0227 | 1.4147 | 0 |
| sat-a | cleanup | sat-a-nats | 0.0006 | 0.0317 | 0.0317 | 0 |
| sat-b | cleanup | sat-b-cockroachdb | 0.07490000000000001 | 0.2419 | 0.2419 | 0 |
| sat-a | cleanup | sat-a-pathcomp-backend | 0.0 | 0.0404 | 0.0404 | 0 |
| sat-a | cleanup | sat-a-cockroachdb | 0.0233 | 0.0892 | 0.0892 | 0 |
| sat-b | cleanup | sat-b-nats | 0.0006 | 0.031200000000000002 | 0.031200000000000002 | 0 |
| sat-b | cleanup | sat-b-pathcomp-backend | 0.0 | 0.0 | 0.0 | 0 |
| sat-b | cleanup | sat-b-contextservice | 0.0029 | 0.2591 | 0.2591 | 0 |
| sat-b | cleanup | sat-b-pathcompservice | 0.0227 | 0.0315 | 0.0315 | 0 |
| sat-b | cleanup | sat-b-deviceservice | 0.5755 | 0.6396999999999999 | 0.6396999999999999 | 0 |
| sat-b | cleanup | sat-b-serviceservice | 0.0034999999999999996 | 0.0034999999999999996 | 0.2395 | 0 |
| sat-b | cleanup | sat-b-nbiservice | 0.0336 | 0.2274 | 0.2274 | 0 |

Evidenze: C:\UNIFI-workspaces\satellite-simulation\teraflow-migration-sim\results\runs\run-3c7bbc31438740e78086a5ec69463df4

## cold — run-66bca6f6c0ae4f1a96b59f85531eeee3

### Totali per slot e finestra

| Slot | Finestra | Mediana | P95 | Massimo | Campioni >2,4 |
|---|---|---:|---:|---:|---:|
| sat-a | preparation | 0.7917000000000001 | 3.2472 | 3.6289000000000002 | 6 |
| sat-b | preparation | 0.6034 | 2.9249 | 4.787599999999999 | 6 |

Superamenti campionati in regime stabile: False. Completezza delle risorse: False.
Campioni mancanti o totali incompleti non sono consumi nulli.

### Componenti

| Slot | Finestra | Servizio | Mediana | P95 | Massimo | Campioni >2,4 |
|---|---|---|---:|---:|---:|---:|
| sat-b | preparation | sat-b-nbiservice | 0.035 | 0.1638 | 1.9313999999999998 | 0 |
| sat-a | preparation | sat-a-nbiservice | 0.0323 | 0.182 | 0.2487 | 0 |
| sat-b | preparation | sat-b-serviceservice | 0.0048 | 0.1675 | 0.2306 | 0 |
| sat-a | preparation | sat-a-serviceservice | 0.0044 | 0.2097 | 0.21239999999999998 | 0 |
| sat-b | preparation | sat-b-deviceservice | 0.06770000000000001 | 0.972 | 1.2241 | 0 |
| sat-a | preparation | sat-a-deviceservice | 0.6517000000000001 | 0.9562999999999999 | 1.2006000000000001 | 0 |
| sat-b | preparation | sat-b-pathcompservice | 0.0227 | 0.19260000000000002 | 0.2491 | 0 |
| sat-a | preparation | sat-a-pathcompservice | 0.0213 | 0.1875 | 0.19149999999999998 | 0 |
| sat-a | preparation | sat-a-contextservice | 0.0019 | 0.2673 | 0.33640000000000003 | 0 |
| sat-b | preparation | sat-b-contextservice | 0.0010500000000000002 | 0.2407 | 0.3332 | 0 |
| sat-b | preparation | sat-b-kafka | 0.0207 | 2.1481 | 2.1725 | 0 |
| sat-a | preparation | sat-a-kafka | 0.0181 | 1.8529 | 2.4662 | 4 |
| sat-a | preparation | sat-a-nats | 0.0005 | 0.028300000000000002 | 0.035 | 0 |
| sat-b | preparation | sat-b-pathcomp-backend | 0.0 | 0.0406 | 0.0775 | 0 |
| sat-b | preparation | sat-b-cockroachdb | 0.050499999999999996 | 0.6668000000000001 | 1.034 | 0 |
| sat-a | preparation | sat-a-pathcomp-backend | 0.0 | 0.0425 | 0.0665 | 0 |
| sat-a | preparation | sat-a-cockroachdb | 0.0335 | 0.6892 | 1.0458 | 0 |
| sat-b | preparation | sat-b-nats | 0.0005 | 0.0285 | 0.0323 | 0 |

Evidenze: C:\UNIFI-workspaces\satellite-simulation\teraflow-migration-sim\results\runs\run-66bca6f6c0ae4f1a96b59f85531eeee3
