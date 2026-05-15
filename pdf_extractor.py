"""決算書PDFから売上高・経常利益・役員報酬・総資産をClaude APIで抽出する。"""
from __future__ import annotations

import base64
import json
import os
import re
from dataclasses import dataclass
from typing import Optional

from anthropic import Anthropic

MODEL = "claude-opus-4-7"  # 決算書の表構造を正確に読むためOpusを既定にする

EXTRACTION_PROMPT = """あなたは日本の決算書（貸借対照表・損益計算書）を読み取る税務アシスタントです。
添付されたPDFから以下の4項目を**円単位の整数**で抽出してください。

1. sales: 売上高（損益計算書 / 売上高）
2. ordinary_profit: 経常利益（損益計算書 / 経常利益。マイナスの場合は負の値）
3. executive_salary: 役員報酬（販管費内訳の「役員報酬」のみ。従業員給与・賞与・法定福利費は含めない）
4. total_assets: 資産合計 / 総資産（貸借対照表 / 資産の部合計）

加えて、業種を以下のいずれかから推定してください（複数該当しそうなら最も主要なもの）：
卸売業 / 小売業 / 建設業 / 製造業 / サービス業その他

返答は**必ず以下のJSONのみ**で、説明文は一切付けないでください。
値が読み取れない／自信がない場合は null にしてください。

{
  "sales": <整数 or null>,
  "ordinary_profit": <整数 or null>,
  "executive_salary": <整数 or null>,
  "total_assets": <整数 or null>,
  "industry": "卸売業" | "小売業" | "建設業" | "製造業" | "サービス業その他" | null,
  "notes": "<読み取りで迷った点や注意事項を日本語1〜2文。なければ空文字>"
}
"""


@dataclass
class Extracted:
    sales: Optional[int]
    ordinary_profit: Optional[int]
    executive_salary: Optional[int]
    total_assets: Optional[int]
    industry: Optional[str]
    notes: str
    raw: str


def extract_from_pdf(pdf_bytes: bytes, api_key: Optional[str] = None) -> Extracted:
    client = Anthropic(api_key=api_key or os.environ.get("ANTHROPIC_API_KEY"))
    b64 = base64.standard_b64encode(pdf_bytes).decode("utf-8")

    msg = client.messages.create(
        model=MODEL,
        max_tokens=2048,
        messages=[
            {
                "role": "user",
                "content": [
                    {
                        "type": "document",
                        "source": {
                            "type": "base64",
                            "media_type": "application/pdf",
                            "data": b64,
                        },
                    },
                    {"type": "text", "text": EXTRACTION_PROMPT},
                ],
            }
        ],
    )
    text = "".join(block.text for block in msg.content if block.type == "text").strip()
    data = _parse_json(text)
    return Extracted(
        sales=_to_int(data.get("sales")),
        ordinary_profit=_to_int(data.get("ordinary_profit")),
        executive_salary=_to_int(data.get("executive_salary")),
        total_assets=_to_int(data.get("total_assets")),
        industry=data.get("industry") if data.get("industry") in {
            "卸売業", "小売業", "建設業", "製造業", "サービス業その他"
        } else None,
        notes=data.get("notes", "") or "",
        raw=text,
    )


def _parse_json(text: str) -> dict:
    # コードフェンスを剥がす
    text = re.sub(r"^```(?:json)?\s*", "", text.strip())
    text = re.sub(r"\s*```$", "", text.strip())
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", text, re.DOTALL)
        if match:
            return json.loads(match.group(0))
        raise


def _to_int(v) -> Optional[int]:
    if v is None or v == "":
        return None
    if isinstance(v, (int, float)):
        return int(v)
    if isinstance(v, str):
        s = v.replace(",", "").replace("円", "").strip()
        if s in {"", "-", "null"}:
            return None
        try:
            return int(float(s))
        except ValueError:
            return None
    return None
