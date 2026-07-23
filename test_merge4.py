import pandas as pd
import sys
sys.path.append('.')
from vanguard.engines.intelligence import InstitutionalIntelligence
intel = InstitutionalIntelligence()
df_t_opt, _ = intel.processor.normalize('data/raw/FO_BhavCopy_NSE_FO_0_0_0_20260722_F_0000.csv')
metrics_t = df_t_opt.groupby('SYMBOL').apply(intel.calc_metrics).reset_index()
print("metrics_t pre merge", metrics_t.index.name, type(metrics_t.index[0]))
