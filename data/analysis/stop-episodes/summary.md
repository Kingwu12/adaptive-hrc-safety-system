# Stop-episode analysis

## Applied command, by recorded controller (closed loop, totals)

| group | trials | raw_onsets | short_stop_segments | stop_s | observed_s | episodes_gap0.25_min0.0 | episodes_gap0.25_min0.5 | episodes_gap0.25_min1.0 | episodes_gap0.5_min0.0 | episodes_gap0.5_min0.5 | episodes_gap0.5_min1.0 | episodes_gap1.0_min0.0 | episodes_gap1.0_min0.5 | episodes_gap1.0_min1.0 |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| fixed zone | 32 | 659 | 673 | 1145.2 | 3717.7 | 748 | 162 | 141 | 691 | 160 | 140 | 589 | 155 | 137 |
| reactive SSM | 32 | 888 | 858 | 1197.9 | 3531.4 | 768 | 177 | 157 | 676 | 170 | 153 | 548 | 160 | 146 |
| predictive SSM | 33 | 1417 | 1378 | 1350.8 | 3639.3 | 919 | 223 | 187 | 777 | 215 | 187 | 624 | 200 | 177 |

## Applied command, legacy_operator_confirmed

| group | trials | raw_onsets | short_stop_segments | stop_s | observed_s | episodes_gap0.25_min0.0 | episodes_gap0.25_min0.5 | episodes_gap0.25_min1.0 | episodes_gap0.5_min0.0 | episodes_gap0.5_min0.5 | episodes_gap0.5_min1.0 | episodes_gap1.0_min0.0 | episodes_gap1.0_min0.5 | episodes_gap1.0_min1.0 |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| fixed zone | 17 | 86 | 64 | 621.3 | 1945.5 | 147 | 83 | 76 | 146 | 82 | 75 | 139 | 78 | 72 |
| reactive SSM | 17 | 88 | 62 | 595.6 | 1770.8 | 146 | 87 | 79 | 143 | 85 | 77 | 137 | 83 | 76 |
| predictive SSM | 18 | 305 | 281 | 674.0 | 1986.0 | 204 | 95 | 89 | 195 | 94 | 89 | 185 | 90 | 86 |

## Applied command, automatic_streams

| group | trials | raw_onsets | short_stop_segments | stop_s | observed_s | episodes_gap0.25_min0.0 | episodes_gap0.25_min0.5 | episodes_gap0.25_min1.0 | episodes_gap0.5_min0.0 | episodes_gap0.5_min0.5 | episodes_gap0.5_min1.0 | episodes_gap1.0_min0.0 | episodes_gap1.0_min0.5 | episodes_gap1.0_min1.0 |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| fixed zone | 15 | 573 | 609 | 523.9 | 1772.1 | 601 | 79 | 65 | 545 | 78 | 65 | 450 | 77 | 65 |
| reactive SSM | 15 | 800 | 796 | 602.4 | 1760.6 | 622 | 90 | 78 | 533 | 85 | 76 | 411 | 77 | 70 |
| predictive SSM | 15 | 1112 | 1097 | 676.8 | 1653.3 | 715 | 128 | 98 | 582 | 121 | 98 | 439 | 110 | 91 |

## Applied stop onsets by issuing rule and duration (brief < 0.5 s)

| cause | fixed zone | reactive SSM | predictive SSM |
|---|---|---|---|
| sensing dropout hold|brief | 450 | 414 | 326 |
| sensing dropout hold|sustained | 1 | 2 | 1 |
| intrusion predictor|brief | 0 | 0 | 805 |
| intrusion predictor|sustained | 0 | 0 | 104 |
| red boundary|brief | 43 | 14 | 32 |
| red boundary|sustained | 164 | 156 | 101 |
| envelope minimum|brief | 0 | 279 | 37 |
| envelope minimum|sustained | 0 | 23 | 11 |
| tracking unavailable|sustained | 1 | 0 | 0 |

