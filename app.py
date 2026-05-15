"""税務顧問報酬見積りツール（Streamlit版）。

環境変数 / Streamlit secrets:
  WEB_MODE=1            : 公開Webデプロイ時に1。決算書PDF読取機能を非表示
  APP_PASSWORD=xxx      : 設定すると起動時にパスワード入力が必須になる
  ANTHROPIC_API_KEY=... : 決算書PDF読取に必要。WEB_MODE=1なら不要
"""
from __future__ import annotations

import os
from datetime import date
from pathlib import Path

import pandas as pd
import streamlit as st
from dotenv import load_dotenv

from estimate_pdf import EstimateInfo, build_estimate_pdf
from fee_calculator import (
    INDUSTRY_COLS,
    calculate_fee,
    format_range,
    load_master,
)

load_dotenv()


def _get_config(key: str, default: str = "") -> str:
    """環境変数 → Streamlit secrets の順に取得。"""
    val = os.environ.get(key, "")
    if val:
        return val
    try:
        return str(st.secrets[key])  # type: ignore[index]
    except (KeyError, FileNotFoundError, Exception):
        return default


WEB_MODE = _get_config("WEB_MODE", "0") in ("1", "true", "True", "yes")
APP_PASSWORD = _get_config("APP_PASSWORD", "")

# PDF読取機能はWEB_MODEではimportしない（依存重い+APIキー不要にするため）
if not WEB_MODE:
    from pdf_extractor import Extracted, extract_from_pdf  # noqa: F401

BASE_DIR = Path(__file__).parent
MASTER_CSV = BASE_DIR / "master.csv"

st.set_page_config(
    page_title="税務顧問報酬見積りツール",
    page_icon=None,
    layout="wide",
)


def _check_password() -> None:
    """APP_PASSWORDが設定されていれば、認証されるまでアプリを止める。"""
    if not APP_PASSWORD:
        return  # パスワード未設定なら素通り（社内LANやローカル用）
    if st.session_state.get("_authenticated"):
        return

    st.markdown("### ログイン")
    st.caption("社内共有用のパスワードを入力してください。")
    pw = st.text_input("パスワード", type="password", key="_pw_input", label_visibility="collapsed")
    if st.button("ログイン", type="primary"):
        if pw == APP_PASSWORD:
            st.session_state["_authenticated"] = True
            st.rerun()
        else:
            st.error("パスワードが違います。")
    st.stop()


_check_password()

st.markdown(
    """
    <style>
    :root {
      --main-black: #1a1a1a;
      --accent-red: #b71c1c;
    }
    .block-container { padding-top: 1.5rem; }
    h1.app-title {
      font-family: 'Noto Serif JP', serif;
      font-weight: 700;
      font-size: 1.8rem;
      letter-spacing: 0.05em;
      border-bottom: 4px solid #1a1a1a;
      padding-bottom: 10px;
      margin-bottom: 1.5rem;
    }
    [data-testid="stSidebar"] {
      background-color: #1a1a1a;
    }
    [data-testid="stSidebar"] * { color: #fff !important; }
    [data-testid="stSidebar"] .stTextInput input,
    [data-testid="stSidebar"] .stNumberInput input,
    [data-testid="stSidebar"] .stSelectbox div[data-baseweb="select"] > div {
      background-color: #2d2d2d !important;
      color: #fff !important;
      border-radius: 0 !important;
    }
    [data-testid="stSidebar"] h2 {
      color: #fff !important;
      border-bottom: 2px solid #b71c1c;
      padding-bottom: 8px;
      margin-bottom: 1rem;
    }
    .fee-summary {
      border-left: 5px solid #b71c1c;
      background: white;
      padding: 20px 24px;
      box-shadow: 0 2px 8px rgba(0,0,0,0.05);
      margin-bottom: 16px;
    }
    .fee-label { font-size: 0.85rem; color: #666; letter-spacing: 0.05em; }
    .fee-value {
      font-family: 'Roboto', sans-serif;
      font-size: 2.2rem;
      font-weight: 700;
      color: #1a1a1a;
      text-align: right;
      line-height: 1.1;
    }
    .fee-unit { font-size: 1rem; color: #666; margin-left: 4px; }
    .annual-box {
      background-color: #1a1a1a;
      color: #fff;
      padding: 18px 24px;
      display: flex;
      justify-content: space-between;
      align-items: center;
      margin-top: 8px;
      border-right: 5px solid #b71c1c;
    }
    .annual-val {
      font-family: 'Roboto', sans-serif;
      font-size: 1.6rem;
      font-weight: 700;
    }
    .stButton > button[kind="primary"] {
      background-color: #b71c1c !important;
      border-radius: 0 !important;
      border: none !important;
      letter-spacing: 0.1em;
      font-weight: 700;
      padding: 12px 24px;
    }
    .stButton > button[kind="primary"]:hover { background-color: #d32f2f !important; }
    </style>
    """,
    unsafe_allow_html=True,
)


