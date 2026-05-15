"""算定結果からA4縦の見積書PDFを生成する。

HTML→Edgeヘッドレス印刷で PDF を出力するため、追加のPythonパッケージ不要。
ただし Microsoft Edge がインストールされている必要がある（標準でWindowsに入っている）。
"""
from __future__ import annotations

import base64
import html
import os
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path
from typing import Optional

from fee_calculator import FeeResult

EDGE_CANDIDATES = [
    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
]

BASE_DIR = Path(__file__).parent
LOGO_PATH = BASE_DIR / "logo.png"

FIRM_ADDRESS = "大阪市中央区今橋４－１－１　淀屋橋三井ビルディング４F"
FIRM_REPRESENTATIVE = "代表社員　才木　正之"


def _logo_data_uri() -> str:
    if not LOGO_PATH.exists():
        return ""
    data = LOGO_PATH.read_bytes()
    return "data:image/png;base64," + base64.standard_b64encode(data).decode("ascii")


def _split_paren(s: str) -> tuple[str, str]:
    """『題名（補足）』を題名と補足に分割する。"""
    for paren in ("（", "("):
        if paren in s:
            i = s.index(paren)
            return s[:i].strip(), s[i:].strip()
    return s, ""


@dataclass
class EstimateInfo:
    client_name: str
    issue_date: date
    estimate_no: str = ""
    valid_days: int = 30
    contract_term: str = "1事業年度（自動更新）"
    notes: str = ""
    # 値引き等を反映した最終提示金額（円）。Noneなら自動算定値をそのまま使う。
    final_monthly: Optional[int] = None
    final_closing: Optional[int] = None


def _find_edge() -> str:
    for p in EDGE_CANDIDATES:
        if Path(p).exists():
            return p
    raise RuntimeError("Microsoft Edge が見つかりません。Edgeがインストールされているか確認してください。")


def _fmt_yen(n: int) -> str:
    return f"{int(n):,}"


