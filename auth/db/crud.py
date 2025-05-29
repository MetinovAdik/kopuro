from sqlalchemy.orm import Session
from . import models
from . import database
from auth.schemas import user_schemas
from auth.core import security


def get_user(db: Session, user_id: int):
    return db.query(models.User).filter(models.User.id == user_id).first()


def get_user_by_email(db: Session, email: str):
    return db.query(models.User).filter(models.User.email == email).first()


def get_users(db: Session, skip: int = 0, limit: int = 100):
    return db.query(models.User).offset(skip).limit(limit).all()


def create_user(db: Session, user: user_schemas.UserCreate):
    hashed_password = security.get_password_hash(user.password)
    db_user = models.User(
        email=user.email,
        full_name=user.full_name,
        hashed_password=hashed_password,
        role=user.role,
        is_active=False,  # Default to inactive
        is_confirmed_by_admin=False  # Default to unconfirmed
    )
    # If it's an admin being created programmatically, they can be set to active/confirmed
    if user.role == user_schemas.UserRole.ADMIN:
        db_user.is_active = True
        db_user.is_confirmed_by_admin = True

    db.add(db_user)
    db.commit()
    db.refresh(db_user)
    return db_user


def get_unconfirmed_workers(db: Session, skip: int = 0, limit: int = 100):
    return db.query(models.User).filter(
        models.User.role == user_schemas.UserRole.WORKER,
        models.User.is_confirmed_by_admin == False
    ).offset(skip).limit(limit).all()

def confirm_worker(db: Session, user_id: int):
    db_user = get_user(db, user_id=user_id)
    if db_user and db_user.role == user_schemas.UserRole.WORKER:
        db_user.is_active = True
        db_user.is_confirmed_by_admin = True
        db.commit()
        db.refresh(db_user)
        return db_user
    return None

def authenticate_user(db: Session, email: str, password: str) -> models.User | None:
    user = get_user_by_email(db, email=email)
    if not user:
        return None
    if not security.verify_password(password, user.hashed_password):
        return None
    return user


def create_first_admin_if_not_exists(db: Session):
    from auth.core.config import settings
    if settings.FIRST_ADMIN_EMAIL and settings.FIRST_ADMIN_PASSWORD:
        admin = get_user_by_email(db, email=settings.FIRST_ADMIN_EMAIL)
        if not admin:
            admin_in = user_schemas.UserCreate(
                email=settings.FIRST_ADMIN_EMAIL,
                password=settings.FIRST_ADMIN_PASSWORD,
                full_name="Default Admin",
                role=user_schemas.UserRole.ADMIN
            )
            create_user(db=db, user=admin_in)
            print(f"Default admin user {settings.FIRST_ADMIN_EMAIL} created.")
        elif admin.role != user_schemas.UserRole.ADMIN:
            print(
                f"Warning: User {settings.FIRST_ADMIN_EMAIL} exists but is not an admin. Manual intervention may be required.")