import json
from pathlib import Path
import pdfplumber
import anthropic
from src.models import StatementInfo
from src.exceptions import ParseError


class PDFParser:
    _MODEL = "claude-haiku-4-5-20251001"
    _MAX_PAGES = 5
    _MAX_CHARS = 5000

    def __init__(self, api_key: str) -> None:
        self._client = anthropic.Anthropic(api_key=api_key)

    _SCREEN_SYSTEM = (
        "You are a document classifier for a trust company. "
        "Reply with only the single word YES or NO — nothing else."
    )

    def is_custodial_statement(self, pdf_path: Path) -> bool:
        text = self._extract_text(pdf_path)
        if not text.strip():
            return False
        response = self._client.messages.create(
            model=self._MODEL,
            max_tokens=5,
            system=self._SCREEN_SYSTEM,
            messages=[{
                "role": "user",
                "content": (
                    "Is this document a custodial investment or financial statement "
                    "from a brokerage or financial institution (e.g. Schwab, Fidelity, "
                    "Morgan Stanley, Pershing, or any other)? Answer YES or NO only.\n\n"
                    f"Document text:\n---\n{text[:2000]}\n---"
                ),
            }],
        )
        answer = response.content[0].text.strip().upper()
        return answer == "YES"

    def parse(self, pdf_path: Path) -> StatementInfo:
        text = self._extract_text(pdf_path)
        if not text.strip():
            raise ParseError(f"No text in {pdf_path.name} — may be a scanned image PDF.")
        return self._classify(text, pdf_path.name)

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
        'NOT the trustee company, NOT the fund name"}}'
    )

    def _classify(self, text: str, filename: str) -> StatementInfo:
        response = self._client.messages.create(
            model=self._MODEL,
            max_tokens=256,
            system=self._SYSTEM_PROMPT,
            messages=[{
                "role": "user",
                "content": self._USER_TEMPLATE.format(text=text[: self._MAX_CHARS]),
            }],
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
            provider=data["provider"],
            account_number=data["account_number"],
            statement_date=data["statement_date"],
            trust_name=data.get("trust_name") or None,
        )

    @staticmethod
    def _provider_from_filename(filename: str) -> str | None:
        stem = Path(filename).stem
        parts = [p.strip() for p in stem.split(" - ")]
        if len(parts) >= 3:
            return parts[1]
        return None
