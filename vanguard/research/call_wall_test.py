import duckdb
import pandas as pd

con = duckdb.connect('data/compiled/vanguard.duckdb')
df = con.execute("""
    SELECT symbol, date, spot_close, call_wall, spot_change_pct
    FROM daily_market_structure
    WHERE call_wall > 0
    ORDER BY symbol, date
""").df()

df['spot_to_wall'] = df['spot_close'] / df['call_wall'] - 1
# Near call wall: spot is within 0.5% below or above the call wall
df['near_wall'] = df['spot_to_wall'].abs() < 0.005

df['fwd_1d'] = df.groupby('symbol')['spot_close'].shift(-1) / df['spot_close'] - 1
df['fwd_5d'] = df.groupby('symbol')['spot_close'].shift(-5) / df['spot_close'] - 1

near = df[df['near_wall'] == True]

print(f"Total instances of spot near Call Wall (Peak Gamma): {len(near)}")
print(f"1-Day Forward Return: {near['fwd_1d'].mean()*100:.2f}% (Win Rate: {(near['fwd_1d']>0).mean()*100:.1f}%)")
print(f"5-Day Forward Return: {near['fwd_5d'].mean()*100:.2f}% (Win Rate: {(near['fwd_5d']>0).mean()*100:.1f}%)")

# What if it's right BELOW the wall (-1% to 0%)?
below = df[(df['spot_to_wall'] >= -0.01) & (df['spot_to_wall'] < 0)]
print(f"\nInstances just BELOW Call Wall (Resistance): {len(below)}")
print(f"1-Day Forward Return: {below['fwd_1d'].mean()*100:.2f}% (Win Rate: {(below['fwd_1d']>0).mean()*100:.1f}%)")
print(f"5-Day Forward Return: {below['fwd_5d'].mean()*100:.2f}% (Win Rate: {(below['fwd_5d']>0).mean()*100:.1f}%)")
