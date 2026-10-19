# Diagnosi CPU TeraFlow

ID: resource-bff4c5e32a744285975ab7aa012217f8
Migrazioni riuscite: True. Diagnosi completa: False.

Planner, risorse e calibrazioni non modificati. Percentili empirici floor(0.95*(N-1)).
Le coincidenze temporali non dimostrano causalità; i campioni non misurano la durata esatta dei picchi.

## hot — run-882dd853b6144c91a0a388d9e97f5f6f

### Totali per slot e finestra

| Slot | Finestra | Mediana | P95 | Massimo | Campioni >2,4 |
|---|---|---:|---:|---:|---:|
| sat-a | cleanup | 2.1225 | 3.1601 | 3.1601 | 2 |
| sat-a | dynamic_baseline | 1.1191 | 2.993 | 4.0824 | 8 |
| sat-a | dynamic_observation | 1.10395 | 3.0819 | 3.5142 | 4 |
| sat-a | migration | 1.1897 | 3.3533999999999997 | 4.0962 | 66 |
| sat-a | preparation | 1.1133 | 3.2089 | 8.4574 | 29 |
| sat-a | settling | 1.24965 | 3.0837 | 4.1614 | 12 |
| sat-a | source_stable | 1.11945 | 3.2325 | 4.0824 | 30 |
| sat-a | target_stable | 1.0895 | 3.1974 | 3.6182 | 24 |
| sat-b | cleanup | 0.848 | 1.4263 | 1.4263 | 0 |
| sat-b | dynamic_baseline | 0.2774 | 2.5116 | 2.517 | 4 |
| sat-b | dynamic_observation | 1.2482 | 3.2201000000000004 | 3.3721 | 6 |
| sat-b | migration | 0.33335000000000004 | 2.4655 | 7.3018 | 30 |
| sat-b | preparation | 0.36310000000000003 | 2.5334000000000003 | 7.388300000000001 | 10 |
| sat-b | settling | 0.0612 | 2.0352 | 2.7281 | 6 |
| sat-b | source_stable | 0.0747 | 2.2674000000000003 | 3.0921 | 10 |
| sat-b | target_stable | 1.1523 | 3.3436000000000003 | 3.8523 | 22 |

Superamenti campionati in regime stabile: True. Completezza delle risorse: True.
Campioni mancanti o totali incompleti non sono consumi nulli.

### Componenti

