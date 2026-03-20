import os
from passlib.context import CryptContext

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

SECRET_KEY = os.getenv("SECRET_KEY", "verander-dit-in-productie-gebruik-een-lang-random-string")
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 60 * 8  # 8 uur

# Hardcoded gebruikers: gebruikersnaam -> gehashte wachtwoorden
# boer1 / welkom123
# boer2 / welkom456
USERS = {
    "boer1": {
        "username": "boer1",
        "hashed_password": pwd_context.hash("welkom123"),
    },
    "boer2": {
        "username": "boer2",
        "hashed_password": pwd_context.hash("welkom456"),
    },
}
