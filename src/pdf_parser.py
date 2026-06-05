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
                    "Morgan Stanley, Pershing)? Answer YES or NO only.\n\n"
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
        "The provider is the CUSTODIAN or BROKERAGE INSTITUTION that holds the investment account — "
        "the company whose name appears on the letterhead or logo of the statement. "
        "Common examples: Morgan Stanley, Charles Schwab, Schwab, Fidelity, Pershing, "
        "Wells Fargo, JP Morgan, UBS, TD Ameritrade, Vanguard, BlackRock, BNY Mellon, "
        "First Western Bank, Interactive Brokers, Transamerica.\n"
        "Do NOT use the trustee company name (e.g. Sterling Trustees, Sterling Trustee, "
        "any company with 'Trustee' or 'Trust Company' in its name) — that is the trust manager, "
        "not the custodian. It typically appears in the mailing address block, not the letterhead."
    )

    _USER_TEMPLATE = (
        "Extract the following three fields from this custodial statement and return ONLY a JSON object.\n\n"
        "Statement text:\n---\n{text}\n---\n\n"
        '{{"provider": "custodian/brokerage name from the statement letterhead only", '
        '"account_number": "account number digits only, no spaces or dashes", '
        '"statement_date": "statement period end date in MM-DD-YYYY format"}}'
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

        missing = [k for k in ("provider", "account_number", "statement_date") if not data.get(k)]
        if missing:
            raise ParseError(f"Could not extract {', '.join(missing)} from {filename}")

        return StatementInfo(
            provider=data["provider"],
            account_number=data["account_number"],
            statement_date=data["statement_date"],
        )