| Slot | Finestra | Servizio | Mediana | P95 | Massimo | Campioni >2,4 |
|---|---|---|---:|---:|---:|---:|
| sat-b | preparation | sat-b-kafka | 0.019 | 2.1347 | 2.4981 | 6 |
| sat-a | preparation | sat-a-kafka | 0.021400000000000002 | 1.9694999999999998 | 2.448 | 4 |
| sat-a | preparation | sat-a-nats | 0.0005 | 0.029300000000000003 | 0.0519 | 0 |
| sat-b | preparation | sat-b-cockroachdb | 0.026600000000000002 | 0.6537000000000001 | 1.1423 | 0 |
| sat-a | preparation | sat-a-cockroachdb | 0.08900000000000001 | 0.9147 | 1.4450999999999998 | 0 |
| sat-b | preparation | sat-b-nats | 0.0005 | 0.029500000000000002 | 0.0524 | 0 |
| sat-a | preparation | sat-a-pathcomp-backend | 0.0 | 0.0385 | 0.0636 | 0 |
| sat-a | preparation | sat-a-contextservice | 0.0015 | 0.25379999999999997 | 0.5493 | 0 |
| sat-a | preparation | sat-a-pathcompservice | 0.022099999999999998 | 0.153 | 0.2232 | 0 |
| sat-a | preparation | sat-a-deviceservice | 0.6531999999999999 | 0.8429000000000001 | 0.9904000000000001 | 0 |
| sat-a | preparation | sat-a-serviceservice | 0.0015 | 0.20010000000000003 | 0.243 | 0 |
| sat-a | preparation | sat-a-nbiservice | 0.03435 | 0.2757 | 7.8203 | 3 |
| sat-b | preparation | sat-b-pathcomp-backend | 0.0 | 0.0374 | 0.0472 | 0 |
| sat-b | preparation | sat-b-contextservice | 0.0011 | 0.19 | 0.22210000000000002 | 0 |
| sat-b | preparation | sat-b-pathcompservice | 0.0203 | 0.2014 | 0.21239999999999998 | 0 |
| sat-b | preparation | sat-b-deviceservice | 0.0191 | 0.1909 | 0.2028 | 0 |
| sat-b | preparation | sat-b-serviceservice | 0.0011 | 0.1984 | 0.2245 | 0 |
| sat-b | preparation | sat-b-nbiservice | 0.0304 | 0.4648 | 6.766900000000001 | 2 |
| sat-b | settling | sat-b-kafka | 0.0108 | 1.9809 | 2.4919 | 2 |
| sat-a | settling | sat-a-kafka | 0.022000000000000002 | 2.0575 | 2.5850999999999997 | 2 |
| sat-a | settling | sat-a-nats | 0.0004 | 0.0311 | 0.0332 | 0 |
| sat-b | settling | sat-b-cockroachdb | 0.0223 | 0.7306 | 0.8323 | 0 |
| sat-a | settling | sat-a-cockroachdb | 0.023 | 0.7542 | 1.3839 | 0 |
| sat-b | settling | sat-b-nats | 0.0005 | 0.0288 | 0.0331 | 0 |
| sat-a | settling | sat-a-pathcomp-backend | 0.0 | 0.0407 | 0.042800000000000005 | 0 |
| sat-a | settling | sat-a-contextservice | 0.001 | 0.2045 | 0.24609999999999999 | 0 |
| sat-a | settling | sat-a-pathcompservice | 0.0213 | 0.1998 | 0.23989999999999997 | 0 |
| sat-a | settling | sat-a-deviceservice | 0.7044 | 0.9126000000000001 | 1.2492 | 0 |
| sat-a | settling | sat-a-serviceservice | 0.0022 | 0.1985 | 0.3356 | 0 |
| sat-a | settling | sat-a-nbiservice | 0.0286 | 0.1321 | 0.1819 | 0 |
| sat-b | source_stable | sat-b-kafka | 0.010700000000000001 | 2.2457 | 2.5618 | 8 |
| sat-a | source_stable | sat-a-kafka | 0.0213 | 2.2965 | 2.5497 | 12 |
| sat-a | source_stable | sat-a-nats | 0.00045 | 0.0317 | 0.0373 | 0 |
| sat-b | source_stable | sat-b-cockroachdb | 0.022649999999999997 | 0.7162000000000001 | 1.0107 | 0 |
| sat-a | source_stable | sat-a-cockroachdb | 0.023 | 0.701 | 0.8298000000000001 | 0 |
| sat-b | source_stable | sat-b-nats | 0.0005 | 0.0318 | 0.0338 | 0 |
| sat-a | source_stable | sat-a-pathcomp-backend | 0.0 | 0.042199999999999994 | 0.04769999999999999 | 0 |
| sat-a | source_stable | sat-a-contextservice | 0.001 | 0.214 | 0.2349 | 0 |
| sat-a | source_stable | sat-a-pathcompservice | 0.0223 | 0.2021 | 0.2379 | 0 |
| sat-a | source_stable | sat-a-deviceservice | 0.7101999999999999 | 0.8765000000000001 | 0.9689 | 0 |
| sat-a | source_stable | sat-a-serviceservice | 0.0026 | 0.2076 | 0.2325 | 0 |
| sat-a | source_stable | sat-a-nbiservice | 0.0294 | 0.14029999999999998 | 0.18030000000000002 | 0 |
| sat-b | dynamic_baseline | sat-b-kafka | 0.0104 | 2.4926 | 2.4966999999999997 | 4 |
| sat-a | dynamic_baseline | sat-a-kafka | 0.0217 | 1.6103999999999998 | 2.568 | 3 |
| sat-a | dynamic_baseline | sat-a-nats | 0.0004 | 0.0315 | 0.0341 | 0 |
| sat-b | dynamic_baseline | sat-b-cockroachdb | 0.025099999999999997 | 0.7382 | 1.1307 | 0 |
| sat-a | dynamic_baseline | sat-a-cockroachdb | 0.02545 | 0.6973999999999999 | 0.7572 | 0 |
| sat-b | dynamic_baseline | sat-b-nats | 0.0005 | 0.0304 | 0.032 | 0 |
| sat-a | dynamic_baseline | sat-a-pathcomp-backend | 0.0 | 0.042800000000000005 | 0.044199999999999996 | 0 |
| sat-a | dynamic_baseline | sat-a-contextservice | 0.00115 | 0.20989999999999998 | 0.3539 | 0 |
| sat-a | dynamic_baseline | sat-a-pathcompservice | 0.0216 | 0.21059999999999998 | 0.21230000000000002 | 0 |
| sat-a | dynamic_baseline | sat-a-deviceservice | 0.7126 | 0.9054000000000001 | 0.9067000000000001 | 0 |
| sat-a | dynamic_baseline | sat-a-serviceservice | 0.0023 | 0.2223 | 0.24420000000000003 | 0 |
| sat-a | dynamic_baseline | sat-a-nbiservice | 0.029199999999999997 | 0.1612 | 0.1616 | 0 |
| sat-b | migration | sat-b-kafka | 0.0121 | 2.1748 | 2.5824000000000003 | 12 |
| sat-a | migration | sat-a-kafka | 0.0219 | 2.1795 | 2.6118 | 14 |
| sat-a | migration | sat-a-nats | 0.0005 | 0.0333 | 0.058899999999999994 | 0 |
| sat-b | migration | sat-b-cockroachdb | 0.0391 | 0.8031999999999999 | 1.1962000000000002 | 0 |
| sat-a | migration | sat-a-cockroachdb | 0.027000000000000003 | 0.7931 | 1.1013 | 0 |
| sat-b | migration | sat-b-nats | 0.0005 | 0.0334 | 0.0581 | 0 |
| sat-a | migration | sat-a-pathcomp-backend | 0.0 | 0.0464 | 0.0803 | 0 |
| sat-a | migration | sat-a-contextservice | 0.0012 | 0.2548 | 0.4987 | 0 |
| sat-a | migration | sat-a-pathcompservice | 0.0248 | 0.2193 | 0.3911 | 0 |
| sat-a | migration | sat-a-deviceservice | 0.7126 | 0.8976999999999999 | 1.0395 | 0 |
| sat-a | migration | sat-a-serviceservice | 0.0032 | 0.2462 | 0.314 | 0 |
| sat-a | migration | sat-a-nbiservice | 0.0338 | 0.1673 | 0.32789999999999997 | 0 |
| sat-b | migration | sat-b-pathcomp-backend | 0.0 | 0.04 | 0.0495 | 0 |
| sat-b | migration | sat-b-contextservice | 0.0906 | 0.3883 | 0.5104 | 0 |
| sat-b | migration | sat-b-pathcompservice | 0.022000000000000002 | 0.2208 | 0.3691 | 0 |
| sat-b | migration | sat-b-deviceservice | 0.5781000000000001 | 0.8475 | 0.9915 | 0 |
| sat-b | migration | sat-b-serviceservice | 0.0078000000000000005 | 0.231 | 0.4472 | 0 |
| sat-b | migration | sat-b-nbiservice | 0.06295 | 0.2493 | 6.3667 | 2 |
| sat-b | dynamic_observation | sat-b-kafka | 0.0218 | 2.4818000000000002 | 2.6061 | 4 |
| sat-a | dynamic_observation | sat-a-kafka | 0.0219 | 1.7497 | 2.5649 | 2 |
| sat-a | dynamic_observation | sat-a-nats | 0.0005 | 0.0327 | 0.035699999999999996 | 0 |
| sat-b | dynamic_observation | sat-b-cockroachdb | 0.0232 | 0.6978 | 0.7219 | 0 |
| sat-a | dynamic_observation | sat-a-cockroachdb | 0.024850000000000004 | 0.6869 | 0.7336 | 0 |
| sat-b | dynamic_observation | sat-b-nats | 0.0005 | 0.030899999999999997 | 0.0383 | 0 |
| sat-a | dynamic_observation | sat-a-pathcomp-backend | 0.0 | 0.0406 | 0.0416 | 0 |
| sat-a | dynamic_observation | sat-a-contextservice | 0.0011 | 0.2161 | 0.2676 | 0 |
| sat-a | dynamic_observation | sat-a-pathcompservice | 0.023149999999999997 | 0.21050000000000002 | 0.2375 | 0 |
| sat-a | dynamic_observation | sat-a-deviceservice | 0.6571 | 0.8234999999999999 | 0.8452 | 0 |
| sat-a | dynamic_observation | sat-a-serviceservice | 0.0032 | 0.222 | 0.2237 | 0 |
| sat-a | dynamic_observation | sat-a-nbiservice | 0.0323 | 0.1456 | 0.1557 | 0 |
| sat-b | dynamic_observation | sat-b-pathcomp-backend | 0.0 | 0.0463 | 0.0524 | 0 |
| sat-b | dynamic_observation | sat-b-contextservice | 0.001 | 0.20620000000000002 | 0.2138 | 0 |
| sat-b | dynamic_observation | sat-b-pathcompservice | 0.022400000000000003 | 0.19879999999999998 | 0.2079 | 0 |
| sat-b | dynamic_observation | sat-b-deviceservice | 0.6441 | 0.8070999999999999 | 0.8193 | 0 |
| sat-b | dynamic_observation | sat-b-serviceservice | 0.0033 | 0.2266 | 0.24969999999999998 | 0 |
| sat-b | dynamic_observation | sat-b-nbiservice | 0.03275 | 0.1576 | 0.17149999999999999 | 0 |
| sat-b | target_stable | sat-b-kafka | 0.022099999999999998 | 1.986 | 2.603 | 8 |
| sat-a | target_stable | sat-a-kafka | 0.0215 | 2.278 | 2.5756 | 8 |
| sat-a | target_stable | sat-a-nats | 0.0005 | 0.0326 | 0.0443 | 0 |
| sat-b | target_stable | sat-b-cockroachdb | 0.0242 | 0.7733 | 0.8791 | 0 |
| sat-a | target_stable | sat-a-cockroachdb | 0.0235 | 0.7652 | 0.8885 | 0 |
| sat-b | target_stable | sat-b-nats | 0.0005 | 0.0325 | 0.0452 | 0 |
| sat-a | target_stable | sat-a-pathcomp-backend | 0.0 | 0.0444 | 0.0464 | 0 |
| sat-a | target_stable | sat-a-contextservice | 0.0012 | 0.23370000000000002 | 0.3209 | 0 |
| sat-a | target_stable | sat-a-pathcompservice | 0.0222 | 0.207 | 0.25079999999999997 | 0 |
| sat-a | target_stable | sat-a-deviceservice | 0.65 | 0.8219 | 0.8432 | 0 |
| sat-a | target_stable | sat-a-serviceservice | 0.003 | 0.2316 | 0.2858 | 0 |
| sat-a | target_stable | sat-a-nbiservice | 0.0313 | 0.1483 | 0.16570000000000001 | 0 |
| sat-b | target_stable | sat-b-pathcomp-backend | 0.0 | 0.0404 | 0.0559 | 0 |
| sat-b | target_stable | sat-b-contextservice | 0.0009 | 0.2279 | 0.24670000000000003 | 0 |
| sat-b | target_stable | sat-b-pathcompservice | 0.0217 | 0.20309999999999997 | 0.2438 | 0 |
| sat-b | target_stable | sat-b-deviceservice | 0.6376 | 0.8073999999999999 | 0.8201 | 0 |
| sat-b | target_stable | sat-b-serviceservice | 0.0033 | 0.2115 | 0.26030000000000003 | 0 |
| sat-b | target_stable | sat-b-nbiservice | 0.0313 | 0.1411 | 0.1672 | 0 |
| sat-b | cleanup | sat-b-kafka | 0.0268 | 0.0537 | 0.0537 | 0 |
| sat-a | cleanup | sat-a-kafka | 1.1476 | 2.1106 | 2.1106 | 0 |
| sat-a | cleanup | sat-a-nats | 0.0009 | 0.031400000000000004 | 0.031400000000000004 | 0 |
| sat-b | cleanup | sat-b-cockroachdb | 0.1206 | 0.2255 | 0.2255 | 0 |
| sat-a | cleanup | sat-a-cockroachdb | 0.0215 | 0.1149 | 0.1149 | 0 |
| sat-b | cleanup | sat-b-nats | 0.0004 | 0.032799999999999996 | 0.032799999999999996 | 0 |
| sat-a | cleanup | sat-a-pathcomp-backend | 0.0 | 0.045700000000000005 | 0.045700000000000005 | 0 |
| sat-a | cleanup | sat-a-contextservice | 0.0013 | 0.2429 | 0.2429 | 0 |
| sat-a | cleanup | sat-a-pathcompservice | 0.023 | 0.024 | 0.024 | 0 |
| sat-a | cleanup | sat-a-deviceservice | 0.6464 | 0.647 | 0.647 | 0 |
| sat-a | cleanup | sat-a-serviceservice | 0.0028000000000000004 | 0.23010000000000003 | 0.23010000000000003 | 0 |
| sat-a | cleanup | sat-a-nbiservice | 0.0335 | 0.0358 | 0.0358 | 0 |
| sat-b | cleanup | sat-b-pathcomp-backend | 0.0 | 0.0433 | 0.0433 | 0 |
| sat-b | cleanup | sat-b-contextservice | 0.0036 | 0.214 | 0.214 | 0 |
| sat-b | cleanup | sat-b-pathcompservice | 0.0223 | 0.024300000000000002 | 0.024300000000000002 | 0 |
| sat-b | cleanup | sat-b-deviceservice | 0.6333 | 0.6463 | 0.6463 | 0 |
| sat-b | cleanup | sat-b-serviceservice | 0.0036 | 0.0039000000000000003 | 0.20579999999999998 | 0 |
| sat-b | cleanup | sat-b-nbiservice | 0.0346 | 0.2687 | 0.2687 | 0 |

