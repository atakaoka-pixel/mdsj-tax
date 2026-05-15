# 税務顧問報酬見積りツール 起動スクリプト
# 使い方: このファイルを右クリック → 「PowerShellで実行」
#        または PowerShell で  .\run.ps1
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

if (-not (Test-Path ".\.venv\Scripts\streamlit.exe")) {
    Write-Host "初回セットアップ: 仮想環境を作成します..." -ForegroundColor Yellow
    py -3 -m venv .venv
    .\.venv\Scripts\python.exe -m pip install --upgrade pip
    .\.venv\Scripts\python.exe -m pip install -r requirements.txt
}

if (-not (Test-Path ".\.env")) {
    Copy-Item .env.example .env
    Write-Host ".env を作成しました。ANTHROPIC_API_KEY を設定してください。" -ForegroundColor Yellow
    notepad .env
}

.\.venv\Scripts\streamlit.exe run app.py
