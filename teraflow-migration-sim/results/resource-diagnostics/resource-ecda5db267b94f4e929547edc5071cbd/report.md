# Diagnosi CPU TeraFlow

ID: resource-ecda5db267b94f4e929547edc5071cbd
Migrazioni riuscite: True. Diagnosi completa: True.

Planner, risorse e calibrazioni non modificati. Percentili empirici floor(0.95*(N-1)).
Le coincidenze temporali non dimostrano causalità; i campioni non misurano la durata esatta dei picchi.

## hot — run-9fc28d4d941f44aab61201b7df605547

### Totali per slot e finestra

| Slot | Finestra | Mediana | P95 | Massimo | Campioni >2,4 |
|---|---|---:|---:|---:|---:|
| sat-a | cleanup | 0.8056 | 1.4677 | 1.4677 | 0 |
| sat-a | dynamic_baseline | 1.0996000000000001 | 3.0008999999999997 | 3.257 | 6 |
| sat-a | dynamic_observation | 0.9698 | 3.3463 | 3.6946000000000003 | 8 |
| sat-a | migration | 1.1803 | 3.4084000000000003 | 4.7654 | 70 |
| sat-a | preparation | 1.2249 | 3.4345000000000003 | 7.770099999999999 | 22 |
| sat-a | settling | 1.13465 | 2.8783 | 4.3349 | 16 |
| sat-a | source_stable | 1.1897 | 3.0508 | 4.4724 | 31 |
| sat-a | target_stable | 1.0409000000000002 | 3.1214 | 3.7148999999999996 | 24 |
| sat-b | cleanup | 2.0107 | 2.0107 | 2.63 | 1 |
| sat-b | dynamic_baseline | 0.2519 | 2.4463 | 2.4678 | 4 |
| sat-b | dynamic_observation | 1.0615999999999999 | 2.3171 | 3.4859999999999998 | 2 |
| sat-b | migration | 0.30979999999999996 | 2.5105999999999997 | 4.457800000000001 | 37 |
| sat-b | preparation | 0.832 | 2.7784 | 4.2281 | 16 |
| sat-b | settling | 0.062200000000000005 | 2.0843 | 3.1697 | 6 |
| sat-b | source_stable | 0.08015 | 2.463 | 3.7346 | 15 |
| sat-b | target_stable | 1.0267 | 3.0363999999999995 | 3.8705 | 29 |

Superamenti campionati in regime stabile: True. Completezza delle risorse: True.
Campioni mancanti o totali incompleti non sono consumi nulli.

### Componenti

