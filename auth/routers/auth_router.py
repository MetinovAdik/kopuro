from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy.orm import Session
from datetime import timedelta

from auth.db import crud, database
from auth.schemas import user_schemas
from auth.core import security, deps
from auth.core.config import settings

router = APIRouter(
    prefix="/auth",  # Prefix for all routes in this router
    tags=["Authentication"],
)


@router.post("/register", response_model=user_schemas.User)
def register_user(user_in: user_schemas.UserRegister, db: Session = Depends(database.get_db)):
    db_user = crud.get_user_by_email(db, email=user_in.email)
    if db_user:
        raise HTTPException(status_code=400, detail="Email already registered")
    user_create_data = user_schemas.UserCreate(
        email=user_in.email,
        full_name=user_in.full_name,
        password=user_in.password,
        role=user_schemas.UserRole.WORKER
    )
    return crud.create_user(db=db, user=user_create_data)


@router.post("/token", response_model=user_schemas.Token)
def login_for_access_token(
        db: Session = Depends(database.get_db),
        form_data: OAuth2PasswordRequestForm = Depends()
):
    user = crud.authenticate_user(db, email=form_data.username, password=form_data.password)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect email or password",
            headers={"WWW-Authenticate": "Bearer"},
        )
    if user.role == user_schemas.UserRole.WORKER and not user.is_confirmed_by_admin:
        raise HTTPException(status_code=403, detail="Worker account not yet confirmed by admin.")
    if not user.is_active:
        raise HTTPException(status_code=400, detail="Inactive user")

    access_token_expires = timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    access_token = security.create_access_token(
        data={
            "sub": user.email,
            "role": user.role.value,
            "is_active": user.is_active,
            "is_confirmed_by_admin": user.is_confirmed_by_admin
        },
        expires_delta=access_token_expires
    )
    return {"access_token": access_token, "token_type": "bearer"}


@router.get("/users/me", response_model=user_schemas.User)
def read_users_me(current_user: user_schemas.User = Depends(deps.get_current_active_user)):
    return current_user