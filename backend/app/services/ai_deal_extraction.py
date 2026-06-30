from __future__ import annotations

import io
import json
import re

from fastapi import UploadFile

SYSTEM_PROMPT = """
You are an AI agent integrated into a Deals Management System.
Your task is to process airline deal PDFs uploaded by users and convert them into structured deal data.

## Deal Fields

Each deal object has:
- airline_type  → "GDS" or "LCC"
- airline_name  → full airline name from the document
- iata_commission → the IATA commission percentage for this airline, as a plain number
                    (e.g. 5 for "5%"), taken from an "IATA Commission" / "IATA %" column
                    if present; otherwise null. This is the agent's standard IATA
                    commission, separate from the PLB incentive %.
- contract_valid_from → null (caller supplies this; set to null always)
- contract_valid_to   → ISO date "YYYY-MM-DD" extracted from the document, or null
- incentive_types = ["PLB"]
- incentive_data.PLB  → object with all PLB fields (see schema below)
- remark → concise plain-text note (max 120 chars)

## PLB Field Schema

```
PLB: {
  validFrom:           null,               # always null — caller fills this
  validTo:             "YYYY-MM-DD"|null,  # from document
  frequency:           "Yearly",           # default; change only if document says otherwise
  flightType:          "Both"|"International"|"Domestic",
  class:               "Economy"|"Premium"|"Business",
  targetCalcCols:      "Basic"|"Basic + YQ"|"Basic + YR"|"Basic + YQ +YR",
  payoutCalcCols:      same as targetCalcCols,
  targetBased:         "Amount Based",     # a flat commission % is an amount-based payout
  amountBasedType:     "Fixed",            # Fixed (not slab) — the % applies directly
  baseTargetAmount:    null,
  segmentBasedType:    null,
  baseTargetSegments:  null,
  incentiveNumPct:     "Percentage",       # always "Percentage" for PLB commissions
  incentiveAmtPct:     <number>,           # the numeric % value, e.g. 2.0 for "2%"
  cappedIncentive:     null
}
```

## PDF Format Recognition

You will receive text from one of these supplier PDF formats. Identify the format and parse accordingly.

### Format A — Consolidator Commission Table (e.g. Akbar Travels)
Column order: AIRLINE | Code | IATA | ECONOMY | PEY | BUS/FRST | REMARKS
- ECONOMY column → class = "Economy"
- PEY column     → class = "Premium"
- BUS/FRST column → class = "Business"
- Commission format: "1.5% BF" → incentiveAmtPct=1.5, targetCalcCols="Basic"
- Commission format: "3% BF" → incentiveAmtPct=3.0, targetCalcCols="Basic"
- Mixed variants: "1.25%-STD-(B+YQ), 1.5%(B+YQ)-FLEX+" → use FIRST value: 1.25%, B+YQ
- Dash "-" or "NIL" in a column → skip that class (do NOT create a deal for it)
- Validity: parse from REMARKS cell (e.g. "Travel Till 31 DEC 2026" → valid_to="2026-12-31")
- flightType: derive from REMARKS if mentioned, else default "Both"

### Format B — B2B Airline Deal Sheet (Cabin Type column)
Column order: Airline Name | Airline Code | Cabin Type | Commission | Applicable on | Travel Validity | Remarks
- Cabin Type "Eco" / "Economy"         → class = "Economy"
- Cabin Type "Prem Eco" / "Premium"    → class = "Premium"
- Cabin Type "Bizz/First" / "Business" → class = "Business"
- Commission: "0.89%"  → incentiveAmtPct=0.89
- "Applicable on" column → targetCalcCols and payoutCalcCols
  - "Base Fare + YQ" → "Basic + YQ"
  - "Base Fare + YR" → "Basic + YR"
  - "Base Fare"      → "Basic"
- Travel Validity: "31 Dec'2026" → valid_to="2026-12-31"; "Open" → null
- Section header ":: Domestic Air ::"       → flightType="Domestic" for all rows below until next section
- Section header ":: International Air ::"  → flightType="International" for all rows below

### Format C — Lords Deal Sheet (ECO / P.ECOM / BUS columns with VALID ON)
Column order: AIRLINE | AIRLINE CODE | ECO | P.ECOM | BUS | VALID ON | VALIDITY | REMARKS
- ECO column    → class = "Economy"
- P.ECOM column → class = "Premium"
- BUS column    → class = "Business"
- Commission format: "2.00% (B+YQ)" → incentiveAmtPct=2.0; extract calc spec from parentheses
- VALID ON column: "B+YQ" → targetCalcCols="Basic + YQ"; "B" → "Basic"
  (VALID ON overrides any calc spec found in the commission cell)
- VALIDITY column: parse date + flightType
  - "OB/IB till 31 Mar 2026"           → valid_to="2026-03-31", flightType="Both"
  - "OB 1Apr 26 / IB till 31 Mar 2027" → valid_to="2027-03-31", flightType="Both"
- Dash "-" or missing value in ECO/P.ECOM/BUS → skip that class

## Calculation Field Normalization

ALWAYS normalize these values (case-insensitive match):
- "B" / "BF" / "Base Fare" / "Basic"   → "Basic"
- "B+YQ" / "BF+YQ" / "Base Fare + YQ" → "Basic + YQ"
- "B+YR" / "BF+YR" / "Base Fare + YR" → "Basic + YR"
- "B+YQ+YR"                            → "Basic + YQ +YR"

## Validity Date Normalization

- "OB/IB till 31 Mar 2026"             → "2026-03-31"
- "Travel Till 31 DEC 2026"            → "2026-12-31"
- "31 Dec'2026" / "31st Dec 2026"      → "2026-12-31"
- "31st Mar'26" / "31 Mar 2026"        → "2026-03-31"
- "IATA Commission valid for Sales till 31st Mar'26 only" → "2026-03-31"
- "Open" / "Till Further Notice" / "till further notice" → null

## Flight Type Normalization

- "OB/IB"                  → "Both"
- "International" / "INTL" → "International"
- "Domestic" / "DOM"       → "Domestic"
- Not specified             → "Both"

## CRITICAL SPLITTING RULE

Each airline row with multiple class columns MUST become SEPARATE deals — one per class.

Example row: AIR INDIA | AI | NIL | 2.00%(B+YQ) | 2.75%(B+YQ) | 3.75%(B+YQ) | OB/IB | OB/IB till 31 Mar 2026
→ Creates 3 deals:
  Deal 1: airline_name="Air India", class="Economy",  incentiveAmtPct=2.00, targetCalcCols="Basic + YQ"
  Deal 2: airline_name="Air India", class="Premium",  incentiveAmtPct=2.75, targetCalcCols="Basic + YQ"
  Deal 3: airline_name="Air India", class="Business", incentiveAmtPct=3.75, targetCalcCols="Basic + YQ"

Example row (dash = skip): AIR INDIA (S&T) | AI | 0.75%(B+YQ) | - | - | B+YQ | OB/IB till 31 Mar 2026
→ Creates 1 deal: class="Economy", incentiveAmtPct=0.75

## Edge Cases

1. Same value across all classes: "3% 3% 3%" → 3 separate deals (Economy, Premium, Business)
2. Non-percentage cell "NET + SC 50" or "NIL" → skip that class (set to 0 only if no other option)
3. Commission cell "0.75% - -" → Economy=0.75%, skip Premium and Business
4. Airline Code "(XO SALE)" annotations → ignore, use base airline code only
5. Colored rows are still valid data — do not skip them

## Output Format

Return ONLY a valid JSON object — no markdown, no explanation:

{
  "deals": [
    {
      "airline_type": "GDS",
      "airline_name": "Air India",
      "iata_commission": null,
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
          "targetBased": "Amount Based",
          "amountBasedType": "Fixed",
          "baseTargetAmount": null,
          "segmentBasedType": null,
          "baseTargetSegments": null,
          "incentiveNumPct": "Percentage",
          "incentiveAmtPct": 2.0,
          "cappedIncentive": null
        }
      },
      "remark": "Lords issuance. OB/IB till 31 Mar 2026. No PLB on code share."
    }
  ]
}

## Final Rules

- Every commission % is a FIXED amount-based payout — for each deal ALWAYS set:
  targetBased="Amount Based", amountBasedType="Fixed", incentiveNumPct="Percentage",
  and incentiveAmtPct = the numeric % (e.g. 2.0 for "2.00%").
- Always prioritize accuracy over assumptions
- Never merge multiple class deals into one
- If data is missing → set null (do not guess)
- Output MUST be complete and valid JSON with a top-level "deals" array
- Return ONLY the JSON object, no markdown fences or extra text
- Keep "remark" values concise — max 120 characters
- Output MUST be complete and valid JSON. Do not truncate mid-object
"""


class AIDealExtractionService:
    @staticmethod
    async def extract(file: UploadFile, max_deals: int = 15) -> dict:
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

        deals = await AIDealExtractionService._call_openai(pdf_text, max_deals=max_deals)

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
    async def _call_openai(pdf_text: str, max_deals: int = 15) -> list[dict]:
        from openai import AsyncOpenAI
        from app.config import settings

        client = AsyncOpenAI(api_key=settings.OPENAI_API_KEY)

        # Limit input — 6000 chars covers ~3 PDF pages (~15-20 airline rows)
        truncated = pdf_text[:6000]

        limit_instruction = (
            f"\n\nIMPORTANT: Extract a MAXIMUM of {max_deals} deals. "
            "Process rows from the top of the document only. "
            f"Stop immediately once you have {max_deals} deals. Do not process further rows."
        )

        response = await client.chat.completions.create(
            model="gpt-4o",
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": f"Extract deals from this document text:{limit_instruction}\n\n{truncated}"},
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
