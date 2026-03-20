import os
import bcrypt

SECRET_KEY = os.getenv("SECRET_KEY", "verander-dit-in-productie-gebruik-een-lang-random-string")
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 60 * 8  # 8 uur

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