Evidenze: C:\UNIFI-workspaces\satellite-simulation\teraflow-migration-sim\results\runs\run-882dd853b6144c91a0a388d9e97f5f6f

## cold — run-f3cc5a57d0e54143b62de4e464ea3018

### Totali per slot e finestra

| Slot | Finestra | Mediana | P95 | Massimo | Campioni >2,4 |
|---|---|---:|---:|---:|---:|
| sat-a | cleanup | 0.13419999999999999 | 0.7842 | 0.7842 | 0 |
| sat-a | dynamic_baseline | 1.2653 | 2.6715 | 3.4547 | 4 |
| sat-a | dynamic_observation | 0.0697 | 0.886 | 2.5100000000000002 | 3 |
| sat-a | migration | 0.46840000000000004 | 2.4615 | 4.292599999999999 | 31 |
| sat-a | preparation | 1.351 | 3.4141000000000004 | 4.1019000000000005 | 14 |
| sat-a | settling | 1.1005 | 3.1277 | 4.237299999999999 | 10 |
| sat-a | source_stable | 1.1888 | 3.5013 | 4.5584 | 29 |
| sat-a | target_stable | 0.0662 | 2.5011 | 3.2201 | 15 |
| sat-b | cleanup | 2.248 | 3.1042 | 3.1042 | 2 |
| sat-b | dynamic_baseline | 0.0588 | 2.8529 | 2.9233 | 6 |
| sat-b | dynamic_observation | 1.2231 | 3.5223000000000004 | 4.0454 | 10 |
| sat-b | migration | 0.2882 | 2.4794 | 6.585299999999999 | 38 |
| sat-b | preparation | 0.7786000000000001 | 2.4705 | 4.3898 | 9 |
| sat-b | settling | 0.0617 | 2.3502 | 3.2427 | 6 |
| sat-b | source_stable | 0.0632 | 2.4167 | 2.961 | 14 |
| sat-b | target_stable | 1.0866 | 3.1466 | 4.0374 | 23 |

