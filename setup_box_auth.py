import json
import sys
import webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import parse_qs, urlparse
from dotenv import load_dotenv
from src.config import StatementConfig
from src.box_client import TokenStore
from boxsdk import OAuth2

_REDIRECT_URI = "http://localhost:8080/callback"
_auth_code: list[str] = []
_expected_state: list[str] = []


class _CallbackHandler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        params = parse_qs(urlparse(self.path).query)
        code = params.get("code", [None])[0]
        state = params.get("state", [None])[0]
        if code and _expected_state and state == _expected_state[0]:
            _auth_code.append(code)
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b"<h2>Box authorised. You can close this tab.</h2>")
        else:
            self.send_response(400)
            self.end_headers()
            self.wfile.write(b"<h2>Authorisation failed. Close this tab and try again.</h2>")

    def log_message(self, *args) -> None:
        pass


def main() -> None:
    load_dotenv()
    config = StatementConfig.from_env()

    if not config.box_client_id or not config.box_client_secret:
        print("BOX_CLIENT_ID and BOX_CLIENT_SECRET must be set in .env")
        sys.exit(1)

    token_store = TokenStore(config.token_file)
    oauth = OAuth2(
        client_id=config.box_client_id,
        client_secret=config.box_client_secret,
        store_tokens=token_store.save,
    )

    auth_url, csrf_token = oauth.get_authorization_url(_REDIRECT_URI)
    _expected_state.append(csrf_token)
    print("Opening Box login in browser...")
    webbrowser.open(auth_url)

    HTTPServer(("localhost", 8080), _CallbackHandler).handle_request()

    if not _auth_code:
        print("No authorisation code received.")
        sys.exit(1)

    oauth.authenticate(_auth_code[0])
    print(f"Box connected. Token saved to: {config.token_file}")
    print("Run: python main.py")


if __name__ == "__main__":
    main()
