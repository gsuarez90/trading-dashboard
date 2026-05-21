"""
One-time Schwab OAuth login. Run this once to generate schwab_token.json.
After that, schwab_service.py loads the token automatically.

Usage (from repo root):
    python scripts/schwab_auth.py

Note: the callback URL registered in the Schwab developer portal must match
SCHWAB_CALLBACK_URL exactly, including the port (default: https://127.0.0.1:8182).
"""

import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent.parent / ".env.local")

import schwab

TOKEN_PATH = Path(__file__).resolve().parent.parent / "backend" / "schwab_token.json"


def main():
    client = schwab.auth.easy_client(
        api_key=os.environ["SCHWAB_CLIENT_ID"],
        app_secret=os.environ["SCHWAB_CLIENT_SECRET"],
        callback_url=os.environ.get("SCHWAB_CALLBACK_URL", "https://127.0.0.1:8182"),
        token_path=str(TOKEN_PATH),
    )
    print(f"\nAuth complete. Token saved to {TOKEN_PATH}")
    print("You can now start the backend — schwab_service.py will load this token automatically.")


if __name__ == "__main__":
    main()