| Slot | Finestra | Servizio | Mediana | P95 | Massimo | Campioni >2,4 |
|---|---|---|---:|---:|---:|---:|
| sat-b | preparation | sat-b-nbiservice | 0.03025 | 0.15839999999999999 | 2.3077 | 0 |
| sat-b | preparation | sat-b-serviceservice | 0.0033 | 0.15109999999999998 | 0.18780000000000002 | 0 |
| sat-b | preparation | sat-b-deviceservice | 0.17379999999999998 | 0.7578 | 0.8586 | 0 |
| sat-b | preparation | sat-b-pathcompservice | 0.0217 | 0.1764 | 0.20370000000000002 | 0 |
| sat-b | preparation | sat-b-contextservice | 0.0011 | 0.2325 | 0.522 | 0 |
| sat-b | preparation | sat-b-kafka | 0.02 | 2.2875 | 2.5987999999999998 | 7 |
| sat-a | preparation | sat-a-kafka | 0.0189 | 2.2566 | 2.5385 | 9 |
| sat-a | preparation | sat-a-nats | 0.0005 | 0.0304 | 0.0334 | 0 |
| sat-b | preparation | sat-b-pathcomp-backend | 0.0 | 0.037599999999999995 | 0.0546 | 0 |
| sat-b | preparation | sat-b-cockroachdb | 0.027000000000000003 | 0.7206 | 0.9621 | 0 |
| sat-a | preparation | sat-a-cockroachdb | 0.0843 | 0.7653 | 0.9336 | 0 |
| sat-b | preparation | sat-b-nats | 0.0005 | 0.029900000000000003 | 0.032 | 0 |
| sat-a | preparation | sat-a-pathcomp-backend | 0.0 | 0.0381 | 0.044800000000000006 | 0 |
| sat-a | preparation | sat-a-contextservice | 0.042800000000000005 | 0.3759 | 0.5728 | 0 |
| sat-a | preparation | sat-a-pathcompservice | 0.0222 | 0.17190000000000003 | 0.25920000000000004 | 0 |
| sat-a | preparation | sat-a-deviceservice | 0.63415 | 0.8922 | 0.9399 | 0 |
| sat-a | preparation | sat-a-serviceservice | 0.0032500000000000003 | 0.1837 | 0.2341 | 0 |
| sat-a | preparation | sat-a-nbiservice | 0.048799999999999996 | 0.2789 | 6.935 | 3 |
| sat-b | settling | sat-b-kafka | 0.0095 | 2.0303 | 2.4485 | 4 |
| sat-a | settling | sat-a-kafka | 0.0192 | 2.0804 | 2.55 | 4 |
| sat-a | settling | sat-a-nats | 0.0004 | 0.0305 | 0.0313 | 0 |
| sat-b | settling | sat-b-cockroachdb | 0.02355 | 0.6757 | 0.8223 | 0 |
| sat-a | settling | sat-a-cockroachdb | 0.0225 | 0.6867 | 0.8806999999999999 | 0 |
| sat-b | settling | sat-b-nats | 0.0005 | 0.031400000000000004 | 0.046799999999999994 | 0 |
| sat-a | settling | sat-a-pathcomp-backend | 0.0 | 0.0397 | 0.0443 | 0 |
| sat-a | settling | sat-a-contextservice | 0.0012 | 0.2061 | 0.26890000000000003 | 0 |
| sat-a | settling | sat-a-pathcompservice | 0.021 | 0.2022 | 0.2275 | 0 |
| sat-a | settling | sat-a-deviceservice | 0.6807 | 0.8643000000000001 | 0.8724 | 0 |
| sat-a | settling | sat-a-serviceservice | 0.0025 | 0.2107 | 0.2455 | 0 |
| sat-a | settling | sat-a-nbiservice | 0.0282 | 0.1353 | 0.1565 | 0 |
| sat-b | source_stable | sat-b-kafka | 0.009899999999999999 | 1.9927000000000001 | 2.8779000000000003 | 9 |
| sat-a | source_stable | sat-a-kafka | 0.0194 | 2.0676 | 2.516 | 8 |
| sat-a | source_stable | sat-a-nats | 0.0005 | 0.031 | 0.0666 | 0 |
| sat-b | source_stable | sat-b-cockroachdb | 0.0232 | 0.7290000000000001 | 1.7537 | 0 |
| sat-a | source_stable | sat-a-cockroachdb | 0.02305 | 0.7587999999999999 | 1.5238999999999998 | 0 |
| sat-b | source_stable | sat-b-nats | 0.00045 | 0.0298 | 0.069 | 0 |
| sat-a | source_stable | sat-a-pathcomp-backend | 0.0 | 0.0406 | 0.056600000000000004 | 0 |
| sat-a | source_stable | sat-a-contextservice | 0.0012 | 0.2408 | 0.42829999999999996 | 0 |
| sat-a | source_stable | sat-a-pathcompservice | 0.0218 | 0.2113 | 0.4886 | 0 |
| sat-a | source_stable | sat-a-deviceservice | 0.6837000000000001 | 0.9869 | 1.9079 | 0 |
| sat-a | source_stable | sat-a-serviceservice | 0.0023 | 0.2351 | 0.38689999999999997 | 0 |
| sat-a | source_stable | sat-a-nbiservice | 0.0288 | 0.1396 | 0.3754 | 0 |
| sat-b | dynamic_baseline | sat-b-kafka | 0.01015 | 2.4282 | 2.4476 | 4 |
| sat-a | dynamic_baseline | sat-a-kafka | 0.0177 | 2.199 | 2.4833000000000003 | 2 |
| sat-a | dynamic_baseline | sat-a-nats | 0.0005 | 0.0302 | 0.030299999999999997 | 0 |
| sat-b | dynamic_baseline | sat-b-cockroachdb | 0.022000000000000002 | 0.6796 | 0.7494 | 0 |
| sat-a | dynamic_baseline | sat-a-cockroachdb | 0.0222 | 0.7168000000000001 | 0.8194 | 0 |
| sat-b | dynamic_baseline | sat-b-nats | 0.0004 | 0.0294 | 0.032 | 0 |
| sat-a | dynamic_baseline | sat-a-pathcomp-backend | 0.0 | 0.0387 | 0.039900000000000005 | 0 |
| sat-a | dynamic_baseline | sat-a-contextservice | 0.0013 | 0.21539999999999998 | 0.3091 | 0 |
| sat-a | dynamic_baseline | sat-a-pathcompservice | 0.02145 | 0.2143 | 0.2184 | 0 |
| sat-a | dynamic_baseline | sat-a-deviceservice | 0.6823 | 0.9339 | 0.9758 | 0 |
| sat-a | dynamic_baseline | sat-a-serviceservice | 0.0022500000000000003 | 0.2094 | 0.20989999999999998 | 0 |
| sat-a | dynamic_baseline | sat-a-nbiservice | 0.03 | 0.1535 | 0.1558 | 0 |
| sat-b | migration | sat-b-kafka | 0.011399999999999999 | 2.2363999999999997 | 2.611 | 16 |
| sat-a | migration | sat-a-kafka | 0.0206 | 2.2547 | 2.5775 | 15 |
| sat-a | migration | sat-a-nats | 0.0005 | 0.0327 | 0.0542 | 0 |
| sat-b | migration | sat-b-cockroachdb | 0.0371 | 0.818 | 1.5834000000000001 | 0 |
| sat-a | migration | sat-a-cockroachdb | 0.0274 | 0.8225 | 1.4693 | 0 |
| sat-b | migration | sat-b-nats | 0.0005 | 0.0344 | 0.056600000000000004 | 0 |
| sat-a | migration | sat-a-pathcomp-backend | 0.0 | 0.043 | 0.0745 | 0 |
| sat-a | migration | sat-a-contextservice | 0.0013 | 0.2539 | 0.48950000000000005 | 0 |
| sat-a | migration | sat-a-pathcompservice | 0.0242 | 0.21739999999999998 | 0.34090000000000004 | 0 |
| sat-a | migration | sat-a-deviceservice | 0.6901999999999999 | 0.8831 | 1.5086000000000002 | 0 |
| sat-a | migration | sat-a-serviceservice | 0.0029 | 0.2409 | 0.2696 | 0 |
| sat-a | migration | sat-a-nbiservice | 0.0339 | 0.17620000000000002 | 0.33899999999999997 | 0 |
| sat-b | migration | sat-b-pathcomp-backend | 0.0 | 0.0408 | 0.051100000000000007 | 0 |
| sat-b | migration | sat-b-contextservice | 0.11055000000000001 | 0.5421 | 0.6997 | 0 |
| sat-b | migration | sat-b-pathcompservice | 0.024900000000000002 | 0.2107 | 0.2952 | 0 |
| sat-b | migration | sat-b-deviceservice | 0.5279 | 0.8724 | 0.9014 | 0 |
| sat-b | migration | sat-b-serviceservice | 0.009399999999999999 | 0.2469 | 0.679 | 0 |
| sat-b | migration | sat-b-nbiservice | 0.0633 | 0.2693 | 4.0252 | 2 |
| sat-b | dynamic_observation | sat-b-kafka | 0.020499999999999997 | 1.6950999999999998 | 2.3697999999999997 | 0 |
| sat-a | dynamic_observation | sat-a-kafka | 0.01985 | 2.325 | 2.4499 | 2 |
| sat-a | dynamic_observation | sat-a-nats | 0.0005 | 0.0294 | 0.0356 | 0 |
| sat-b | dynamic_observation | sat-b-cockroachdb | 0.0273 | 0.7503 | 0.7841 | 0 |
| sat-a | dynamic_observation | sat-a-cockroachdb | 0.0234 | 0.7484000000000001 | 0.7519 | 0 |
| sat-b | dynamic_observation | sat-b-nats | 0.0006 | 0.030699999999999998 | 0.0332 | 0 |
| sat-a | dynamic_observation | sat-a-pathcomp-backend | 0.0 | 0.045 | 0.0526 | 0 |
| sat-a | dynamic_observation | sat-a-contextservice | 0.0013 | 0.23170000000000002 | 0.2583 | 0 |
| sat-a | dynamic_observation | sat-a-pathcompservice | 0.0225 | 0.1977 | 0.2021 | 0 |
| sat-a | dynamic_observation | sat-a-deviceservice | 0.6098 | 0.7683 | 0.775 | 0 |
| sat-a | dynamic_observation | sat-a-serviceservice | 0.0026 | 0.21559999999999999 | 0.25370000000000004 | 0 |
| sat-a | dynamic_observation | sat-a-nbiservice | 0.0327 | 0.1484 | 0.1572 | 0 |
| sat-b | dynamic_observation | sat-b-pathcomp-backend | 0.0 | 0.039599999999999996 | 0.0564 | 0 |
| sat-b | dynamic_observation | sat-b-contextservice | 0.0013 | 0.23199999999999998 | 0.2636 | 0 |
| sat-b | dynamic_observation | sat-b-pathcompservice | 0.024300000000000002 | 0.17850000000000002 | 0.23739999999999997 | 0 |
| sat-b | dynamic_observation | sat-b-deviceservice | 0.6175 | 0.7371 | 0.8389 | 0 |
| sat-b | dynamic_observation | sat-b-serviceservice | 0.0032 | 0.2147 | 0.24050000000000002 | 0 |
| sat-b | dynamic_observation | sat-b-nbiservice | 0.0329 | 0.152 | 0.157 | 0 |
| sat-b | target_stable | sat-b-kafka | 0.020099999999999996 | 2.0206 | 2.5389 | 6 |
| sat-a | target_stable | sat-a-kafka | 0.01985 | 2.1049 | 2.6113999999999997 | 11 |
| sat-a | target_stable | sat-a-nats | 0.0005 | 0.031400000000000004 | 0.0374 | 0 |
| sat-b | target_stable | sat-b-cockroachdb | 0.02435 | 0.7594 | 0.8039000000000001 | 0 |
| sat-a | target_stable | sat-a-cockroachdb | 0.0239 | 0.7583 | 0.7993000000000001 | 0 |
| sat-b | target_stable | sat-b-nats | 0.0005 | 0.030699999999999998 | 0.0368 | 0 |
| sat-a | target_stable | sat-a-pathcomp-backend | 0.0 | 0.0407 | 0.050499999999999996 | 0 |
| sat-a | target_stable | sat-a-contextservice | 0.0012 | 0.2121 | 0.2415 | 0 |
| sat-a | target_stable | sat-a-pathcompservice | 0.0218 | 0.1954 | 0.2206 | 0 |
| sat-a | target_stable | sat-a-deviceservice | 0.6101 | 0.7648 | 0.8051999999999999 | 0 |
| sat-a | target_stable | sat-a-serviceservice | 0.0027 | 0.2211 | 0.2766 | 0 |
| sat-a | target_stable | sat-a-nbiservice | 0.030299999999999997 | 0.1369 | 0.1593 | 0 |
| sat-b | target_stable | sat-b-pathcomp-backend | 0.0 | 0.0397 | 0.046799999999999994 | 0 |
| sat-b | target_stable | sat-b-contextservice | 0.0012 | 0.2145 | 0.2827 | 0 |
| sat-b | target_stable | sat-b-pathcompservice | 0.023 | 0.19699999999999998 | 0.2311 | 0 |
| sat-b | target_stable | sat-b-deviceservice | 0.6222 | 0.7870999999999999 | 0.8158 | 0 |
| sat-b | target_stable | sat-b-serviceservice | 0.00295 | 0.2339 | 0.263 | 0 |
| sat-b | target_stable | sat-b-nbiservice | 0.0315 | 0.1531 | 0.1773 | 0 |
| sat-b | cleanup | sat-b-kafka | 0.051100000000000007 | 0.051100000000000007 | 1.4022999999999999 | 0 |
| sat-a | cleanup | sat-a-kafka | 0.019299999999999998 | 0.0239 | 0.0239 | 0 |
| sat-a | cleanup | sat-a-nats | 0.0006 | 0.0277 | 0.0277 | 0 |
| sat-b | cleanup | sat-b-cockroachdb | 0.2434 | 1.2311 | 1.2311 | 0 |
| sat-a | cleanup | sat-a-cockroachdb | 0.0601 | 0.7508 | 0.7508 | 0 |
| sat-b | cleanup | sat-b-nats | 0.0006 | 0.0281 | 0.0281 | 0 |
| sat-a | cleanup | sat-a-pathcomp-backend | 0.0 | 0.037599999999999995 | 0.037599999999999995 | 0 |
| sat-a | cleanup | sat-a-contextservice | 0.0018 | 0.0501 | 0.0501 | 0 |
| sat-a | cleanup | sat-a-pathcompservice | 0.022099999999999998 | 0.0235 | 0.0235 | 0 |
| sat-a | cleanup | sat-a-deviceservice | 0.5851 | 0.6441 | 0.6441 | 0 |
| sat-a | cleanup | sat-a-serviceservice | 0.0024 | 0.0025 | 0.0025 | 0 |
| sat-a | cleanup | sat-a-nbiservice | 0.0301 | 0.0315 | 0.0315 | 0 |
| sat-b | cleanup | sat-b-pathcomp-backend | 0.0 | 0.052199999999999996 | 0.052199999999999996 | 0 |
| sat-b | cleanup | sat-b-contextservice | 0.1681 | 0.1681 | 0.2827 | 0 |
| sat-b | cleanup | sat-b-pathcompservice | 0.0227 | 0.027999999999999997 | 0.027999999999999997 | 0 |
| sat-b | cleanup | sat-b-deviceservice | 0.5999 | 0.6346 | 0.6346 | 0 |
| sat-b | cleanup | sat-b-serviceservice | 0.0044 | 0.2027 | 0.2027 | 0 |
| sat-b | cleanup | sat-b-nbiservice | 0.0868 | 0.1525 | 0.1525 | 0 |

