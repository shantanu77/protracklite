from datetime import datetime, timedelta
from secrets import choice
from string import ascii_letters, digits

from jose import JWTError, jwt
from passlib.context import CryptContext

from app.config import get_settings


settings = get_settings()
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


def verify_password(plain_password: str, password_hash: str) -> bool:
    return pwd_context.verify(plain_password, password_hash)


def hash_password(password: str) -> str:
    return pwd_context.hash(password)


def create_token(subject: str, token_type: str, expires_delta: timedelta) -> str:
    payload = {
        "sub": subject,
        "type": token_type,
        "exp": datetime.utcnow() + expires_delta,
        "iat": datetime.utcnow(),
    }
    return jwt.encode(payload, settings.secret_key, algorithm=settings.jwt_algorithm)


def decode_token(token: str, expected_type: str) -> str | None:
    try:
        payload = jwt.decode(token, settings.secret_key, algorithms=[settings.jwt_algorithm])
    except JWTError:
        return None
    if payload.get("type") != expected_type:
        return None
    return payload.get("sub")


def create_access_token(subject: str) -> str:
    return create_token(subject, "access", timedelta(minutes=settings.access_token_ttl_minutes))


def create_refresh_token(subject: str) -> str:
    return create_token(subject, "refresh", timedelta(days=settings.refresh_token_ttl_days))


def generate_temp_password(length: int = 10) -> str:
    alphabet = ascii_letters + digits
    return "".join(choice(alphabet) for _ in range(length))
