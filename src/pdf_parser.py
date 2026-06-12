import base64
import json
import re
from pathlib import Path
import pdfplumber
import anthropic
from src.models import StatementInfo
from src.exceptions import ParseError


class PDFParser:
    _MODEL = "claude-haiku-4-5-20251001"
    _MAX_PAGES = 8
    _MAX_CHARS = 15000
    _MAX_PDF_BYTES = 30_000_000

    def __init__(self, api_key: str) -> None:
        self._client = anthropic.Anthropic(api_key=api_key)

    def parse(self, pdf_path: Path) -> StatementInfo:
        text = self._extract_text(pdf_path)
        if text.strip():
            content = self._USER_TEMPLATE.format(text=text[: self._MAX_CHARS])
        else:
            content = self._document_content(pdf_path)
        return self._classify(content, pdf_path.name)

    def _document_content(self, pdf_path: Path) -> list:
        data = pdf_path.read_bytes()
        if len(data) > self._MAX_PDF_BYTES:
            raise ParseError(f"Scanned PDF too large to process: {pdf_path.name}")
        return [
            {
                "type": "document",
                "source": {
                    "type": "base64",
                    "media_type": "application/pdf",
                    "data": base64.b64encode(data).decode(),
                },
            },
            {
                "type": "text",
                "text": self._USER_TEMPLATE.format(
                    text="(no machine-readable text — read the attached scanned statement)"
                ),
            },
        ]

    def _extract_text(self, pdf_path: Path) -> str:
        parts: list[str] = []
        with pdfplumber.open(pdf_path) as pdf:
            for page in pdf.pages[: self._MAX_PAGES]:
                text = page.extract_text()
                if text:
                    parts.append(text)
        return "\n".join(parts)

    _SYSTEM_PROMPT = (
        "You are a financial document parser for a trust company. "
        "Your only job is to extract structured data from custodial investment statements. "
        "Always respond with a single valid JSON object and nothing else — no markdown, no explanation, no extra text. "
        "If a field cannot be determined with confidence, use null.\n\n"
        "CRITICAL — provider extraction rules:\n"
        "The provider is the financial institution, fund manager, or investment firm whose name "
        "appears on the LETTERHEAD or LOGO at the top of the statement — the entity that ISSUED this document. "
        "For brokerage statements: Morgan Stanley, Charles Schwab, Fidelity, Pershing, Wells Fargo, "
        "JP Morgan, UBS, TD Ameritrade, Vanguard, BlackRock, BNY Mellon, Interactive Brokers, Transamerica. "
        "For fund statements: the fund manager or fund name shown on the letterhead (e.g. Fourthstone, "
        "Hamilton Lane, KKR, Apollo, Blackstone). "
        "Do NOT use the trust or client name (e.g. 'The Beethoven Trust', 'Camden Trust') — that is the account holder. "
        "Do NOT use the trustee company name (e.g. Sterling Trustees, any company with 'Trustee' or 'Trust Company') — "
        "that is the trust manager, not the issuer."
    )

    _USER_TEMPLATE = (
        "Extract the following fields from this financial statement and return ONLY a JSON object.\n\n"
        "Statement text:\n---\n{text}\n---\n\n"
        '{{"provider": "name of the fund, brokerage, or financial institution from the letterhead or logo", '
        '"account_number": "the primary account identifier — could be labelled Account Number, Account #, '
        "SubEntity ID, Fund Code, Client ID, Portfolio Number, or any similar unique identifier. "
        'Return digits and letters only, no spaces or dashes", '
        '"statement_date": "statement period end date or valuation date in MM-DD-YYYY format", '
        '"trust_name": "the trust or client name this statement is addressed to (e.g. The Beethoven Trust, Camden Trust) — '
        'NOT the trustee company, NOT the fund name", '
        '"fund_name": "the specific FUND the investment is held in, if this is a fund or private equity statement '
        '(e.g. Fenghe Asia (UST) Fund Ltd, Fourthstone QP Opportunity Fund LP, Engine Capital LP) — '
        'null for regular brokerage accounts"}}'
    )

    def _classify(self, content: str | list, filename: str) -> StatementInfo:
        response = self._client.messages.create(
            model=self._MODEL,
            max_tokens=256,
            system=self._SYSTEM_PROMPT,
            messages=[{"role": "user", "content": content}],
        )
        try:
            raw = response.content[0].text.strip()
        except (IndexError, AttributeError) as exc:
            raise ParseError(f"Unexpected API response structure for {filename}") from exc

        if raw.startswith("```"):
            raw = raw.split("\n", 1)[1].rsplit("```", 1)[0].strip()

        try:
            data = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise ParseError(f"Model returned invalid JSON for {filename}: {raw}") from exc

        if not data.get("provider"):
            data["provider"] = self._provider_from_filename(filename)

        missing = [k for k in ("provider", "account_number", "statement_date") if not data.get(k)]
        if missing:
            raise ParseError(f"Could not extract {', '.join(missing)} from {filename}")

        return StatementInfo(
            provider=str(data["provider"]).strip(),
            account_number=str(data["account_number"]).strip(),
            statement_date=self._normalize_date(str(data["statement_date"]), filename),
            trust_name=str(data["trust_name"]).strip() if data.get("trust_name") else None,
            fund_name=str(data["fund_name"]).strip() if data.get("fund_name") else None,
        )

    @staticmethod
    def _normalize_date(raw: str, filename: str) -> str:
        m = re.match(r"^\s*(\d{1,2})[-/](\d{1,2})[-/](\d{4})\s*$", raw)
        if not m:
            raise ParseError(f"Invalid statement date '{raw}' in {filename}")
        month, day, year = int(m.group(1)), int(m.group(2)), int(m.group(3))
        if not (1 <= month <= 12 and 1 <= day <= 31 and 1990 <= year <= 2100):
            raise ParseError(f"Implausible statement date '{raw}' in {filename}")
        return f"{month:02d}-{day:02d}-{year}"

    @staticmethod
    def _provider_from_filename(filename: str) -> str | None:
        stem = Path(filename).stem
        parts = [p.strip() for p in stem.split(" - ")]
        if len(parts) >= 3:
            return parts[1]
        return None
