from fastapi import FastAPI, Depends
from sqlalchemy.orm import Session

from .db import models, database, crud
from .routers import auth_router, admin_router
from .core.config import settings

models.Base.metadata.create_all(bind=database.engine)

app = FastAPI(
    title=settings.PROJECT_NAME,
    version=settings.PROJECT_VERSION,
    root_path="/auth_service"
)

@app.on_event("startup")
def on_startup():
    db: Session = next(database.get_db()) # Get a DB session
    try:
        crud.create_first_admin_if_not_exists(db)
    finally:
        db.close()


app.include_router(auth_router.router)
app.include_router(admin_router.router)


@app.get("/")
async def root():
    return {"message": f"Welcome to {settings.PROJECT_NAME} v{settings.PROJECT_VERSION}"}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8001, log_level="info")