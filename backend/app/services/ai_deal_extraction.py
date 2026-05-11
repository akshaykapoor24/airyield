from __future__ import annotations

import io
import json
import re

from fastapi import UploadFile

SYSTEM_PROMPT = """
You are an AI agent integrated into a Deals Management System.

Your task is to process airline deal PDFs uploaded by users and convert them into structured deal data.

## Step 1: Understand Create Deal Fields

Each deal consists of:

### Airline Contract Details
- airline_type → "GDS" or "LCC"
- airline_name → Extract from PDF
- contract_valid_from → Extract if available, else null (ISO date format YYYY-MM-DD)
- contract_valid_to → Extract date (ISO date format YYYY-MM-DD)

### Incentive Types (PLB ONLY)

Each deal MUST have:
- incentive_types = ["PLB"]

PLB structure inside incentive_data.PLB:
- validFrom → same as contract_valid_from
- validTo → same as contract_valid_to
- frequency → default "Yearly"
- flightType → map: "OB/IB" → "Both", "Domestic" → "Domestic", "International" → "International", default "Both"
- class → ONE of: "Economy", "Premium", "Business"
- targetCalcCols → map: "B" → "Basic", "B+YQ" → "Basic + YQ", "B+YR" → "Basic + YR", "B+YQ+YR" → "Basic + YQ +YR"
- payoutCalcCols → same as targetCalcCols
- targetBased → null
- incentiveNumPct → "Percentage"
- incentiveAmtPct → numeric value (the percentage number, e.g. 2.0 for 2%)
- cappedIncentive → null

### Remarks
- Extract all conditions, exclusions, notes from PDF
- Store as plain text in the remark field

## Step 2: CRITICAL SPLITTING RULE

A SINGLE LINE IN PDF MAY CONTAIN MULTIPLE DEALS.

Example: "2.00% (B+YQ)  2.75% (B+YQ)  3.75% (B+YQ)"
This MUST be split into 3 DIFFERENT DEALS:
1. Economy → 2.00%
2. Premium → 2.75%
3. Business → 3.75%

The order of percentages maps to: Economy → Premium → Business

DO NOT create multiple PLB rows in one deal.
ALWAYS create separate deals per class.

## Step 3: Edge Cases

1. Missing values: "0.75% - -" → Only create Economy deal (skip the dashes)
2. Same values: "3% 3% 3%" → Create 3 separate deals
3. Non-percentage values like "NET + SC 50" → Skip or set incentiveAmtPct to 0
4. Validity formats:
   - "Till further notice" → set valid_to = null
   - "Travel till 31 Dec 2026" → extract as "2026-12-31"

## Step 4: Output Format

Return a JSON object with a "deals" array:

{
  "deals": [
    {
      "airline_type": "GDS",
      "airline_name": "Air India",
      "contract_valid_from": null,
      "contract_valid_to": "2026-03-31",
      "incentive_types": ["PLB"],
      "incentive_data": {
        "PLB": {
          "validFrom": null,
          "validTo": "2026-03-31",
          "frequency": "Yearly",
          "flightType": "Both",
          "class": "Economy",
          "targetCalcCols": "Basic + YQ",
          "payoutCalcCols": "Basic + YQ",
          "incentiveNumPct": "Percentage",
          "incentiveAmtPct": 2.0,
          "targetBased": null,
          "cappedIncentive": null
        }
      },
      "remark": "Lords issuance, OB/IB till 31 Mar 2026"
    }
  ]
}

## Final Rules

- Always prioritize accuracy over assumptions
- Never merge multiple class deals into one
- Always normalize calculation fields (B → Basic, B+YQ → Basic + YQ, etc.)
- If data is missing → set null (do not guess)
- Output must be valid JSON with a top-level "deals" array
- Return ONLY the JSON object, no markdown fences or extra text
- Keep "remark" values concise — max 120 characters. Summarise key conditions only.
- Output MUST be complete and valid JSON. Do not truncate mid-object.
"""


class AIDealExtractionService:
    @staticmethod
    async def extract(file: UploadFile) -> dict:
        content = await file.read()
        await file.seek(0)

        pdf_text = AIDealExtractionService._extract_pdf_text(content, file.filename or "")

        if not pdf_text.strip():
            return {
                "deals": [],
                "file_name": file.filename or "",
                "confidence": 0.0,
                "warning": "Could not extract text from this file.",
            }

        deals = await AIDealExtractionService._call_openai(pdf_text)

        return {
            "deals": deals,
            "file_name": file.filename or "",
            "confidence": 0.9 if deals else 0.2,
            "warning": None if deals else "No deals could be extracted from this PDF.",
        }

    @staticmethod
    def _extract_pdf_text(content: bytes, filename: str) -> str:
        ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""

        if ext == "pdf":
            try:
                import fitz  # PyMuPDF
                doc = fitz.open(stream=io.BytesIO(content), filetype="pdf")
                return "\n".join(page.get_text("text") for page in doc)
            except Exception:
                return ""

        if ext in ("xlsx", "xls"):
            try:
                import openpyxl
                wb = openpyxl.load_workbook(io.BytesIO(content), data_only=True)
                lines = []
                for ws in wb.worksheets:
                    for row in ws.iter_rows(values_only=True):
                        parts = [str(c) for c in row if c is not None]
                        if parts:
                            lines.append("\t".join(parts))
                return "\n".join(lines)
            except Exception:
                return ""

        if ext in ("doc", "docx"):
            try:
                import docx
                doc = docx.Document(io.BytesIO(content))
                return "\n".join(p.text for p in doc.paragraphs if p.text.strip())
            except Exception:
                return ""

        return content.decode("utf-8", errors="ignore")

    @staticmethod
    def _repair_truncated_json(content: str) -> list[dict]:
        """Extract all complete deal objects from potentially truncated JSON."""
        # Locate the opening of the deals array
        match = re.search(r'"deals"\s*:\s*\[', content)
        if not match:
            return []

        array_content = content[match.end():]

        # Walk through characters to find the boundary of each complete object
        depth = 0
        in_string = False
        escape_next = False
        last_complete_end = -1

        for i, ch in enumerate(array_content):
            if escape_next:
                escape_next = False
                continue
            if ch == "\\" and in_string:
                escape_next = True
                continue
            if ch == '"':
                in_string = not in_string
                continue
            if in_string:
                continue
            if ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    last_complete_end = i

        if last_complete_end == -1:
            return []

        try:
            return json.loads("[" + array_content[: last_complete_end + 1] + "]")
        except json.JSONDecodeError:
            return []

    @staticmethod
    async def _call_openai(pdf_text: str) -> list[dict]:
        from openai import AsyncOpenAI
        from app.config import settings

        client = AsyncOpenAI(api_key=settings.OPENAI_API_KEY)

        # Limit input to avoid exceeding context window (keep ~8k chars for output budget)
        truncated = pdf_text[:14000]

        response = await client.chat.completions.create(
            model="gpt-4o",
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": f"Extract deals from this document text:\n\n{truncated}"},
            ],
            response_format={"type": "json_object"},
            temperature=0,
            max_tokens=16000,
        )

        finish_reason = response.choices[0].finish_reason
        raw_content = response.choices[0].message.content or "{}"

        # If the model ran out of tokens, salvage the complete deals it managed to emit
        if finish_reason == "length":
            return AIDealExtractionService._repair_truncated_json(raw_content)

        try:
            parsed = json.loads(raw_content)
        except json.JSONDecodeError:
            # Attempt repair even without a length finish reason
            return AIDealExtractionService._repair_truncated_json(raw_content)

        if isinstance(parsed, list):
            return parsed
        return parsed.get("deals", [])
