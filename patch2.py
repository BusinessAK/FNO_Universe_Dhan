with open("vanguard/engines/intelligence.py", "r") as f:
    text = f.read()

# Restore top part to final.index.map
text = text.replace("final['SPOT_T'] = final['SYMBOL'].map(spots_t)", "final['SPOT_T'] = final.index.map(spots_t)")
text = text.replace("final['SPOT_TM1'] = final['SYMBOL'].map(spots_tm1)", "final['SPOT_TM1'] = final.index.map(spots_tm1)")
text = text.replace("print('FINAL COLUMNS:', final.columns)\n        print('FINAL INDEX:', final.index.name, type(final.index[0]))\n        ", "")

with open("vanguard/engines/intelligence.py", "w") as f:
    f.write(text)
