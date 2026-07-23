import pandas as pd
df1 = pd.DataFrame({'A': [1,2]}, index=['X','Y'])
df1.index.name = 'SYMBOL'
df2 = pd.DataFrame({'B': [3,4]}, index=['X','Y'])
df2.index.name = 'SYMBOL'
res = pd.merge(df1, df2, on='SYMBOL')
print(res.columns)
print(res.index.name)
print(type(res.index[0]))