Evidenze: C:\UNIFI-workspaces\satellite-simulation\teraflow-migration-sim\results\runs\run-9fc28d4d941f44aab61201b7df605547

## cold — run-fc0d676806b64b389ccde469d31cd8eb

### Totali per slot e finestra

| Slot | Finestra | Mediana | P95 | Massimo | Campioni >2,4 |
|---|---|---:|---:|---:|---:|
| sat-a | cleanup | 0.0412 | 0.1024 | 0.1024 | 0 |
| sat-a | dynamic_baseline | 1.1549 | 3.2594 | 4.0481 | 6 |
| sat-a | dynamic_observation | 0.06470000000000001 | 2.7133 | 2.7727999999999997 | 6 |
| sat-a | migration | 0.42479999999999996 | 2.3878 | 4.6576 | 25 |
| sat-a | preparation | 1.3933 | 2.6987 | 4.4205000000000005 | 13 |
| sat-a | settling | 0.96895 | 3.3381999999999996 | 3.7754 | 15 |
| sat-a | source_stable | 1.1967 | 3.1313 | 4.0911 | 32 |
| sat-a | target_stable | 0.0635 | 2.3582 | 2.8754 | 11 |
| sat-b | cleanup | 1.6237 | 1.6237 | 2.1939 | 0 |
| sat-b | dynamic_baseline | 0.2532 | 2.5599 | 2.6022 | 5 |
| sat-b | dynamic_observation | 0.9753999999999999 | 3.5409 | 3.7753 | 6 |
| sat-b | migration | 0.25 | 2.5795 | 7.8313 | 40 |
| sat-b | preparation | 0.6346999999999999 | 3.3522000000000003 | 3.7683 | 13 |
| sat-b | settling | 0.057999999999999996 | 1.7883 | 3.0822000000000003 | 4 |
| sat-b | source_stable | 0.0575 | 2.173 | 3.1708 | 10 |
| sat-b | target_reconciliation | None | None | None | 0 |
| sat-b | target_stable | 1.0816999999999999 | 3.2458 | 4.1442000000000005 | 22 |

