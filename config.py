import os
import secrets
import bcrypt

SECRET_KEY = os.environ.get("SECRET_KEY", secrets.token_hex(32))
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 60 * 8  # 8 uur

# SMTP instellingen voor wachtwoord-reset emails
SMTP_HOST = os.getenv("SMTP_HOST", "")
SMTP_PORT = int(os.getenv("SMTP_PORT", "587"))
SMTP_USER = os.getenv("SMTP_USER", "")
SMTP_PASSWORD = os.getenv("SMTP_PASSWORD", "")
SMTP_FROM = os.getenv("SMTP_FROM", "")
APP_URL = os.getenv("APP_URL", "http://localhost:8000")

# Hardcoded gebruikers: gebruikersnaam -> gehashte wachtwoorden
# boer1 / welkom123
# boer2 / welkom456
USERS = {
    "boer1": {
        "username": "boer1",
        "hashed_password": bcrypt.hashpw("welkom123".encode(), bcrypt.gensalt()).decode(),
    },
    "boer2": {
        "username": "boer2",
        "hashed_password": bcrypt.hashpw("welkom456".encode(), bcrypt.gensalt()).decode(),
    },
}
