import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from auth.main import app
from auth.db.database import Base, get_db
from auth.core.config import settings
from auth.schemas import user_schemas
from auth.db import crud
from auth.core.security import get_password_hash

SQLALCHEMY_DATABASE_URL = "sqlite:///:memory:"

engine = create_engine(
    SQLALCHEMY_DATABASE_URL,
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

def override_get_db():
    try:
        db = TestingSessionLocal()
        yield db
    finally:
        db.close()

app.dependency_overrides[get_db] = override_get_db

@pytest.fixture(scope="function")
def db_session():
    Base.metadata.create_all(bind=engine) # Create tables
    db = TestingSessionLocal()
    try:
        yield db
    finally:
        db.close()
        Base.metadata.drop_all(bind=engine)

@pytest.fixture(scope="function")
def client(db_session):
    with TestClient(app) as c:
        yield c

@pytest.fixture(scope="module")
def test_admin_user_data():
    return {
        "email": "admin@test.com",
        "full_name": "Test Admin",
        "password": "testpassword123",
        "role": user_schemas.UserRole.ADMIN
    }

@pytest.fixture(scope="module")
def test_worker_user_data():
    return {
        "email": "worker@test.com",
        "full_name": "Test Worker",
        "password": "testpassword123",
        "role": user_schemas.UserRole.WORKER
    }


@pytest.fixture(scope="function")
def test_admin_user(db_session: sessionmaker, test_admin_user_data):
    user_in = user_schemas.UserCreate(**test_admin_user_data)
    user = crud.create_user(db=db_session, user=user_in)
    return user

@pytest.fixture(scope="function")
def admin_auth_headers(client: TestClient, test_admin_user, test_admin_user_data):
    login_data = {
        "username": test_admin_user_data["email"],
        "password": test_admin_user_data["password"]
    }
    response = client.post("/auth_service/auth/token", data=login_data)
    assert response.status_code == 200
    tokens = response.json()
    a_token = tokens["access_token"]
    headers = {"Authorization": f"Bearer {a_token}"}
    return headers

@pytest.fixture(scope="function")
def test_unconfirmed_worker(db_session: sessionmaker, test_worker_user_data):
    user_in = user_schemas.UserCreate(
        email=test_worker_user_data["email"],
        full_name=test_worker_user_data["full_name"],
        password=test_worker_user_data["password"],
        role=user_schemas.UserRole.WORKER
    )
    user = crud.create_user(db=db_session, user=user_in)
    assert not user.is_confirmed_by_admin
    assert not user.is_active
    return user