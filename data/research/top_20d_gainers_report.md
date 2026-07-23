# Top 20-Session Gainers Attribution

- Events studied: `47,190`
- Forward horizon: `20` trading sessions
- Top-decile cutoff: `10.43%`
- Universe: compiled F&O symbols with cash OHLC

## Top Metric Buckets By Gainer Rate

| metric          | value               |   samples |   avg_fwd_20d_pct |   median_fwd_20d_pct |   top_gainer_rate_pct |   win_rate_pct |
|:----------------|:--------------------|----------:|------------------:|---------------------:|----------------------:|---------------:|
| ml_bucket       | ml_gt_60            |      2765 |             3.683 |                3.451 |                23.725 |         65.389 |
| ml_bucket       | ml_0_30             |        31 |            -0.319 |               -2.305 |                19.355 |         41.935 |
| sector          | NIFTY METAL         |      2016 |             2.806 |                2.947 |                17.411 |         64.633 |
| sector          | NIFTY MEDIA & COMM  |       672 |             2.241 |                1.12  |                16.369 |         56.845 |
| ret20_bucket    | ret_lt_-5           |     10662 |             2.116 |                1.521 |                16.198 |         57.456 |
| gamma_regime    | SHORT_GAMMA         |      1551 |             2.483 |                2.341 |                15.925 |         63.121 |
| sector          | NIFTY INFRA         |      3999 |             1.552 |                0.824 |                14.879 |         53.563 |
| setup_flag      | gamma_squeeze       |       354 |             2.044 |                2.031 |                14.689 |         61.582 |
| rs20_bucket     | rs_gt_10            |      4370 |             0.391 |                0.147 |                14.027 |         50.549 |
| sector          | NIFTY AUTO          |      3123 |             0.883 |                0.794 |                13.673 |         54.371 |
| ml_bucket       | ml_50_60            |     13419 |             0.362 |                0.253 |                12.259 |         51.204 |
| sector          | NIFTY SERVICES      |      1379 |             0.064 |               -0.622 |                12.11  |         46.918 |
| sector          | NIFTY ENERGY        |      3110 |             0.304 |               -0.908 |                12.058 |         44.598 |
| ret20_bucket    | ret_gt_10           |      4804 |            -0.349 |               -0.377 |                11.678 |         48.043 |
| structural_bias | Expansion           |     22436 |             0.163 |               -0.106 |                11.544 |         49.474 |
| rs20_bucket     | rs_lt_-5            |      8673 |             0.535 |               -0.08  |                11.484 |         49.475 |
| sector          | NIFTY FIN SERVICE   |      7257 |            -0.808 |               -0.588 |                11.368 |         46.328 |
| rs20_bucket     | rs_5_10             |      6117 |             0.045 |                0.151 |                11.117 |         50.809 |
| sector          | NIFTY PSU BANK      |      1568 |             1.573 |                1.804 |                10.969 |         60.14  |
| setup_flag      | inventory_migration |     20476 |             0.015 |               -0.172 |                10.905 |         49.087 |

## Top Realized 20-Session Gainers

