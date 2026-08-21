"""
Manejo de credenciales OAuth para Classroom + Drive.
"""
import os
os.environ.setdefault("OAUTHLIB_RELAX_TOKEN_SCOPE", "1")

from pathlib import Path

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow

from . import config

CLIENT_SECRET_PATH = config.CREDENTIALS_DIR / "client_secret.json"
TOKEN_PATH = config.CREDENTIALS_DIR / "token.json"


def get_credentials() -> Credentials:
    config.ensure_dirs()
    creds = None

    if TOKEN_PATH.exists():
        creds = Credentials.from_authorized_user_file(str(TOKEN_PATH), config.SCOPES)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            if not CLIENT_SECRET_PATH.exists():
                raise FileNotFoundError(
                    f"No encuentro {CLIENT_SECRET_PATH}. Descárgalo desde Google Cloud "
                    f"Console (ver README.md) y ponlo exactamente en esa ruta."
                )
            flow = InstalledAppFlow.from_client_secrets_file(str(CLIENT_SECRET_PATH), config.SCOPES)
            creds = flow.run_local_server(port=0)

        TOKEN_PATH.write_text(creds.to_json())

    return creds
