from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from jose import JWTError, jwt
from sqlalchemy.orm import Session
from auth.db import database, models, crud
from auth.schemas import user_schemas
from .config import settings

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="auth/token")


def get_current_user(
        db: Session = Depends(database.get_db), token: str = Depends(oauth2_scheme)
) -> models.User:
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])
        email: str = payload.get("sub")
        if email is None:
            raise credentials_exception
        token_data = user_schemas.TokenData(email=email,
                                            role=payload.get("role"),
                                            is_active=payload.get("is_active"),
                                            is_confirmed_by_admin=payload.get("is_confirmed_by_admin"))
    except JWTError:
        raise credentials_exception

    user = crud.get_user_by_email(db, email=token_data.email)
    if user is None:
        raise credentials_exception
    return user


def get_current_active_user(
        current_user: models.User = Depends(get_current_user)
) -> models.User:
    if not current_user.is_active:
        raise HTTPException(status_code=400, detail="Inactive user")
    if current_user.role == user_schemas.UserRole.WORKER and not current_user.is_confirmed_by_admin:
        raise HTTPException(status_code=403, detail="Worker account not confirmed by admin")
    return current_user


def get_current_active_admin_user(
        current_user: models.User = Depends(get_current_active_user)
) -> models.User:
    if current_user.role != user_schemas.UserRole.ADMIN:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="The user doesn't have enough privileges (Admin role required)",
        )
    return current_user