def build_estimate_html(result: FeeResult, info: EstimateInfo) -> str:
    valid_until = info.issue_date + timedelta(days=info.valid_days)
    logo_uri = _logo_data_uri()

    # 自動算定値
    auto_monthly = result.monthly_total
    auto_closing = result.closing_fee
    auto_annual = result.annual_total

    # 確定（提示）金額: 未指定なら自動値と同じ
    final_monthly = info.final_monthly if info.final_monthly is not None else auto_monthly
    final_closing = info.final_closing if info.final_closing is not None else auto_closing
    final_annual = final_monthly * 12 + final_closing

    # 値引きの有無判定
    has_discount = (final_monthly != auto_monthly) or (final_closing != auto_closing)

    # 各セルのHTML（値引きあり/なしで切替）
    if has_discount:
        annual_html = (
            f'<div class="price-compare">'
            f'<div class="price-list">定価 ¥{_fmt_yen(auto_annual)}</div>'
            f'<div class="price-final">¥{_fmt_yen(final_annual)}<span class="price-final-yen">JPY</span></div>'
            f'</div>'
        )
        monthly_html = (
            f'<div class="sub-compare-list">定価 ¥{_fmt_yen(auto_monthly)}</div>'
            f'<div class="sub-value sub-compare-final">¥{_fmt_yen(final_monthly)}'
            f'<span class="yen-unit">円 / 月</span></div>'
        )
        closing_html = (
            f'<div class="sub-compare-list">定価 ¥{_fmt_yen(auto_closing)}</div>'
            f'<div class="sub-value sub-compare-final">¥{_fmt_yen(final_closing)}'
            f'<span class="yen-unit">円</span></div>'
        )
        closing_note = "※ ご提示価格に値引き等を反映済"
    else:
        annual_html = (
            f'<div class="hero-value">¥{_fmt_yen(auto_annual)}'
            f'<span class="hero-yen">JPY</span></div>'
        )
        monthly_html = (
            f'<div class="sub-value">¥{_fmt_yen(auto_monthly)}'
            f'<span class="yen-unit">円 / 月</span></div>'
        )
        closing_html = (
            f'<div class="sub-value">¥{_fmt_yen(auto_closing)}'
            f'<span class="yen-unit">円</span></div>'
        )
        closing_note = "※ 月額顧問報酬の5ヶ月分"

    included = [
        "税務顧問業務（法人税・法人住民税・法人事業税・消費税・源泉所得税の税務代理及び税務相談）",
        "会計顧問業務（会計帳簿の記帳及び税務書類作成等に係る相談・指導）",
        "決算書類作成業務（決算・申告書類の作成）",
        "月次監査による経営状況・課題の共有",
        "決算3ヶ月前からの決算予測・納税予測",
        "予定申告・各種届出書の作成提出",
        "電話・メール等による税務相談および簡易な書面による回答（2時間以内で作成可能なもの）",
    ]
    included_items = [_split_paren(x) for x in included]
    excluded = [
        ("税務調査対応・意見聴取対応", "人日当 100,000円"),
        ("修正申告書作成", "当社申告分 30,000円／他社 50,000円"),
        ("償却資産税申告書作成", "1自治体毎 20,000円"),
        ("年末調整・法定調書合計表", "別途料金規定"),
        ("事業所税申告書作成", "別途お見積り"),
        ("グループ通算制度・連結決算", "別途お見積り"),
        ("代表取締役等、構成員個人の納税申告", "別途お見積り"),
        ("経営に関する相談・支援・指導等", "別途お見積り"),
    ]

    esc = html.escape

    def _included_li(title: str, sub: str) -> str:
        sub_html = f'<div class="scope-sub">{esc(sub)}</div>' if sub else ""
        return (
            f'<li><span class="check">✓</span>'
            f'<div class="scope-text"><div class="scope-title">{esc(title)}</div>{sub_html}</div></li>'
        )

    included_html = "\n".join(_included_li(t, s) for t, s in included_items)
    excluded_html = "\n".join(
        f'<li><span class="label">{esc(label)}</span><span class="price">{esc(price)}</span></li>'
        for label, price in excluded
    )

    estimate_no_html = (
        f'<div class="meta-row"><span class="meta-label">見積番号</span><span class="meta-value">{esc(info.estimate_no)}</span></div>'
        if info.estimate_no else ""
    )
    notes_html = (
        f'<section class="notes"><h3>備考</h3><p>{esc(info.notes)}</p></section>'
        if info.notes else ""
    )

    return f"""<!DOCTYPE html>
<html lang="ja">
<head>
<meta charset="utf-8">
<title>御見積書 {esc(info.client_name)}</title>
<link href="https://fonts.googleapis.com/css2?family=Noto+Sans+JP:wght@300;400;500;700&family=Noto+Serif+JP:wght@400;500;600;700&family=Inter:wght@300;400;500;600;700&display=swap" rel="stylesheet">
<style>
  @page {{
    size: A4 portrait;
    margin: 11mm 12mm 6mm 12mm;
  }}
  * {{ box-sizing: border-box; }}
  body {{
    font-family: "Noto Sans JP", sans-serif;
    font-weight: 400;
    color: #2d2d2d;
    font-size: 9pt;
    line-height: 1.55;
    margin: 0;
    padding: 0;
    -webkit-print-color-adjust: exact;
    print-color-adjust: exact;
  }}
  .doc-header {{
    display: flex;
    justify-content: space-between;
    align-items: flex-end;
    padding-bottom: 10px;
    border-bottom: 3px solid #1a1a1a;
    margin-bottom: 16px;
    position: relative;
  }}
  .doc-header::after {{
    content: '';
    position: absolute;
    bottom: -3px;
    left: 0;
    width: 90px;
    height: 3px;
    background: #b71c1c;
  }}
  .doc-title {{
    font-family: "Noto Serif JP", serif;
    font-weight: 500;
    font-size: 28pt;
    letter-spacing: 0.18em;
    margin: 0;
    line-height: 1;
    color: #1a1a1a;
  }}
  .doc-title-en {{
    font-family: "Inter", sans-serif;
    font-size: 8pt;
    letter-spacing: 0.3em;
    color: #999;
    margin-top: 6px;
    font-weight: 400;
  }}
  .doc-meta {{
    text-align: right;
    font-size: 9pt;
    color: #2d2d2d;
  }}
  .meta-row {{
    display: flex;
    justify-content: flex-end;
    gap: 12px;
    margin-bottom: 3px;
  }}
  .meta-label {{
    color: #999;
    font-size: 8pt;
    letter-spacing: 0.1em;
  }}
  .meta-value {{
    font-family: "Inter", sans-serif;
    font-weight: 400;
    color: #1a1a1a;
  }}

  .addressee {{
    display: flex;
    justify-content: space-between;
    align-items: flex-start;
    margin-bottom: 18px;
  }}
  .addressee-left {{
    flex: 1;
    padding-right: 16px;
  }}
  .client-name {{
    font-family: "Noto Serif JP", serif;
    font-size: 17pt;
    font-weight: 500;
    margin-bottom: 4px;
    letter-spacing: 0.04em;
    color: #1a1a1a;
  }}
  .addressee-msg {{
    font-size: 9pt;
    color: #555;
  }}
  .firm-info {{
    text-align: right;
    font-size: 8.5pt;
    line-height: 1.6;
    min-width: 220px;
  }}
  .firm-logo {{
    height: 56px;
    width: auto;
    margin-bottom: 6px;
  }}
  .firm-address {{ color: #666; font-size: 8pt; margin-top: 2px; }}
  .firm-rep {{ font-weight: 400; margin-top: 2px; font-size: 9pt; color: #1a1a1a; }}

  /* ===== Price summary (top banner) ===== */
  .price-summary {{
    display: flex;
    gap: 8px;
    margin-bottom: 12px;
  }}
  .hero {{
    flex: 1.55;
    background: #fff;
    color: #1a1a1a;
    border: 1px solid #e4e4e4;
    border-left: 4px solid #b71c1c;
    padding: 10px 22px;
    display: flex;
    flex-direction: column;
    justify-content: center;
  }}
  .hero-label-en {{
    font-family: "Inter", sans-serif;
    font-size: 7pt;
    color: #b71c1c;
    letter-spacing: 0.3em;
    font-weight: 600;
    margin-bottom: 2px;
  }}
  .hero-label {{
    font-size: 9pt;
    color: #666;
    letter-spacing: 0.15em;
    margin-bottom: 6px;
  }}
  .hero-value {{
    font-family: "Inter", sans-serif;
    font-size: 30pt;
    font-weight: 600;
    line-height: 1;
    letter-spacing: -0.02em;
    text-align: right;
    color: #1a1a1a;
  }}
  .hero-yen {{
    font-size: 13pt;
    margin-left: 4px;
    font-weight: 300;
    color: #999;
  }}
  .hero-tax {{
    font-size: 7pt;
    color: #999;
    text-align: right;
    margin-top: 2px;
    letter-spacing: 0.1em;
  }}
  /* 定価/確定価格の対比表示 */
  .price-compare {{
    display: flex;
    flex-direction: column;
    align-items: flex-end;
    gap: 0;
  }}
  .price-list {{
    font-family: "Inter", sans-serif;
    font-size: 8pt;
    color: #aaa;
    text-decoration: line-through;
    font-weight: 400;
    line-height: 1.2;
  }}
  .price-final {{
    font-family: "Inter", sans-serif;
    font-size: 26pt;
    font-weight: 700;
    line-height: 1;
    letter-spacing: -0.02em;
    color: #1a1a1a;
  }}
  .price-final-yen {{
    font-size: 11pt;
    margin-left: 4px;
    font-weight: 300;
    color: #999;
  }}
  .sub-compare-list {{
    font-family: "Inter", sans-serif;
    font-size: 7pt;
    color: #aaa;
    text-decoration: line-through;
    text-align: right;
    margin-bottom: 0;
    font-weight: 400;
    line-height: 1.2;
  }}
  .sub-compare-final {{
    color: #1a1a1a !important;
  }}

  /* Sub cards (right column, stacked) */
  .sub-cards {{
    flex: 1;
    display: flex;
    flex-direction: column;
    gap: 6px;
  }}
  .sub-card {{
    flex: 1;
    background: #fff;
    border: 1px solid #e4e4e4;
    border-left: 4px solid #b71c1c;
    padding: 6px 14px;
    display: flex;
    flex-direction: column;
    justify-content: center;
  }}
  .sub-label {{
    font-size: 8pt;
    color: #666;
    margin-bottom: 2px;
    letter-spacing: 0.05em;
  }}
  .sub-value {{
    font-family: "Inter", sans-serif;
    font-size: 14pt;
    font-weight: 600;
    text-align: right;
    line-height: 1;
    color: #1a1a1a;
  }}
  .sub-value .yen-unit {{
    font-size: 8pt;
    color: #888;
    font-weight: 400;
    margin-left: 3px;
  }}
  .sub-note {{
    font-size: 6.5pt;
    color: #999;
    text-align: right;
    margin-top: 2px;
  }}

  /* ===== Section heading ===== */
  .section {{ margin-bottom: 9px; page-break-inside: avoid; }}
  .section-head {{
    display: flex;
    align-items: baseline;
    gap: 12px;
    margin-bottom: 5px;
    padding-bottom: 3px;
    border-bottom: 1px solid #1a1a1a;
  }}
  .section-num {{
    font-family: "Inter", sans-serif;
    font-size: 7pt;
    color: #b71c1c;
    font-weight: 600;
    letter-spacing: 0.3em;
  }}
  .section-title {{
    font-family: "Noto Serif JP", serif;
    font-size: 11pt;
    font-weight: 500;
    margin: 0;
    letter-spacing: 0.05em;
    color: #1a1a1a;
  }}

  /* ===== 算定内訳 ===== */
  .breakdown {{
    width: 100%;
    border-collapse: collapse;
    font-size: 8.5pt;
  }}
  .breakdown th, .breakdown td {{
    padding: 5px 10px;
    text-align: left;
  }}
  .breakdown th {{
    color: #999;
    font-size: 7.5pt;
    font-weight: 400;
    letter-spacing: 0.1em;
    border-bottom: 1px solid #1a1a1a;
  }}
  .breakdown td {{ border-bottom: 1px solid #ececec; color: #2d2d2d; }}
  .breakdown .num {{
    font-family: "Inter", sans-serif;
    text-align: right;
    font-weight: 400;
  }}
  .breakdown tr.total td {{
    border-top: 2px solid #1a1a1a;
    border-bottom: none;
    font-weight: 500;
    padding-top: 7px;
    color: #1a1a1a;
  }}
  .breakdown tr.total .num {{
    color: #b71c1c;
    font-size: 10.5pt;
    font-weight: 600;
  }}

  /* ===== 含まれる業務 ===== */
  .scope-grid {{
    display: flex;
    gap: 16px;
  }}
  .scope-grid > div {{
    flex: 1;
    min-width: 0;
  }}
  .scope-heading {{
    font-size: 8pt;
    color: #999;
    margin-bottom: 5px;
    letter-spacing: 0.05em;
    font-weight: 400;
  }}
  .scope-list {{
    list-style: none;
    padding: 0;
    margin: 0;
    font-size: 8pt;
    line-height: 1.45;
  }}
  .scope-list li {{
    margin-bottom: 5px;
    padding-left: 14px;
    position: relative;
    display: block;
  }}
  .scope-list .check {{
    position: absolute;
    left: 0;
    top: 1px;
    color: #b71c1c;
    font-weight: 500;
  }}
  .scope-list .scope-title {{
    font-weight: 500;
    color: #2d2d2d;
  }}
  .scope-list .scope-sub {{
    color: #888;
    font-size: 7.5pt;
    margin-top: 1px;
    line-height: 1.4;
    font-weight: 400;
  }}
  .excluded-list {{
    list-style: none;
    padding: 0;
    margin: 0;
    font-size: 8pt;
  }}
  .excluded-list li {{
    display: flex;
    justify-content: space-between;
    gap: 10px;
    align-items: baseline;
    padding: 4px 0;
    border-bottom: 1px dotted #ddd;
  }}
  .excluded-list .label {{
    color: #2d2d2d;
    min-width: 0;
    font-weight: 400;
  }}
  .excluded-list .price {{
    font-family: "Inter", sans-serif;
    color: #999;
    font-size: 7.5pt;
    white-space: nowrap;
    text-align: right;
    font-weight: 400;
  }}

  /* ===== 見積条件 ===== */
  .conditions {{
    width: 100%;
    border-collapse: collapse;
    font-size: 8pt;
  }}
  .conditions th {{
    width: 70px;
    background: #f6f6f6;
    color: #666;
    font-weight: 400;
    padding: 4px 10px;
    text-align: left;
    letter-spacing: 0.1em;
    border-bottom: 1px solid #fff;
    vertical-align: top;
  }}
  .conditions td {{
    padding: 4px 10px;
    border-bottom: 1px solid #ececec;
    color: #2d2d2d;
    font-weight: 400;
  }}

  .notes {{ margin-top: 6px; page-break-inside: avoid; }}
  .notes h3 {{
    font-size: 7.5pt;
    margin: 0 0 2px 0;
    color: #b71c1c;
    letter-spacing: 0.1em;
    font-weight: 500;
  }}
  .notes p {{
    font-size: 7.5pt;
    margin: 0;
    padding: 4px 10px;
    background: #f6f6f6;
    border-left: 3px solid #b71c1c;
    line-height: 1.45;
    color: #555;
  }}

  .footer-stamp {{
    text-align: right;
    margin-top: 3px;
    font-size: 6pt;
    color: #bbb;
    letter-spacing: 0.2em;
  }}
</style>
</head>
<body>

<header class="doc-header">
  <div>
    <h1 class="doc-title">御 見 積 書</h1>
    <div class="doc-title-en">QUOTATION FOR TAX ADVISORY SERVICES</div>
  </div>
  <div class="doc-meta">
    {estimate_no_html}
    <div class="meta-row"><span class="meta-label">発行日</span><span class="meta-value">{info.issue_date.strftime('%Y / %m / %d')}</span></div>
    <div class="meta-row"><span class="meta-label">有効期限</span><span class="meta-value">{valid_until.strftime('%Y / %m / %d')}</span></div>
  </div>
</header>

<section class="addressee">
  <div class="addressee-left">
    <div class="client-name">{esc(info.client_name)}　御中</div>
    <div class="addressee-msg">下記のとおり御見積申し上げます。何卒ご検討の程よろしくお願い申し上げます。</div>
  </div>
  <div class="firm-info">
    {f'<img src="{logo_uri}" class="firm-logo" alt="御堂筋税理士法人">' if logo_uri else ''}
    <div class="firm-address">{FIRM_ADDRESS}</div>
    <div class="firm-rep">{FIRM_REPRESENTATIVE}</div>
  </div>
</section>

<div class="price-summary">
  <div class="hero">
    <div class="hero-label-en">ANNUAL TOTAL</div>
    <div class="hero-label">年間総額（税抜）</div>
    {annual_html}
    <div class="hero-tax">＋消費税</div>
  </div>
  <div class="sub-cards">
    <div class="sub-card">
      <div class="sub-label">月額顧問報酬（税抜）</div>
      {monthly_html}
    </div>
    <div class="sub-card">
      <div class="sub-label">決算申告料（税抜）</div>
      {closing_html}
      <div class="sub-note">{closing_note}</div>
    </div>
  </div>
</div>

<section class="section">
  <div class="section-head">
    <span class="section-num">01</span>
    <h2 class="section-title">算定内訳</h2>
  </div>
  <table class="breakdown">
    <thead>
      <tr>
        <th>算定基準要素</th>
        <th class="num">入力値（千円）</th>
        <th class="num">月額（円）</th>
      </tr>
    </thead>
    <tbody>
      <tr>
        <td>① 売上高基準（{esc(result.industry)}）</td>
        <td class="num">{_fmt_yen(result.sales_yen // 1000)}</td>
        <td class="num">{_fmt_yen(result.fee_sales)}</td>
      </tr>
      <tr>
        <td>② 総資産基準</td>
        <td class="num">{_fmt_yen(result.asset_yen // 1000)}</td>
        <td class="num">{_fmt_yen(result.fee_asset)}</td>
      </tr>
      <tr>
        <td>③ 個人換算所得基準（経常利益＋役員報酬）</td>
        <td class="num">{_fmt_yen(result.income_yen // 1000)}</td>
        <td class="num">{_fmt_yen(result.fee_income)}</td>
      </tr>
      <tr class="total">
        <td colspan="2">合計（月額顧問報酬）</td>
        <td class="num">¥{_fmt_yen(result.monthly_total)}</td>
      </tr>
    </tbody>
  </table>
</section>

<section class="section">
  <div class="section-head">
    <span class="section-num">02</span>
    <h2 class="section-title">業務範囲</h2>
  </div>
  <div class="scope-grid">
    <div>
      <div class="scope-heading">御見積に含まれる業務</div>
      <ul class="scope-list">
        {included_html}
      </ul>
    </div>
    <div>
      <div class="scope-heading">別途お見積りとなる業務</div>
      <ul class="excluded-list">
        {excluded_html}
      </ul>
    </div>
  </div>
</section>

<section class="section">
  <div class="section-head">
    <span class="section-num">03</span>
    <h2 class="section-title">御見積条件</h2>
  </div>
  <table class="conditions">
    <tr><th>金　額</th><td>上記金額はすべて税抜表示です。別途消費税を申し受けます。</td></tr>
    <tr><th>支払方法</th><td>口座振替（月次：当月分を当月口座振替指定日／決算：決算報告後の直近指定日）</td></tr>
    <tr><th>契約期間</th><td>{esc(info.contract_term)}</td></tr>
    <tr><th>有効期限</th><td>本見積書の有効期限は{valid_until.year}年{valid_until.month}月{valid_until.day}日までとさせていただきます。</td></tr>
    <tr><th>そ の 他</th><td>本見積は当法人標準の税務顧問契約書に基づきます。実費（交通費・関係書類謄写費等）は別途ご負担いただきます。</td></tr>
  </table>
</section>

{notes_html}


</body>
</html>
"""