@st.cache_data
def get_master() -> pd.DataFrame:
    return load_master(MASTER_CSV)


def init_state():
    defaults = {
        "industry": "",
        "sales_sen": 0,
        "profit_sen": 0,
        "salary_sen": 0,
        "asset_sen": 0,
        "extracted": None,
        "result": None,
    }
    for k, v in defaults.items():
        st.session_state.setdefault(k, v)


def apply_extracted(ex: Extracted):
    """PDF抽出結果をフォームに反映（円→千円）。"""
    if ex.sales is not None:
        st.session_state["sales_sen"] = ex.sales // 1000
    if ex.ordinary_profit is not None:
        st.session_state["profit_sen"] = ex.ordinary_profit // 1000
    if ex.executive_salary is not None:
        st.session_state["salary_sen"] = ex.executive_salary // 1000
    if ex.total_assets is not None:
        st.session_state["asset_sen"] = ex.total_assets // 1000
    if ex.industry:
        st.session_state["industry"] = ex.industry


def sidebar():
    with st.sidebar:
        st.markdown("## 算定条件入力")

        st.selectbox(
            "業種区分　*",
            options=[""] + list(INDUSTRY_COLS.keys()),
            key="industry",
            format_func=lambda x: "選択してください" if x == "" else x,
        )
        st.number_input("売上高（千円）", min_value=0, step=1000, key="sales_sen")
        st.number_input("経常利益（千円）", step=1000, key="profit_sen")
        st.number_input("役員報酬（千円）", min_value=0, step=1000, key="salary_sen")
        st.number_input("総資産（千円）", min_value=0, step=1000, key="asset_sen")

        calc_clicked = st.button("お見積りを計算", type="primary", use_container_width=True)

        st.caption("※各数値は千円単位で入力してください")

        # 決算書PDF自動読取（ローカル版限定）
        if not WEB_MODE:
            st.divider()
            st.markdown("### 決算書PDFから自動入力")
            pdf = st.file_uploader("決算書PDFをアップロード", type=["pdf"], label_visibility="collapsed")
            if pdf is not None:
                if st.button("PDFから読み取る", use_container_width=True):
                    if not os.environ.get("ANTHROPIC_API_KEY"):
                        st.error("ANTHROPIC_API_KEY が未設定です。.env を確認してください。")
                    else:
                        with st.spinner("Claudeで読み取り中…"):
                            try:
                                ex = extract_from_pdf(pdf.read())
                                st.session_state["extracted"] = ex
                                apply_extracted(ex)
                                st.success("読み取り完了。各欄をご確認ください。")
                                st.rerun()
                            except Exception as e:
                                st.error(f"読み取り失敗: {e}")

    return calc_clicked