Superamenti campionati in regime stabile: True. Completezza delle risorse: True.
Campioni mancanti o totali incompleti non sono consumi nulli.

### Componenti

| Slot | Finestra | Servizio | Mediana | P95 | Massimo | Campioni >2,4 |
|---|---|---|---:|---:|---:|---:|
| sat-b | preparation | sat-b-nbiservice | 0.029300000000000003 | 0.19829999999999998 | 2.5196 | 1 |
| sat-a | preparation | sat-a-nbiservice | 0.043899999999999995 | 0.1985 | 0.3246 | 0 |
| sat-b | preparation | sat-b-serviceservice | 0.0033 | 0.1881 | 0.22760000000000002 | 0 |
| sat-a | preparation | sat-a-serviceservice | 0.0036 | 0.2183 | 0.23850000000000002 | 0 |
| sat-b | preparation | sat-b-deviceservice | 0.024 | 0.7469 | 0.8719 | 0 |
| sat-a | preparation | sat-a-deviceservice | 0.665 | 0.8783 | 0.9627 | 0 |
| sat-b | preparation | sat-b-pathcompservice | 0.0217 | 0.19690000000000002 | 0.215 | 0 |
| sat-a | preparation | sat-a-pathcompservice | 0.0212 | 0.1827 | 0.1957 | 0 |
| sat-a | preparation | sat-a-contextservice | 0.053399999999999996 | 0.3762 | 0.4673 | 0 |
| sat-b | preparation | sat-b-contextservice | 0.001 | 0.2253 | 0.5867 | 0 |
| sat-b | preparation | sat-b-kafka | 0.0189 | 2.3556 | 2.47 | 2 |
| sat-a | preparation | sat-a-kafka | 0.0187 | 1.7521 | 2.4930000000000003 | 2 |
| sat-a | preparation | sat-a-nats | 0.0005 | 0.0305 | 0.0326 | 0 |
| sat-b | preparation | sat-b-pathcomp-backend | 0.0 | 0.036000000000000004 | 0.039599999999999996 | 0 |
| sat-b | preparation | sat-b-cockroachdb | 0.0259 | 0.6987000000000001 | 1.0704 | 0 |
| sat-a | preparation | sat-a-pathcomp-backend | 0.0 | 0.0392 | 0.0421 | 0 |
| sat-a | preparation | sat-a-cockroachdb | 0.122 | 0.8051 | 1.1442 | 0 |
| sat-b | preparation | sat-b-nats | 0.0005 | 0.03 | 0.0365 | 0 |
| sat-a | settling | sat-a-nbiservice | 0.0288 | 0.13019999999999998 | 0.16149999999999998 | 0 |
| sat-a | settling | sat-a-serviceservice | 0.0033 | 0.217 | 0.23739999999999997 | 0 |
| sat-a | settling | sat-a-deviceservice | 0.6896500000000001 | 0.8376 | 0.8748999999999999 | 0 |
| sat-a | settling | sat-a-pathcompservice | 0.021099999999999997 | 0.2036 | 0.22699999999999998 | 0 |
| sat-a | settling | sat-a-contextservice | 0.0012 | 0.2133 | 0.2503 | 0 |
| sat-b | settling | sat-b-kafka | 0.009000000000000001 | 1.7516 | 2.4702 | 4 |
| sat-a | settling | sat-a-kafka | 0.019 | 2.4437 | 2.5484999999999998 | 7 |
| sat-a | settling | sat-a-nats | 0.0005 | 0.0297 | 0.0335 | 0 |
| sat-b | settling | sat-b-cockroachdb | 0.0239 | 0.7398 | 0.7801 | 0 |
| sat-a | settling | sat-a-pathcomp-backend | 0.0 | 0.042800000000000005 | 0.0521 | 0 |
| sat-a | settling | sat-a-cockroachdb | 0.0226 | 0.7454000000000001 | 1.2145000000000001 | 0 |
| sat-b | settling | sat-b-nats | 0.0005 | 0.03 | 0.0365 | 0 |
| sat-a | source_stable | sat-a-nbiservice | 0.0287 | 0.1323 | 0.1739 | 0 |
| sat-a | source_stable | sat-a-serviceservice | 0.0032 | 0.2145 | 0.2475 | 0 |
| sat-a | source_stable | sat-a-deviceservice | 0.68875 | 0.865 | 0.9081 | 0 |
| sat-a | source_stable | sat-a-pathcompservice | 0.0215 | 0.1968 | 0.2237 | 0 |
| sat-a | source_stable | sat-a-contextservice | 0.0013 | 0.2144 | 0.2593 | 0 |
| sat-b | source_stable | sat-b-kafka | 0.00985 | 1.8577000000000001 | 2.5913999999999997 | 10 |
| sat-a | source_stable | sat-a-kafka | 0.019 | 1.8903999999999999 | 2.5682 | 10 |
| sat-a | source_stable | sat-a-nats | 0.0005 | 0.030699999999999998 | 0.037599999999999995 | 0 |
| sat-b | source_stable | sat-b-cockroachdb | 0.0217 | 0.7190000000000001 | 0.8031 | 0 |
| sat-a | source_stable | sat-a-pathcomp-backend | 0.0 | 0.0385 | 0.0455 | 0 |
| sat-a | source_stable | sat-a-cockroachdb | 0.02355 | 0.7612000000000001 | 1.4735 | 0 |
| sat-b | source_stable | sat-b-nats | 0.0005 | 0.0304 | 0.0362 | 0 |
| sat-a | dynamic_baseline | sat-a-nbiservice | 0.02895 | 0.157 | 0.17120000000000002 | 0 |
| sat-a | dynamic_baseline | sat-a-serviceservice | 0.00335 | 0.2236 | 0.2437 | 0 |
| sat-a | dynamic_baseline | sat-a-deviceservice | 0.6992 | 0.8737 | 0.9023 | 0 |
| sat-a | dynamic_baseline | sat-a-pathcompservice | 0.022000000000000002 | 0.2082 | 0.2263 | 0 |
| sat-a | dynamic_baseline | sat-a-contextservice | 0.0014000000000000002 | 0.22210000000000002 | 0.3146 | 0 |
| sat-b | dynamic_baseline | sat-b-kafka | 0.009399999999999999 | 2.4066 | 2.5364 | 5 |
| sat-a | dynamic_baseline | sat-a-kafka | 0.018750000000000003 | 1.8903999999999999 | 2.5097 | 3 |
| sat-a | dynamic_baseline | sat-a-nats | 0.0005 | 0.0296 | 0.0302 | 0 |
| sat-b | dynamic_baseline | sat-b-cockroachdb | 0.0227 | 0.7798999999999999 | 1.5050999999999999 | 0 |
| sat-a | dynamic_baseline | sat-a-pathcomp-backend | 0.0 | 0.0401 | 0.045599999999999995 | 0 |
| sat-a | dynamic_baseline | sat-a-cockroachdb | 0.022650000000000003 | 0.7053 | 0.7948999999999999 | 0 |
| sat-b | dynamic_baseline | sat-b-nats | 0.0005 | 0.0315 | 0.034300000000000004 | 0 |
| sat-a | migration | sat-a-nbiservice | 0.03 | 0.1317 | 2.406 | 1 |
| sat-a | migration | sat-a-serviceservice | 0.0033 | 0.21539999999999998 | 0.25079999999999997 | 0 |
| sat-a | migration | sat-a-deviceservice | 0.6898000000000001 | 0.8487 | 0.9315000000000001 | 0 |
| sat-a | migration | sat-a-pathcompservice | 0.02155 | 0.1889 | 0.2347 | 0 |
| sat-a | migration | sat-a-contextservice | 0.0013 | 0.1993 | 0.2642 | 0 |
| sat-b | migration | sat-b-kafka | 0.0096 | 2.0751 | 2.6656999999999997 | 12 |
| sat-a | migration | sat-a-kafka | 0.0101 | 2.2577000000000003 | 2.5482 | 14 |
| sat-a | migration | sat-a-nats | 0.0005 | 0.0321 | 0.0452 | 0 |
| sat-b | migration | sat-b-cockroachdb | 0.027200000000000002 | 0.7781 | 1.4672 | 0 |
| sat-a | migration | sat-a-pathcomp-backend | 0.0 | 0.0444 | 0.0513 | 0 |
| sat-a | migration | sat-a-cockroachdb | 0.0219 | 0.765 | 0.8604 | 0 |
| sat-b | migration | sat-b-nats | 0.0005 | 0.0317 | 0.044800000000000006 | 0 |
| sat-b | migration | sat-b-pathcomp-backend | 0.0 | 0.039 | 0.044000000000000004 | 0 |
| sat-b | migration | sat-b-contextservice | 0.0942 | 0.39049999999999996 | 0.47609999999999997 | 0 |
| sat-b | migration | sat-b-pathcompservice | 0.022099999999999998 | 0.18489999999999998 | 0.207 | 0 |
| sat-b | migration | sat-b-deviceservice | 0.6462 | 0.888 | 0.9898 | 0 |
| sat-b | migration | sat-b-serviceservice | 0.0031 | 0.2182 | 0.256 | 0 |
| sat-b | migration | sat-b-nbiservice | 0.06445000000000001 | 0.2889 | 6.138999999999999 | 1 |
| sat-b | dynamic_observation | sat-b-pathcomp-backend | 0.0 | 0.039900000000000005 | 0.0417 | 0 |
| sat-b | dynamic_observation | sat-b-contextservice | 0.0012 | 0.21420000000000003 | 0.2206 | 0 |
| sat-b | dynamic_observation | sat-b-pathcompservice | 0.022099999999999998 | 0.1999 | 0.2014 | 0 |
| sat-b | dynamic_observation | sat-b-deviceservice | 0.6890999999999999 | 0.8805 | 0.8912 | 0 |
| sat-b | dynamic_observation | sat-b-serviceservice | 0.0032 | 0.2183 | 0.23829999999999998 | 0 |
| sat-b | dynamic_observation | sat-b-nbiservice | 0.031400000000000004 | 0.1459 | 0.17079999999999998 | 0 |
| sat-b | dynamic_observation | sat-b-kafka | 0.019249999999999996 | 2.2233 | 2.4261 | 2 |
| sat-a | dynamic_observation | sat-a-kafka | 0.009399999999999999 | 2.364 | 2.5524 | 2 |
| sat-a | dynamic_observation | sat-a-nats | 0.0005 | 0.0327 | 0.0341 | 0 |
| sat-b | dynamic_observation | sat-b-cockroachdb | 0.0256 | 0.8406 | 0.8656 | 0 |
| sat-a | dynamic_observation | sat-a-cockroachdb | 0.0262 | 0.8459 | 0.9079 | 0 |
| sat-b | dynamic_observation | sat-b-nats | 0.0005 | 0.0322 | 0.0335 | 0 |
| sat-b | target_reconciliation | sat-b-contextservice | 0.0009 | 0.0009 | 0.0009 | 0 |
| sat-b | target_reconciliation | sat-b-pathcompservice | 0.0235 | 0.0235 | 0.0235 | 0 |
| sat-b | target_reconciliation | sat-b-deviceservice | 0.695 | 0.695 | 0.695 | 0 |
| sat-b | target_stable | sat-b-serviceservice | 0.0029 | 0.2141 | 0.25170000000000003 | 0 |
| sat-b | target_stable | sat-b-nbiservice | 0.029300000000000003 | 0.13849999999999998 | 0.18 | 0 |
| sat-b | target_stable | sat-b-kafka | 0.0177 | 2.3337 | 2.4678999999999998 | 10 |
| sat-a | target_stable | sat-a-kafka | 0.0087 | 2.336 | 2.5666 | 9 |
| sat-a | target_stable | sat-a-nats | 0.0004 | 0.0297 | 0.0464 | 0 |
| sat-b | target_stable | sat-b-cockroachdb | 0.022799999999999997 | 0.7198 | 0.8562000000000001 | 0 |
| sat-a | target_stable | sat-a-cockroachdb | 0.0219 | 0.7148 | 0.7888 | 0 |
| sat-b | target_stable | sat-b-nats | 0.0005 | 0.0294 | 0.0375 | 0 |
| sat-b | target_stable | sat-b-pathcomp-backend | 0.0 | 0.038900000000000004 | 0.0479 | 0 |
| sat-b | target_stable | sat-b-contextservice | 0.001 | 0.215 | 0.26539999999999997 | 0 |
| sat-b | target_stable | sat-b-pathcompservice | 0.021 | 0.1993 | 0.2291 | 0 |
| sat-b | target_stable | sat-b-deviceservice | 0.6825 | 0.8553000000000001 | 0.8815999999999999 | 0 |
| sat-b | cleanup | sat-b-kafka | 0.0292 | 0.0292 | 1.403 | 0 |
| sat-a | cleanup | sat-a-kafka | 0.0077 | 0.0184 | 0.0184 | 0 |
| sat-a | cleanup | sat-a-nats | 0.0006 | 0.0313 | 0.0313 | 0 |
| sat-b | cleanup | sat-b-cockroachdb | 0.0848 | 0.12300000000000001 | 0.12300000000000001 | 0 |
| sat-a | cleanup | sat-a-cockroachdb | 0.0222 | 0.0639 | 0.0639 | 0 |
| sat-b | cleanup | sat-b-nats | 0.0007000000000000001 | 0.0281 | 0.0281 | 0 |
| sat-b | cleanup | sat-b-pathcomp-backend | 0.0 | 0.0 | 0.0 | 0 |
| sat-b | cleanup | sat-b-contextservice | 0.1105 | 0.33640000000000003 | 0.33640000000000003 | 0 |
| sat-b | cleanup | sat-b-pathcompservice | 0.0217 | 0.1747 | 0.1747 | 0 |
| sat-b | cleanup | sat-b-deviceservice | 0.6959000000000001 | 0.8258 | 0.8258 | 0 |
| sat-b | cleanup | sat-b-serviceservice | 0.0027 | 0.2004 | 0.2004 | 0 |
| sat-b | cleanup | sat-b-nbiservice | 0.11449999999999999 | 0.1152 | 0.1152 | 0 |

Evidenze: C:\UNIFI-workspaces\satellite-simulation\teraflow-migration-sim\results\runs\run-fc0d676806b64b389ccde469d31cd8eb
