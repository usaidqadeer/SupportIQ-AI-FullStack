from fastapi.testclient import TestClient
from app.main import app
client=TestClient(app)
def test_health():
 response=client.get("/");assert response.status_code==200;assert response.json()["status"]=="healthy"
def test_auth_required():assert client.get("/api/tickets").status_code==401