def render_result(result, df: pd.DataFrame):
    tab1, tab2, tab3 = st.tabs(["PROPOSAL", "DETAILS", "PRICE LIST"])

    fmt = lambda n: f"{int(n):,}"

    with tab1:
        c1, c2 = st.columns(2)
        with c1:
            st.markdown(
                f'<div class="fee-summary"><div class="fee-label">月額顧問報酬（税抜）</div>'
                f'<div class="fee-value">{fmt(result.monthly_total)}<span class="fee-unit">円</span></div></div>',
                unsafe_allow_html=True,
            )
        with c2:
            st.markdown(
                f'<div class="fee-summary"><div class="fee-label">決算申告料（税抜）</div>'
                f'<div class="fee-value">{fmt(result.closing_fee)}<span class="fee-unit">円</span></div>'
                f'<div style="text-align:right;color:#888;font-size:0.8rem;margin-top:4px;">※月額報酬の5ヶ月分</div></div>',
                unsafe_allow_html=True,
            )

        st.markdown(
            f'<div class="annual-box"><span>年間総額</span>'
            f'<span class="annual-val">{fmt(result.annual_total)} <span style="font-size:0.9rem;font-weight:400;">円</span></span></div>',
            unsafe_allow_html=True,
        )

        st.markdown("##### 　")
        col_in, col_out = st.columns(2)
        with col_in:
            st.markdown("##### 見積りに含まれるもの")
            for x in [
                "経理業務の電話等による相談と税務アドバイス",
                "月次監査による経営状況や課題共有",
                "決算3か月前からの決算予測と納税予測",
                "税額確定に基づく決算書・申告書作成",
                "法人税・消費税・地方税申告",
                "決算書分析と決算報告の実施",
                "予定申告・届出関係",
            ]:
                st.markdown(f"- {x}")
        with col_out:
            st.markdown("##### 別途報酬となるもの")
            for x in [
                "税務調査対応、意見聴取対応",
                "月次決算代行、システム利用料",
                "グループ通算制度・連結決算",
                "年末調整、法定調書合計表、償却資産税",
            ]:
                st.markdown(f"- {x}")

    with tab2:
        st.markdown("#### 算定内訳詳細")
        detail_df = pd.DataFrame(
            [
                {
                    "算定基準要素": "① 売上高基準",
                    "入力値（千円）": fmt(result.sales_yen // 1000),
                    "算出額（月額）": fmt(result.fee_sales) + " 円",
                },
                {
                    "算定基準要素": "② 総資産基準",
                    "入力値（千円）": fmt(result.asset_yen // 1000),
                    "算出額（月額）": fmt(result.fee_asset) + " 円",
                },
                {
                    "算定基準要素": "③ 所得基準 (利益+報酬)",
                    "入力値（千円）": fmt(result.income_yen // 1000),
                    "算出額（月額）": fmt(result.fee_income) + " 円",
                },
            ]
        )
        st.dataframe(detail_df, hide_index=True, use_container_width=True)
        st.markdown(
            f"**合計月額：<span style='color:#b71c1c;font-size:1.3rem;'>{fmt(result.monthly_total)} 円</span>**",
            unsafe_allow_html=True,
        )

    with tab3:
        st.markdown(f"**適用業種：{result.industry}**")
        s_min_col, s_max_col = INDUSTRY_COLS[result.industry]
        rows = []
        for _, row in df.iterrows():
            rows.append(
                {
                    "売上高": format_range(row[s_min_col], row[s_max_col]),
                    "総資産": format_range(row["asset_min"], row["asset_max"]),
                    "個人換算所得": format_range(row["income_min"], row["income_max"]),
                    "基準額": f"{int(row['fee']):,} 円",
                }
            )
        st.dataframe(pd.DataFrame(rows), hide_index=True, use_container_width=True)


def render_estimate_section(result):
    """お客様送付用の見積書（A4縦PDF）生成セクション。"""
    st.markdown("---")
    st.markdown("### お客様送付用 見積書（A4縦 PDF）")
    st.caption("以下を入力して『見積書を作成』を押すと、A4縦1ページのPDFをダウンロードできます。")

    with st.form("estimate_form"):
        c1, c2 = st.columns([2, 1])
        with c1:
            client_name = st.text_input(
                "宛先（会社名）",
                value=st.session_state.get("est_client_name", ""),
                placeholder="株式会社●●●●",
            )
        with c2:
            issue_date = st.date_input("発行日", value=date.today())

        c3, c4, c5 = st.columns([1, 1, 1])
        with c3:
            estimate_no = st.text_input(
                "見積番号（任意）",
                value=st.session_state.get("est_no", ""),
                placeholder="Q-2026-0513-001",
            )
        with c4:
            valid_days = st.number_input("有効期限（日数）", min_value=1, max_value=180, value=30)
        with c5:
            person_in_charge = st.text_input(
                "担当者名（任意）",
                value=st.session_state.get("est_person", ""),
                placeholder="例：高岡 亜子",
                help="入力すると見積書末尾の署名が「担当 〇〇」になります。空欄なら「代表社員 才木 正之」",
            )

        contract_term = st.text_input(
            "契約期間表記",
            value=st.session_state.get("est_term", "1事業年度（自動更新）"),
        )

        st.markdown("##### 確定見積金額（値引き等を反映）")
        st.caption("自動算定額からの値引きをする場合、ここで金額を編集してください。変更がなければそのままでOK。")
        cc1, cc2 = st.columns(2)
        with cc1:
            final_monthly = st.number_input(
                "確定 月額顧問報酬（円）",
                min_value=0,
                value=int(result.monthly_total),
                step=1000,
                help=f"自動算定額: ¥{result.monthly_total:,}",
            )
        with cc2:
            final_closing = st.number_input(
                "確定 決算申告料（円）",
                min_value=0,
                value=int(result.closing_fee),
                step=1000,
                help=f"自動算定額: ¥{result.closing_fee:,}（月額×5）",
            )
        final_annual_preview = int(final_monthly) * 12 + int(final_closing)
        diff = final_annual_preview - result.annual_total
        if diff == 0:
            st.markdown(
                f"確定年間総額：**¥{final_annual_preview:,}**（自動算定と同額）"
            )
        else:
            sign = "値引き" if diff < 0 else "上乗せ"
            st.markdown(
                f"確定年間総額：**¥{final_annual_preview:,}**　"
                f"<span style='color:#b71c1c;'>（{sign} ¥{abs(diff):,}）</span>",
                unsafe_allow_html=True,
            )

        notes = st.text_area(
            "備考（任意）",
            value=st.session_state.get("est_notes", ""),
            placeholder="例：本見積は2026年5月時点での御社決算情報に基づき算定したものです。",
            height=70,
        )

        submitted = st.form_submit_button("見積書を作成", type="primary")

    if submitted:
        if not client_name.strip():
            st.error("宛先（会社名）を入力してください。")
            return
        st.session_state["est_client_name"] = client_name
        st.session_state["est_no"] = estimate_no
        st.session_state["est_term"] = contract_term
        st.session_state["est_notes"] = notes
        st.session_state["est_person"] = person_in_charge

        # 自動算定値と同じなら None を渡して「値引きなし」として処理
        fm = int(final_monthly) if int(final_monthly) != result.monthly_total else None
        fc = int(final_closing) if int(final_closing) != result.closing_fee else None

        info = EstimateInfo(
            client_name=client_name.strip(),
            issue_date=issue_date,
            estimate_no=estimate_no.strip(),
            valid_days=int(valid_days),
            contract_term=contract_term.strip() or "1事業年度（自動更新）",
            notes=notes.strip(),
            final_monthly=fm,
            final_closing=fc,
            person_in_charge=person_in_charge.strip(),
        )
        try:
            with st.spinner("見積書PDFを生成中…"):
                data = build_estimate_pdf(result, info)
            safe_name = client_name.replace("/", "_").replace("\\", "_").strip()
            filename = f"御見積書_{safe_name}_{issue_date.strftime('%Y%m%d')}.pdf"
            st.success("見積書を作成しました。下のボタンからダウンロードしてください。")
            st.download_button(
                label=f"{filename} をダウンロード",
                data=data,
                file_name=filename,
                mime="application/pdf",
                type="primary",
            )
        except Exception as e:
            st.error(f"見積書の作成に失敗しました: {e}")


def main():
    init_state()
    st.markdown('<h1 class="app-title">税務顧問報酬見積りツール</h1>', unsafe_allow_html=True)

    calc_clicked = sidebar()

    df = get_master()

    ex = st.session_state.get("extracted")
    if ex is not None:
        with st.expander("PDF抽出結果（参考）", expanded=False):
            st.json(
                {
                    "売上高": ex.sales,
                    "経常利益": ex.ordinary_profit,
                    "役員報酬": ex.executive_salary,
                    "総資産": ex.total_assets,
                    "推定業種": ex.industry,
                    "備考": ex.notes,
                }
            )

    if calc_clicked:
        if not st.session_state["industry"]:
            st.error("業種を選択してください。")
            return
        result = calculate_fee(
            df,
            industry=st.session_state["industry"],
            sales_sen=st.session_state["sales_sen"],
            profit_sen=st.session_state["profit_sen"],
            salary_sen=st.session_state["salary_sen"],
            asset_sen=st.session_state["asset_sen"],
        )
        st.session_state["result"] = result

    if st.session_state.get("result") is not None:
        render_result(st.session_state["result"], df)
        render_estimate_section(st.session_state["result"])
    else:
        if WEB_MODE:
            st.info("左サイドバーで業種・売上高・経常利益・役員報酬・総資産を入力し、「お見積りを計算」を押してください。")
        else:
            st.info("左サイドバーで条件を入力するか、決算書PDFをアップロードしてください。")


if __name__ == "__main__":
    main()
