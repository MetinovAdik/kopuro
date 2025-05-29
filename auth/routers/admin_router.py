from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from typing import List

from auth.db import crud, database, models
from auth.schemas import user_schemas
from auth.core import deps

router = APIRouter(
    prefix="/admin",
    tags=["Admin"],
    dependencies=[Depends(deps.get_current_active_admin_user)]
)

@router.get("/users", response_model=List[user_schemas.User])
def read_all_users(skip: int = 0, limit: int = 100, db: Session = Depends(database.get_db)):
    users = crud.get_users(db, skip=skip, limit=limit)
    return users

@router.get("/unconfirmed-workers", response_model=List[user_schemas.User])
def read_unconfirmed_workers(skip: int = 0, limit: int = 100, db: Session = Depends(database.get_db)):
    workers = crud.get_unconfirmed_workers(db, skip=skip, limit=limit)
    return workers

@router.patch("/confirm-worker/{user_id}", response_model=user_schemas.User)
def confirm_worker_registration(user_id: int, db: Session = Depends(database.get_db)):
    db_user = crud.confirm_worker(db, user_id=user_id)
    if db_user is None:
        raise HTTPException(status_code=404, detail="Worker not found or not eligible for confirmation")
    return db_user