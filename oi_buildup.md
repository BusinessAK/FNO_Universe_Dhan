# Implementation Plan: Correcting F&O Buildup Calculations using Futures OI

This plan details the steps to modify the institutional EOD compiler pipeline and the matrix dashboard UI to use **Futures Open Interest** (rather than options open interest sum) for determining F&O Buildup (LB, SB, LU, SC).

## Proposed Changes

### Component: Data Compilation Pipeline

#### [MODIFY] [intelligence.py](file:///Users/shivanidamodar/Desktop/FNO_BHAV/src/intelligence.py)
* Aggregate `OPEN_INT` and `CHG_IN_OI` from the normalized futures DataFrame `df_fut_t`.
* Merge these aggregated futures metrics (`FUT_OI_T` and `FUT_CHG_OI_T`) into the `final` dataframe.

#### [MODIFY] [daily_compiler.py](file:///Users/shivanidamodar/Desktop/FNO_BHAV/daily_compiler.py)
* Extract `FUT_OI_T` and `FUT_CHG_OI_T` from the intelligence results.
* Save them as `futures_oi` and `futures_oi_chg` in `day_data` and include them in the flattened `df_structure` for Parquet & DuckDB export.

#### [MODIFY] [states.py](file:///Users/shivanidamodar/Desktop/FNO_BHAV/src/models/states.py)
* Add `futures_oi` and `futures_oi_chg` fields to the `SignalState` dataclass.
* Update `from_dict` constructor to parse these fields.

---

### Component: User Interface

#### [MODIFY] [matrix.py](file:///Users/shivanidamodar/Desktop/FNO_BHAV/src/ui/matrix.py)
* Retrieve `futures_oi_chg` as the underlying `delta_oi` instead of options `delta_ce_oi` + `delta_pe_oi`.
* Update tooltip description to read `Futures OI Shift` instead of `Options OI Shift`.

---

## Verification Plan

### Automated/Manual Compilation Test
1. Run `./start.sh` or `python3 daily_compiler.py --force` to compile the database.
2. Verify that the compilation succeeds and the DuckDB tables have the new columns.

### Dashboard Verification
1. Run the Streamlit application and check the "F&O Buildup" column in the dashboard matrix to ensure it shows accurate buildup signals aligning with price trends.