## Shadow commands on identical inputs (33 trials, open loop)

| group | trials | raw_onsets | short_stop_segments | stop_s | observed_s | episodes_gap0.25_min0.0 | episodes_gap0.25_min0.5 | episodes_gap0.25_min1.0 | episodes_gap0.5_min0.0 | episodes_gap0.5_min0.5 | episodes_gap0.5_min1.0 | episodes_gap1.0_min0.0 | episodes_gap1.0_min0.5 | episodes_gap1.0_min1.0 |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| fixed zone | 33 | 283 | 194 | 1206.6 | 3929.5 | 654 | 473 | 343 | 647 | 471 | 345 | 631 | 463 | 345 |
| reactive SSM | 33 | 954 | 870 | 1247.0 | 3929.5 | 975 | 479 | 354 | 906 | 476 | 357 | 849 | 471 | 354 |
| predictive SSM | 33 | 1863 | 1727 | 1429.1 | 3929.5 | 1420 | 556 | 384 | 1251 | 554 | 394 | 1109 | 545 | 396 |

## Offline 0.5-s minimum stop dwell on applied predictive commands

| group | trials | raw_onsets | short_stop_segments | stop_s | observed_s | episodes_gap0.25_min0.0 | episodes_gap0.25_min0.5 | episodes_gap0.25_min1.0 | episodes_gap0.5_min0.0 | episodes_gap0.5_min0.5 | episodes_gap0.5_min1.0 | episodes_gap1.0_min0.0 | episodes_gap1.0_min0.5 | episodes_gap1.0_min1.0 |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| predictive SSM | 33 | 577 | 73 | 1782.7 | 3639.3 | 695 | 626 | 268 | 633 | 568 | 266 | 519 | 461 | 241 |

## Offline 0.5-s minimum stop dwell on shadow predictive commands

| group | trials | raw_onsets | short_stop_segments | stop_s | observed_s | episodes_gap0.25_min0.0 | episodes_gap0.25_min0.5 | episodes_gap0.25_min1.0 | episodes_gap0.5_min0.0 | episodes_gap0.5_min0.5 | episodes_gap0.5_min1.0 | episodes_gap1.0_min0.0 | episodes_gap1.0_min0.5 | episodes_gap1.0_min1.0 |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| predictive SSM | 33 | 694 | 324 | 1902.0 | 3929.5 | 1250 | 951 | 509 | 1186 | 898 | 508 | 1103 | 835 | 516 |

## Offline 1.0-s minimum stop dwell on applied predictive commands

| group | trials | raw_onsets | short_stop_segments | stop_s | observed_s | episodes_gap0.25_min0.0 | episodes_gap0.25_min0.5 | episodes_gap0.25_min1.0 | episodes_gap0.5_min0.0 | episodes_gap0.5_min0.5 | episodes_gap0.5_min1.0 | episodes_gap1.0_min0.0 | episodes_gap1.0_min0.5 | episodes_gap1.0_min1.0 |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| predictive SSM | 33 | 420 | 70 | 2064.2 | 3639.3 | 569 | 506 | 487 | 523 | 462 | 445 | 449 | 396 | 383 |

## Offline 1.0-s minimum stop dwell on shadow predictive commands

| group | trials | raw_onsets | short_stop_segments | stop_s | observed_s | episodes_gap0.25_min0.0 | episodes_gap0.25_min0.5 | episodes_gap0.25_min1.0 | episodes_gap0.5_min0.0 | episodes_gap0.5_min0.5 | episodes_gap0.5_min1.0 | episodes_gap1.0_min0.0 | episodes_gap1.0_min0.5 | episodes_gap1.0_min1.0 |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| predictive SSM | 33 | 515 | 313 | 2174.3 | 3929.5 | 1209 | 913 | 714 | 1174 | 887 | 693 | 1124 | 853 | 663 |

Per-trial shadow onset ratio predictive/reactive: median 1.89 (n=33), IQR 1.61-2.43

