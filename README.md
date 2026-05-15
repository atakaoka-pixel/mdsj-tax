# 税務顧問報酬見積りツール

決算書PDFをアップロードすると Claude API が売上高・経常利益・役員報酬・総資産を読み取り、自社の料金マスタに基づいて顧問報酬を自動算定する Streamlit アプリです。

## ファイル構成

| ファイル | 役割 |
|---|---|
| `app.py` | Streamlit アプリ本体（UI） |
| `fee_calculator.py` | 料金算定ロジック（既存GAS版を移植） |
| `pdf_extractor.py` | 決算書PDFをClaude APIで読み取り |
| `master.csv` | 料金マスタ（23階層） |
| `requirements.txt` | Pythonライブラリ |
| `.env.example` | APIキー設定の雛形 |

## 起動（2回目以降）

```powershell
cd "C:\Users\高岡亜子\OneDrive - 御堂筋税理士法人\デスクトップ\AI開発\税務顧問料見積りツール"
.\.venv\Scripts\streamlit.exe run app.py
```

または `run.ps1` をダブルクリック（PowerShellで実行）。ブラウザで `http://localhost:8501` が自動で開きます。停止は PowerShell で `Ctrl+C`。

## 初回セットアップ（既に完了済みの場合は不要）

`run.ps1` を実行すれば自動でやってくれます。手動で行う場合：

```powershell
cd "C:\Users\高岡亜子\OneDrive - 御堂筋税理士法人\デスクトップ\AI開発\税務顧問料見積りツール"

# Windows標準の python は Microsoft Store ショートカットに割り当てられているため、
# 必ず py ランチャー経由で実行する
py -3 -m venv .venv

# 依存関係をインストール（venv内の python.exe を直接指定するのが確実）
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -r requirements.txt

# APIキーを設定
Copy-Item .env.example .env
notepad .env   # ANTHROPIC_API_KEY=sk-ant-... を貼り付けて保存
```

> **Note:** PowerShellでvenvの`Activate.ps1`を使う方法もありますが、実行ポリシー（ExecutionPolicy）で弾かれるケースが多いので、上記のように venv内の `streamlit.exe` を直接呼ぶ方式を推奨します。

## 使い方

1. **手入力で算定**：左サイドバーで業種を選び、売上高・経常利益・役員報酬・総資産を千円単位で入力 →「お見積りを計算」
2. **PDFから自動入力**：サイドバー下部に決算書PDFをアップロード →「PDFから読み取る」→ 各欄が自動で埋まる → 内容を確認・修正して「お見積りを計算」
3. **結果**：PROPOSAL（提案サマリ）／DETAILS（算定内訳）／PRICE LIST（料金マトリクス）の3タブで確認。ブラウザの印刷機能でPDF保存できます。

## 料金マスタの更新

`master.csv` を Excel で開いて編集 → 保存。アプリ再起動で反映されます。
（千円単位ではなく**円単位**で入力していることに注意。GASスプレッドシートと同じ値です。）

## 注意点

- 料金は GAS版の `calculateFee` ロジックをそのまま移植しています（業種別売上・総資産・所得それぞれで料金を引いて合算、決算料は月額×5、年間総額は月額×12+決算料）。
- PDF読み取りは `claude-opus-4-7` を使用。1ファイルあたり数十円程度のAPI課金が発生します。
- 抽出結果は必ず人の目で確認してから見積に使用してください（兼業や特殊な勘定科目で読み取れないケースがあります）。
- 決算書PDFはClaudeのAPIに送信されます。社外秘度の高い顧問先データを扱う場合はチームプラン契約のデータ取り扱いポリシーをご確認ください。
