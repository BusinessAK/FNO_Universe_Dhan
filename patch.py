with open("vanguard/engines/intelligence.py", "r") as f:
    text = f.read()

text = text.replace("final = pd.merge(metrics_t, metrics_tm1, on='SYMBOL', suffixes=('_T', '_TM1'))", "final = pd.merge(metrics_t, metrics_tm1, on='SYMBOL', suffixes=('_T', '_TM1'))\n        print('FINAL COLUMNS:', final.columns)\n        print('FINAL INDEX:', final.index.name, type(final.index[0]))")

with open("vanguard/engines/intelligence.py", "w") as f:
    f.write(text)
