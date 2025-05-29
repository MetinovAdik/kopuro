from fastapi.testclient import TestClient
from sqlalchemy.orm import Session
from auth.schemas import user_schemas
from auth.db import crud

API_PREFIX = "/auth_service"


def test_root_endpoint(client: TestClient):
    response = client.get(API_PREFIX + "/")
    assert response.status_code == 200
    assert response.json() == {"message": f"Welcome to {client.app.title} v{client.app.version}"}


def test_register_worker(client: TestClient, db_session: Session, test_worker_user_data):
    registration_data = {
        "email": test_worker_user_data["email"],
        "full_name": test_worker_user_data["full_name"],
        "password": test_worker_user_data["password"]
    }
    response = client.post(API_PREFIX + "/auth/register", json=registration_data)
    assert response.status_code == 200
    created_user = response.json()
    assert created_user["email"] == test_worker_user_data["email"]
    assert created_user["role"] == user_schemas.UserRole.WORKER.value
    assert not created_user["is_active"]
    assert not created_user["is_confirmed_by_admin"]


    db_user = crud.get_user_by_email(db_session, email=test_worker_user_data["email"])
    assert db_user is not None
    assert not db_user.is_active
    assert not db_user.is_confirmed_by_admin


def test_register_duplicate_email(client: TestClient, test_unconfirmed_worker, test_worker_user_data):
    registration_data = {
        "email": test_worker_user_data["email"],
        "full_name": "Another Worker",
        "password": "anotherpassword"
    }
    response = client.post(API_PREFIX + "/auth/register", json=registration_data)
    assert response.status_code == 400
    assert "Email already registered" in response.json()["detail"]


def test_login_unconfirmed_worker(client: TestClient, test_unconfirmed_worker, test_worker_user_data):
    login_data = {
        "username": test_worker_user_data["email"],
        "password": test_worker_user_data["password"]
    }
    response = client.post(API_PREFIX + "/auth/token", data=login_data)
    assert response.status_code == 403
    assert "Worker account not yet confirmed by admin" in response.json()["detail"]


def test_login_admin(client: TestClient, test_admin_user, test_admin_user_data):
    login_data = {
        "username": test_admin_user_data["email"],
        "password": test_admin_user_data["password"]
    }
    response = client.post(API_PREFIX + "/auth/token", data=login_data)
    assert response.status_code == 200
    tokens = response.json()
    assert "access_token" in tokens
    assert tokens["token_type"] == "bearer"


def test_get_current_user_me(client: TestClient, admin_auth_headers, test_admin_user_data):
    response = client.get(API_PREFIX + "/auth/users/me", headers=admin_auth_headers)
    assert response.status_code == 200
    user_me = response.json()
    assert user_me["email"] == test_admin_user_data["email"]
    assert user_me["role"] == user_schemas.UserRole.ADMIN.value
    assert user_me["is_active"]
    assert user_me["is_confirmed_by_admin"]


def test_admin_get_unconfirmed_workers(client: TestClient, admin_auth_headers, test_unconfirmed_worker):
    response = client.get(API_PREFIX + "/admin/unconfirmed-workers", headers=admin_auth_headers)
    assert response.status_code == 200
    workers = response.json()
    assert len(workers) >= 1
    assert any(w["email"] == test_unconfirmed_worker.email for w in workers)
    assert not workers[0]["is_confirmed_by_admin"]


# In tests/test_auth_flow.py :: test_admin_confirm_worker
def test_admin_confirm_worker(client: TestClient, db_session: Session, admin_auth_headers, test_unconfirmed_worker):
    response = client.patch(
        f"{API_PREFIX}/admin/confirm-worker/{test_unconfirmed_worker.id}",
        headers=admin_auth_headers
    )
    assert response.status_code == 200
    confirmed_worker_data = response.json()
    assert confirmed_worker_data["id"] == test_unconfirmed_worker.id
    assert confirmed_worker_data["is_active"]
    assert confirmed_worker_data["is_confirmed_by_admin"]

    db_session.expire(test_unconfirmed_worker)
    assert test_unconfirmed_worker is not None
    assert test_unconfirmed_worker.is_active
    assert test_unconfirmed_worker.is_confirmed_by_admin


def test_login_confirmed_worker(client: TestClient, db_session: Session, admin_auth_headers, test_unconfirmed_worker, test_worker_user_data):
    client.patch(
        f"{API_PREFIX}/admin/confirm-worker/{test_unconfirmed_worker.id}",
        headers=admin_auth_headers
    )
    login_data = {
        "username": test_worker_user_data["email"],
        "password": test_worker_user_data["password"]
    }
    response = client.post(API_PREFIX + "/auth/token", data=login_data)
    assert response.status_code == 200
    tokens = response.json()
    assert "access_token" in tokens
