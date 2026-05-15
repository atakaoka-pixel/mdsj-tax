"""料金算定ロジック（既存GASのcalculateFee/getFeeを移植）。"""
from __future__ import annotations

import math
from dataclasses import dataclass
from pathlib import Path

import pandas as pd

INDUSTRY_COLS = {
    "卸売業": ("sales_wholesale_min", "sales_wholesale_max"),
    "小売業": ("sales_retail_min", "sales_retail_max"),
    "建設業": ("sales_construction_min", "sales_construction_max"),
    "製造業": ("sales_manufacturing_min", "sales_manufacturing_max"),
    "サービス業その他": ("sales_service_min", "sales_service_max"),
}

MIN_FEE = 25_000
FIRST_ROW_INCOME_MAX = 15_000_000


@dataclass
class FeeResult:
    monthly_total: int
    closing_fee: int
    annual_total: int
    fee_sales: int
    fee_asset: int
    fee_income: int
    sales_yen: int
    asset_yen: int
    income_yen: int
    industry: str


def load_master(csv_path: str | Path) -> pd.DataFrame:
    df = pd.read_csv(csv_path)
    # 最低料金行の自動挿入（先頭行の fee が 25,000 でなければ補う）
    if int(df.iloc[0]["fee"]) > MIN_FEE:
        empty_row = {col: pd.NA for col in df.columns}
        empty_row["fee"] = MIN_FEE
        df = pd.concat([pd.DataFrame([empty_row]), df], ignore_index=True)
    # 先頭行の所得上限を 1,500 万円に固定（既存GAS仕様）
    df.loc[0, "income_min"] = pd.NA
    df.loc[0, "income_max"] = FIRST_ROW_INCOME_MAX
    return df


def _lookup_fee(value: float, df: pd.DataFrame, min_col: str, max_col: str) -> int:
    for i, row in df.iterrows():
        lo = row[min_col]
        hi = row[max_col]
        lo_val = -math.inf if (i == 0 or pd.isna(lo)) else float(lo)
        hi_val = math.inf if pd.isna(hi) else float(hi)
        if lo_val <= value < hi_val:
            return int(row["fee"])
    return int(df.iloc[-1]["fee"])


def calculate_fee(
    df: pd.DataFrame,
    industry: str,
    sales_sen: float,
    profit_sen: float,
    salary_sen: float,
    asset_sen: float,
) -> FeeResult:
    """入力は全て千円単位。"""
    if industry not in INDUSTRY_COLS:
        raise ValueError(f"未対応の業種: {industry}")

    sales_yen = int((sales_sen or 0) * 1000)
    asset_yen = int((asset_sen or 0) * 1000)
    income_yen = int(((profit_sen or 0) + (salary_sen or 0)) * 1000)

    s_min, s_max = INDUSTRY_COLS[industry]
    fee_sales = _lookup_fee(sales_yen, df, s_min, s_max)
    fee_asset = _lookup_fee(asset_yen, df, "asset_min", "asset_max")
    fee_income = _lookup_fee(income_yen, df, "income_min", "income_max")

    monthly_total = fee_sales + fee_asset + fee_income
    closing_fee = monthly_total * 5
    annual_total = monthly_total * 12 + closing_fee

    return FeeResult(
        monthly_total=monthly_total,
        closing_fee=closing_fee,
        annual_total=annual_total,
        fee_sales=fee_sales,
        fee_asset=fee_asset,
        fee_income=fee_income,
        sales_yen=sales_yen,
        asset_yen=asset_yen,
        income_yen=income_yen,
        industry=industry,
    )


def format_range(lo, hi) -> str:
    def yen(v):
        v = float(v)
        if v >= 100_000_000:
            return f"{v / 100_000_000:g}億円"
        return f"{v / 10_000:g}万円"

    lo_blank = pd.isna(lo) or lo == ""
    hi_blank = pd.isna(hi) or hi == ""
    if lo_blank and hi_blank:
        return "-"
    if hi_blank:
        return f"{yen(lo)} 以上"
    if lo_blank:
        return f"{yen(hi)} 未満"
    return f"{yen(lo)} ～ {yen(hi)}"
