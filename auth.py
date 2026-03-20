from datetime import datetime, timedelta
import bcrypt
from jose import JWTError, jwt
from fastapi import Request
from config import SECRET_KEY, ALGORITHM
from database import SessionLocal


def authenticate_user(username: str, password: str):
    import models
    db = SessionLocal()
    try:
        user = db.query(models.User).filter(models.User.username == username).first()
        if not user:
            return None
        if not bcrypt.checkpw(password.encode(), user.hashed_password.encode()):
            return None
        return {"username": user.username}
    finally:
        db.close()


def create_access_token(data: dict, expires_delta: timedelta = None):
    to_encode = data.copy()
    expire = datetime.utcnow() + (expires_delta or timedelta(minutes=60))
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)


def get_current_user(request: Request) -> str | None:
    token = request.cookies.get("access_token")
    if not token:
        return None
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        username: str = payload.get("sub")
        if not username:
            return None
        import models
        db = SessionLocal()
        try:
            user = db.query(models.User).filter(models.User.username == username).first()
            if not user:
                return None
        finally:
            db.close()
        return username
    except JWTError:
        return None