| symbol     | sector             | date                |   fwd_return_20d_pct | setup_types                                                        |   ifs_score |   trend_ret20_pct |   trend_rs20_pct |     net_inv_shift |        gex_shift | gamma_regime      | structural_bias   |
|:-----------|:-------------------|:--------------------|---------------------:|:-------------------------------------------------------------------|------------:|------------------:|-----------------:|------------------:|-----------------:|:------------------|:------------------|
| BHEL       | NIFTY INFRA        | 2026-04-06 00:00:00 |              57.1522 | INVENTORY_MIGRATION                                                |       -74.8 |         -0.911658 |         5.26571  |      -1.39388e+06 | -32305.4         | TRANSITION_REGIME | Expansion         |
| BHEL       | NIFTY INFRA        | 2026-04-07 00:00:00 |              55.6087 | FLOOR_BOUNCE|REGIME_SHIFT|INVENTORY_MIGRATION|IV_SKEW_ACCUMULATION |       100   |         -1.42274  |         5.20835  |       3.64612e+06 |  64269           | LONG_GAMMA        | Expansion         |
| ADANIGREEN | NIFTY ENERGY       | 2026-04-02 00:00:00 |              55.3559 |                                                                    |       -10.1 |         -5.26258  |         3.39433  | -207000           |   7499.47        | TRANSITION_REGIME | Dealer Controlled |
| ADANIGREEN | NIFTY ENERGY       | 2026-04-01 00:00:00 |              53.6548 |                                                                    |        16.4 |        -10.0702   |        -0.144127 |  152400           |  13236.7         | TRANSITION_REGIME | Expansion         |
| BHEL       | NIFTY INFRA        | 2026-04-08 00:00:00 |              51.8199 | INVENTORY_MIGRATION                                                |         2.9 |          2.60668  |         4.45982  | -105000           | 165688           | LONG_GAMMA        | Expansion         |
| BHEL       | NIFTY INFRA        | 2026-04-01 00:00:00 |              51.4561 | REGIME_SHIFT|INVENTORY_MIGRATION                                   |        22.5 |         -4.9481   |         4.97796  |  354375           |  31236.8         | TRANSITION_REGIME | Expansion         |
| ADANIGREEN | NIFTY ENERGY       | 2026-03-27 00:00:00 |              50.3382 | INVENTORY_MIGRATION|IV_SKEW_ACCUMULATION                           |        24.2 |        -13.6545   |        -3.2046   |  545400           | -92604.4         | TRANSITION_REGIME | Expansion         |
| BHEL       | NIFTY INFRA        | 2026-04-02 00:00:00 |              50.3348 | REGIME_SHIFT                                                       |      -100   |         -5.35571  |         3.30119  |      -3.57e+06    | 127578           | LONG_GAMMA        | Flip Zone         |
| ADANIENSOL | NIFTY ENERGY       | 2026-04-02 00:00:00 |              49.655  |                                                                    |        -9.3 |         -3.15746  |         5.49944  | -132300           |   1892.75        | TRANSITION_REGIME | Dealer Controlled |
| ADANIENSOL | NIFTY ENERGY       | 2026-03-27 00:00:00 |              49.2475 | GAMMA_SQUEEZE|INVENTORY_MIGRATION                                  |        -1.1 |         -5.62685  |         4.82307  |   88425           | -65503.1         | SHORT_GAMMA       | Expansion         |
| ADANIENSOL | NIFTY ENERGY       | 2026-04-01 00:00:00 |              48.766  | INVENTORY_MIGRATION                                                |        -4.3 |         -5.43226  |         4.49381  | -148500           |   5395.5         | TRANSITION_REGIME | Expansion         |
| POWERINDIA | NIFTY INFRA        | 2026-01-27 00:00:00 |              48.7634 | INVENTORY_MIGRATION                                                |         3   |         -8.94278  |        -5.61396  |   22250           |    278.593       | TRANSITION_REGIME | Expansion         |
| ADANIGREEN | NIFTY ENERGY       | 2026-03-23 00:00:00 |              48.3553 |                                                                    |       -66.5 |        -15.6778   |        -3.71668  |      -1.1082e+06  | -49651.9         | TRANSITION_REGIME | Expansion         |
| ANGELONE   | NIFTY FIN SERVICE  | 2026-03-16 00:00:00 |              47.922  | PINCH_ZONE                                                         |       -32.6 |        -91.9716   |       -83.875    | -637500           |  23111.9         | TRANSITION_REGIME | Support Weakening |
| ADANIGREEN | NIFTY ENERGY       | 2026-03-30 00:00:00 |              47.8583 | INVENTORY_MIGRATION                                                |        -6.7 |        -16.4657   |        -4.05162  |  -36000           |  -6081.94        | TRANSITION_REGIME | Expansion         |
| ADANIENSOL | NIFTY ENERGY       | 2026-03-24 00:00:00 |              47.7312 | INVENTORY_MIGRATION                                                |         6.1 |         -3.63618  |         7.25558  |   58725           |   2383.57        | TRANSITION_REGIME | Expansion         |
| ADANIGREEN | NIFTY ENERGY       | 2026-03-25 00:00:00 |              46.9751 | INVENTORY_MIGRATION                                                |        31.9 |        -12.9974   |        -4.66612  |  558000           |   6939.64        | TRANSITION_REGIME | Expansion         |
| ADANIGREEN | NIFTY ENERGY       | 2026-04-06 00:00:00 |              46.8896 | INVENTORY_MIGRATION                                                |        -4.2 |          5.63679  |        11.8142   | -311400           |   8742.41        | TRANSITION_REGIME | Expansion         |
| IDEA       | NIFTY MEDIA & COMM | 2026-04-24 00:00:00 |              46.5553 |                                                                    |      -100   |          9.42529  |         3.27186  |      -3.00195e+06 |     -1.15392e+07 | LONG_GAMMA        | Support Weakening |
| ANGELONE   | NIFTY FIN SERVICE  | 2026-03-17 00:00:00 |              46.4709 | VOLATILITY_COIL|PINCH_ZONE                                         |       -32.3 |        -91.5664   |       -83.3835   | -625000           |  41789.5         | TRANSITION_REGIME | Compression       |
| ADANIGREEN | NIFTY ENERGY       | 2026-03-24 00:00:00 |              45.8719 | INVENTORY_MIGRATION                                                |         2.8 |        -13.4797   |        -2.58791  |  -34200           |  54206.4         | TRANSITION_REGIME | Expansion         |
| IDEA       | NIFTY MEDIA & COMM | 2026-04-27 00:00:00 |              45.7732 | PINCH_ZONE                                                         |       100   |          9.12162  |         3.97026  |       7.57635e+06 |     -3.78131e+06 | LONG_GAMMA        | Support Building  |
| ADANIENSOL | NIFTY ENERGY       | 2026-03-25 00:00:00 |              45.731  | INVENTORY_MIGRATION                                                |         5.6 |         -4.50294  |         3.82834  |   35775           |  25270.9         | TRANSITION_REGIME | Expansion         |
| POWERINDIA | NIFTY INFRA        | 2026-01-23 00:00:00 |              45.6036 | REGIME_SHIFT|INVENTORY_MIGRATION                                   |        -2.7 |        -10.418    |        -6.23531  |    6450           |  -3239.1         | TRANSITION_REGIME | Expansion         |
| ADANIENSOL | NIFTY ENERGY       | 2026-03-23 00:00:00 |              45.5469 | INVENTORY_MIGRATION                                                |       -18.9 |         -5.12975  |         6.83134  | -180225           | -37740.3         | TRANSITION_REGIME | Expansion         |