Superamenti campionati in regime stabile: True. Completezza delle risorse: False.
Campioni mancanti o totali incompleti non sono consumi nulli.

### Componenti

| Slot | Finestra | Servizio | Mediana | P95 | Massimo | Campioni >2,4 |
|---|---|---|---:|---:|---:|---:|
| sat-b | preparation | sat-b-nbiservice | 0.0297 | 0.1696 | 1.758 | 0 |
| sat-a | preparation | sat-a-nbiservice | 0.0452 | 0.1895 | 0.2372 | 0 |
| sat-b | preparation | sat-b-serviceservice | 0.0039000000000000003 | 0.2145 | 0.26170000000000004 | 0 |
| sat-a | preparation | sat-a-serviceservice | 0.0042 | 0.22039999999999998 | 0.2702 | 0 |
| sat-b | preparation | sat-b-deviceservice | 0.0229 | 0.7626999999999999 | 0.8901 | 0 |
| sat-a | preparation | sat-a-deviceservice | 0.6593000000000001 | 0.8384999999999999 | 0.9570000000000001 | 0 |
| sat-b | preparation | sat-b-pathcompservice | 0.0218 | 0.204 | 0.23870000000000002 | 0 |
| sat-a | preparation | sat-a-pathcompservice | 0.0218 | 0.2121 | 0.24710000000000001 | 0 |
| sat-a | preparation | sat-a-contextservice | 0.0521 | 0.3048 | 0.4412 | 0 |
| sat-b | preparation | sat-b-contextservice | 0.001 | 0.24960000000000002 | 0.5997 | 0 |
| sat-b | preparation | sat-b-kafka | 0.0212 | 1.8168 | 2.4697999999999998 | 4 |
| sat-a | preparation | sat-a-kafka | 0.021099999999999997 | 2.2739 | 2.6398 | 6 |
| sat-a | preparation | sat-a-nats | 0.0005 | 0.0317 | 0.0366 | 0 |
| sat-b | preparation | sat-b-pathcomp-backend | 0.0 | 0.0355 | 0.043899999999999995 | 0 |
| sat-b | preparation | sat-b-cockroachdb | 0.0775 | 0.8336 | 0.9940000000000001 | 0 |
| sat-a | preparation | sat-a-pathcomp-backend | 0.0 | 0.0421 | 0.049400000000000006 | 0 |
| sat-a | preparation | sat-a-cockroachdb | 0.19399999999999998 | 0.998 | 1.2584 | 0 |
| sat-b | preparation | sat-b-nats | 0.0005 | 0.0315 | 0.0365 | 0 |
| sat-a | settling | sat-a-nbiservice | 0.0291 | 0.1318 | 0.16469999999999999 | 0 |
| sat-a | settling | sat-a-serviceservice | 0.0038 | 0.214 | 0.24100000000000002 | 0 |
| sat-a | settling | sat-a-deviceservice | 0.7115 | 0.8966 | 0.9017000000000001 | 0 |
| sat-a | settling | sat-a-pathcompservice | 0.0219 | 0.2 | 0.2145 | 0 |
| sat-a | settling | sat-a-contextservice | 0.0011 | 0.2046 | 0.2519 | 0 |
| sat-b | settling | sat-b-kafka | 0.0104 | 2.2068 | 2.5683 | 6 |
| sat-a | settling | sat-a-kafka | 0.0202 | 2.0834 | 2.5101 | 2 |
| sat-a | settling | sat-a-nats | 0.0006 | 0.029500000000000002 | 0.031400000000000004 | 0 |
| sat-b | settling | sat-b-cockroachdb | 0.022099999999999998 | 0.7453 | 1.163 | 0 |
| sat-a | settling | sat-a-pathcomp-backend | 0.0 | 0.0403 | 0.0434 | 0 |
| sat-a | settling | sat-a-cockroachdb | 0.0219 | 0.7081000000000001 | 0.7767000000000001 | 0 |
| sat-b | settling | sat-b-nats | 0.0005 | 0.030699999999999998 | 0.0321 | 0 |
| sat-a | source_stable | sat-a-nbiservice | 0.0297 | 0.1437 | 0.1971 | 0 |
| sat-a | source_stable | sat-a-serviceservice | 0.0034999999999999996 | 0.2175 | 0.2733 | 0 |
| sat-a | source_stable | sat-a-deviceservice | 0.7170000000000001 | 0.9135 | 1.0014 | 0 |
| sat-a | source_stable | sat-a-pathcompservice | 0.0225 | 0.1975 | 0.2434 | 0 |
| sat-a | source_stable | sat-a-contextservice | 0.0012 | 0.2192 | 0.23670000000000002 | 0 |
| sat-b | source_stable | sat-b-kafka | 0.0102 | 2.2881 | 2.6145 | 10 |
| sat-a | source_stable | sat-a-kafka | 0.0213 | 2.1491 | 2.6245999999999996 | 11 |
| sat-a | source_stable | sat-a-nats | 0.0005 | 0.0334 | 0.0383 | 0 |
| sat-b | source_stable | sat-b-cockroachdb | 0.023700000000000002 | 0.7342 | 0.8170999999999999 | 0 |
| sat-a | source_stable | sat-a-pathcomp-backend | 0.0 | 0.0449 | 0.049400000000000006 | 0 |
| sat-a | source_stable | sat-a-cockroachdb | 0.0241 | 0.7683 | 1.4335 | 0 |
| sat-b | source_stable | sat-b-nats | 0.0005 | 0.0325 | 0.0403 | 0 |
| sat-a | dynamic_baseline | sat-a-serviceservice | 0.0033 | 0.2375 | 0.2626 | 0 |
| sat-a | dynamic_baseline | sat-a-deviceservice | 0.7161 | 0.8473999999999999 | 0.9239 | 0 |
| sat-a | dynamic_baseline | sat-a-pathcompservice | 0.0229 | 0.2032 | 0.2427 | 0 |
| sat-a | dynamic_baseline | sat-a-contextservice | 0.0011 | 0.21289999999999998 | 0.22899999999999998 | 0 |
| sat-b | dynamic_baseline | sat-b-kafka | 0.0098 | 2.2793 | 2.5421 | 2 |
| sat-a | dynamic_baseline | sat-a-kafka | 0.02045 | 1.8131 | 2.5472 | 3 |
| sat-a | dynamic_baseline | sat-a-nats | 0.0005 | 0.031 | 0.0315 | 0 |
| sat-b | dynamic_baseline | sat-b-cockroachdb | 0.0206 | 0.8222 | 0.8415 | 0 |
| sat-a | dynamic_baseline | sat-a-pathcomp-backend | 0.0 | 0.0412 | 0.0429 | 0 |
| sat-a | dynamic_baseline | sat-a-cockroachdb | 0.022350000000000002 | 0.7254 | 0.8693000000000001 | 0 |
| sat-b | dynamic_baseline | sat-b-nats | 0.0005 | 0.0351 | 0.0375 | 0 |
| sat-a | dynamic_baseline | sat-a-nbiservice | 0.0296 | 0.1434 | 0.1698 | 0 |
| sat-b | migration | sat-b-kafka | 0.0108 | 2.2471 | 2.6005000000000003 | 19 |
| sat-a | migration | sat-a-kafka | 0.012199999999999999 | 2.2666 | 2.5022 | 15 |
| sat-a | migration | sat-a-nats | 0.0005 | 0.033 | 0.048 | 0 |
| sat-b | migration | sat-b-cockroachdb | 0.031200000000000002 | 0.8103 | 1.3126 | 0 |
| sat-a | migration | sat-a-pathcomp-backend | 0.0 | 0.0421 | 0.0482 | 0 |
| sat-a | migration | sat-a-cockroachdb | 0.0242 | 0.7792 | 1.2434 | 0 |
| sat-b | migration | sat-b-nats | 0.0005 | 0.0323 | 0.042300000000000004 | 0 |
| sat-a | migration | sat-a-nbiservice | 0.03065 | 0.1449 | 2.6382999999999996 | 1 |
| sat-a | migration | sat-a-serviceservice | 0.0034999999999999996 | 0.2048 | 0.30579999999999996 | 0 |
| sat-a | migration | sat-a-deviceservice | 0.7204999999999999 | 0.8959999999999999 | 0.9212 | 0 |
| sat-a | migration | sat-a-pathcompservice | 0.0226 | 0.22 | 0.254 | 0 |
| sat-a | migration | sat-a-contextservice | 0.001 | 0.2108 | 0.3613 | 0 |
| sat-b | migration | sat-b-pathcomp-backend | 0.0 | 0.0435 | 0.048 | 0 |
| sat-b | migration | sat-b-contextservice | 0.12050000000000001 | 0.42840000000000006 | 0.49689999999999995 | 0 |
| sat-b | migration | sat-b-pathcompservice | 0.0226 | 0.19519999999999998 | 0.24100000000000002 | 0 |
| sat-b | migration | sat-b-deviceservice | 0.6556000000000001 | 0.9262 | 0.988 | 0 |
| sat-b | migration | sat-b-serviceservice | 0.0040999999999999995 | 0.24170000000000003 | 0.273 | 0 |
| sat-b | migration | sat-b-nbiservice | 0.07 | 0.3194 | 6.358 | 2 |
| sat-b | dynamic_observation | sat-b-kafka | 0.02215 | 2.4134 | 2.4753 | 4 |
| sat-a | dynamic_observation | sat-a-kafka | 0.0101 | 0.6089 | 2.4882 | 3 |
| sat-a | dynamic_observation | sat-a-nats | 0.00045 | 0.032799999999999996 | 0.0354 | 0 |
| sat-b | dynamic_observation | sat-b-cockroachdb | 0.0217 | 0.7714 | 0.8354 | 0 |
| sat-a | dynamic_observation | sat-a-cockroachdb | 0.023600000000000003 | 0.7843000000000001 | 0.8128 | 0 |
| sat-b | dynamic_observation | sat-b-nats | 0.0006 | 0.033 | 0.0341 | 0 |
| sat-b | dynamic_observation | sat-b-pathcomp-backend | 0.0 | 0.0398 | 0.042800000000000005 | 0 |
| sat-b | dynamic_observation | sat-b-contextservice | 0.0012499999999999998 | 0.2395 | 0.2403 | 0 |
| sat-b | dynamic_observation | sat-b-pathcompservice | 0.024399999999999998 | 0.2289 | 0.2685 | 0 |
| sat-b | dynamic_observation | sat-b-deviceservice | 0.7176 | 0.8934000000000001 | 0.9047 | 0 |
| sat-b | dynamic_observation | sat-b-serviceservice | 0.0034999999999999996 | 0.22719999999999999 | 0.2536 | 0 |
| sat-b | dynamic_observation | sat-b-nbiservice | 0.0319 | 0.1634 | 0.17149999999999999 | 0 |
| sat-b | target_stable | sat-b-kafka | 0.0206 | 2.1772 | 2.5413 | 8 |
| sat-a | target_stable | sat-a-kafka | 0.01 | 2.1583 | 2.5531 | 11 |
| sat-a | target_stable | sat-a-nats | 0.0004 | 0.0302 | 0.037000000000000005 | 0 |
| sat-b | target_stable | sat-b-cockroachdb | 0.024399999999999998 | 0.759 | 1.0567 | 0 |
| sat-a | target_stable | sat-a-cockroachdb | 0.0231 | 0.7464 | 1.1172 | 0 |
| sat-b | target_stable | sat-b-nats | 0.0005 | 0.029900000000000003 | 0.0377 | 0 |
| sat-b | target_stable | sat-b-pathcomp-backend | 0.0 | 0.039900000000000005 | 0.0516 | 0 |
| sat-b | target_stable | sat-b-contextservice | 0.0009 | 0.2248 | 0.2801 | 0 |
| sat-b | target_stable | sat-b-pathcompservice | 0.0215 | 0.2061 | 0.2561 | 0 |
| sat-b | target_stable | sat-b-deviceservice | 0.7026 | 0.8693000000000001 | 0.9128000000000001 | 0 |
| sat-b | target_stable | sat-b-serviceservice | 0.0026 | 0.222 | 0.2548 | 0 |
| sat-b | target_stable | sat-b-nbiservice | 0.030600000000000002 | 0.1456 | 0.1649 | 0 |
| sat-a | cleanup | sat-a-nats | 0.0003 | 0.0319 | 0.0319 | 0 |
| sat-b | cleanup | sat-b-cockroachdb | 1.2374 | 1.775 | 1.775 | 0 |
| sat-a | cleanup | sat-a-cockroachdb | 0.09369999999999999 | 0.7702 | 0.7702 | 0 |
| sat-b | cleanup | sat-b-nats | 0.0005 | 0.0353 | 0.0353 | 0 |
| sat-b | cleanup | sat-b-pathcomp-backend | 0.0 | 0.0 | 0.0516 | 0 |
| sat-b | cleanup | sat-b-contextservice | 0.1189 | 0.3282 | 0.3282 | 0 |
| sat-b | cleanup | sat-b-pathcompservice | 0.0282 | 0.1826 | 0.1826 | 0 |
| sat-b | cleanup | sat-b-deviceservice | 0.7347 | 0.9020999999999999 | 0.9020999999999999 | 0 |
| sat-b | cleanup | sat-b-serviceservice | 0.12279999999999999 | 0.13 | 0.13 | 0 |
| sat-b | cleanup | sat-b-nbiservice | 0.1148 | 0.12390000000000001 | 0.12390000000000001 | 0 |
| sat-b | cleanup | sat-b-kafka | 0.0298 | 0.0576 | 0.0576 | 0 |
| sat-a | cleanup | sat-a-kafka | 0.009899999999999999 | 0.0137 | 0.0137 | 0 |

Evidenze: C:\UNIFI-workspaces\satellite-simulation\teraflow-migration-sim\results\runs\run-f3cc5a57d0e54143b62de4e464ea3018