def _find_edge_or_none() -> Optional[str]:
    for p in EDGE_CANDIDATES:
        if Path(p).exists():
            return p
    return None


def _build_via_edge(edge: str, html_str: str) -> bytes:
    with tempfile.TemporaryDirectory() as td:
        tdp = Path(td)
        html_path = tdp / "estimate.html"
        pdf_path = tdp / "estimate.pdf"
        html_path.write_text(html_str, encoding="utf-8")
        cmd = [
            edge,
            f"--user-data-dir={tdp / 'udata'}",
            "--headless=new",
            "--disable-gpu",
            "--no-pdf-header-footer",
            f"--print-to-pdf={pdf_path}",
            f"file:///{html_path.as_posix()}",
        ]
        result_proc = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
        if not pdf_path.exists():
            raise RuntimeError(f"Edge PDF生成失敗: {result_proc.stderr}")
        return pdf_path.read_bytes()


def _build_via_weasyprint(html_str: str) -> bytes:
    """WeasyPrintでPDF化（Linux/Streamlit Cloud用）。"""
    from weasyprint import HTML  # 遅延import（ローカルWindowsでは未インストールでOK）
    return HTML(string=html_str).write_pdf()


def build_estimate_pdf(
    result: FeeResult, info: EstimateInfo, edge_path: Optional[str] = None
) -> bytes:
    """HTML → PDF。Edge優先、なければWeasyPrintにフォールバック。

    環境変数 PDF_BACKEND で強制指定可: 'edge' or 'weasyprint'
    """
    html_str = build_estimate_html(result, info)
    backend = os.environ.get("PDF_BACKEND", "auto")

    if backend == "weasyprint":
        return _build_via_weasyprint(html_str)
    if backend == "edge":
        return _build_via_edge(edge_path or _find_edge(), html_str)

    # auto: Edgeあれば使う、なければWeasyPrint
    edge = edge_path or _find_edge_or_none()
    if edge:
        return _build_via_edge(edge, html_str)
    return _build_via_weasyprint(html_str)
