import pandas as pd
df1 = pd.DataFrame({'A': [1,2]}, index=['X','Y'])
df1.index.name = 'SYMBOL'
df2 = pd.DataFrame({'B': [3,4]}, index=['X','Y'])
df2.index.name = 'SYMBOL'
df_walls = pd.DataFrame({'SYMBOL': ['X','Y'], 'C': [5,6]})
df1 = pd.merge(df1.reset_index(), df_walls, on='SYMBOL').set_index('SYMBOL')
res = pd.merge(df1, df2, on='SYMBOL')
print(res.index.name)
print(type(res.index[0]))
print(res.columns)
