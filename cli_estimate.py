"""コマンドライン版の見積書生成。Claude Code Skill から呼び出される。

使い方:
    python cli_estimate.py --industry 製造業 --sales 300000 --profit 20000 \\
        --salary 12000 --asset 80000 --client "株式会社サンプル工業"

数値はすべて千円単位。
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import date
from pathlib import Path

from fee_calculator import calculate_fee, load_master
from estimate_pdf import EstimateInfo, build_estimate_pdf

BASE_DIR = Path(__file__).parent
INDUSTRIES = ["卸売業", "小売業", "建設業", "製造業", "サービス業その他"]


def main() -> int:
    p = argparse.ArgumentParser(description="税務顧問料見積書PDFを生成")
    p.add_argument("--industry", required=True, choices=INDUSTRIES, help="業種")
    p.add_argument("--sales", type=int, required=True, help="売上高（千円）")
    p.add_argument("--profit", type=int, default=0, help="経常利益（千円、デフォルト0）")
    p.add_argument("--salary", type=int, default=0, help="役員報酬（千円、デフォルト0）")
    p.add_argument("--asset", type=int, required=True, help="総資産（千円）")
    p.add_argument("--client", required=True, help="宛先会社名（御中なしで指定）")
    p.add_argument("--estimate-no", default="", help="見積番号（任意）")
    p.add_argument("--issue-date", default="", help="発行日 YYYY-MM-DD（省略時は今日）")
    p.add_argument("--valid-days", type=int, default=30, help="有効期限の日数")
    p.add_argument("--contract-term", default="1事業年度（自動更新）", help="契約期間表記")
    p.add_argument("--notes", default="", help="備考（任意）")
    p.add_argument("--output", "-o", default="", help="出力PDFパス（省略時は ~/Downloads）")
    p.add_argument("--json", action="store_true", help="結果をJSONで出力")
    args = p.parse_args()

    issue = date.fromisoformat(args.issue_date) if args.issue_date else date.today()

    df = load_master(BASE_DIR / "master.csv")
    result = calculate_fee(
        df,
        industry=args.industry,
        sales_sen=args.sales,
        profit_sen=args.profit,
        salary_sen=args.salary,
        asset_sen=args.asset,
    )

    info = EstimateInfo(
        client_name=args.client,
        issue_date=issue,
        estimate_no=args.estimate_no,
        valid_days=args.valid_days,
        contract_term=args.contract_term,
        notes=args.notes,
    )

    pdf_bytes = build_estimate_pdf(result, info)

    safe = (
        args.client.replace("/", "_").replace("\\", "_").replace(":", "_").strip()
    )
    default_name = f"御見積書_{safe}_{issue.strftime('%Y%m%d')}.pdf"
    out = Path(args.output) if args.output else Path.home() / "Downloads" / default_name
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes(pdf_bytes)

    payload = {
        "industry": args.industry,
        "client": args.client,
        "issue_date": issue.isoformat(),
        "monthly_total": result.monthly_total,
        "closing_fee": result.closing_fee,
        "annual_total": result.annual_total,
        "fee_sales": result.fee_sales,
        "fee_asset": result.fee_asset,
        "fee_income": result.fee_income,
        "pdf_path": str(out),
    }

    # Windowsのcp932コンソールでも安全に出すため、stdoutをUTF-8に再構成
    try:
        sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
    except Exception:
        pass

    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        print(f"業種:   {args.industry}")
        print(f"宛先:   {args.client}")
        print(f"月額:   ￥{result.monthly_total:,}")
        print(f"  内訳:  売上 ￥{result.fee_sales:,} + 総資産 ￥{result.fee_asset:,} + 所得 ￥{result.fee_income:,}")
        print(f"決算料: ￥{result.closing_fee:,}  （月額×5）")
        print(f"年額:   ￥{result.annual_total:,}")
        print(f"PDF:    {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
