import pandas as pd
import os
from typing import Optional

class DataProcessor:
    def __init__(self, processed_dir: str = "data/processed"):
        self.processed_dir = processed_dir
        os.makedirs(self.processed_dir, exist_ok=True)

    def normalize(self, file_path: str) -> pd.DataFrame:
        """
        Cleans and normalizes the new NSE UDiFF Bhavcopy CSV.
        """
        print(f"[*] Normalizing UDiFF data from: {file_path}")
        df = pd.read_csv(file_path)

        # Mapping new columns to our standard names
        mapping = {
            'TckrSymb': 'SYMBOL',
            'XpryDt': 'EXPIRY_DT',
            'StrkPric': 'STRIKE_PR',
            'OptnTp': 'OPTION_TYP',
            'ClsPric': 'CLOSE',
            'OpnPric': 'OPEN',
            'HghPric': 'HIGH',
            'LwPric': 'LOW',
            'OpnIntrst': 'OPEN_INT',
            'ChngInOpnIntrst': 'CHG_IN_OI',
            'UndrlygPric': 'SPOT_PRICE',
            'TradDt': 'TIMESTAMP',
            'FinInstrmTp': 'INSTRUMENT',
            'NewBrdLotQty': 'LOT_SIZE'
        }
        
        # Select and rename
        df = df.rename(columns=mapping)
        
        # Strip string columns
        for col in df.select_dtypes(include=['object']).columns:
            df[col] = df[col].astype(str).str.strip()
        
        # Ensure dates are datetime
        df['EXPIRY_DT'] = pd.to_datetime(df['EXPIRY_DT'])
        df['TIMESTAMP'] = pd.to_datetime(df['TIMESTAMP'])
        
        # Clean numerical columns
        numeric_cols = ['STRIKE_PR', 'CLOSE', 'OPEN_INT', 'CHG_IN_OI', 'SPOT_PRICE', 'LOT_SIZE']
        for col in numeric_cols:
            if col in df.columns:
                df[col] = pd.to_numeric(df[col], errors='coerce').fillna(0)
            
        # Filter for Options (STO and IXO)
        df_options = df[df['INSTRUMENT'].isin(['STO', 'IXO'])].copy()
        
        # Calculate Future Prices separately (to calculate Cost of Carry)
        df_futures = df[df['INSTRUMENT'].isin(['STF', 'IXF'])].copy()
        
        return df_options, df_futures

    def get_spot_prices(self, df: pd.DataFrame) -> dict:
        """
        In UDiFF, spot price is already in the 'SPOT_PRICE' column.
        We can just take the unique value per symbol.
        """
        # Since it might vary slightly per row (though it shouldn't for the same day), 
        # we take the max or mean.
        spots = df.groupby('SYMBOL')['SPOT_PRICE'].max().to_dict()
        return spots

    def get_lot_sizes(self, df: pd.DataFrame) -> dict:
        """
        In UDiFF, lot size is in 'LOT_SIZE'.
        """
        lots = df.groupby('SYMBOL')['LOT_SIZE'].max().to_dict()
        return lots
