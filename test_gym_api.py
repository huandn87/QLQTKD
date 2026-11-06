"""5 kịch bản nghiệm thu MIS3047; dùng SQLite riêng, không đụng DB demo."""
import pytest
from fastapi.testclient import TestClient

import main

@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(main, "DB_PATH", tmp_path / "test_gym.db")
    with TestClient(main.app) as test_client:
        login=test_client.post("/api/auth/login",json={"username":"customer","password":"Member@123"})
        assert login.status_code==200
        yield test_client

def survey_payload(suffix="01", goal="Muốn giảm cân eo thon", parq=None):
    return {"full_name":"Nguyễn Minh Anh", "phone":f"09012345{suffix}", "email":f"member{suffix}@example.com",
            "raw_goal_text":goal, "parq_answers":parq or [False]*7, "coaching_style":"MOTIVATIONAL"}

def make_contract(client, suffix="01"):
    survey=client.post("/api/survey/submit",json=survey_payload(suffix)).json()
    assert survey["status"]=="AUTO_ACCEPTED"
    trainer=survey["trainers"][0]
    contract=client.post("/api/contracts/generate",json={"survey_id":survey["survey_id"],"trainer_id":trainer["trainer_id"],"package_name":"CLASSIC","months":3})
    assert contract.status_code==200, contract.text
    return contract.json()

def signed_contract(client, suffix="01"):
    contract=make_contract(client,suffix)
    signed=client.post(f"/api/contracts/{contract['contract_id']}/sign",json={"signature_data":"Nguyễn Minh Anh"})
    assert signed.status_code==200, signed.text
    return contract

def test_tc01_happy_path_to_member_qr(client):
    contract=signed_contract(client)
    checkout=client.post("/api/payments/checkout",json={"contract_id":contract["contract_id"],"payment_method":"VNPAY"})
    assert checkout.status_code==200
    paid=client.post("/api/payments/webhook-verify",json={"transaction_ref":checkout.json()["transaction_ref"],"success":True})
    assert paid.json()["status"]=="SUCCESS"
    token=paid.json()["contract"]["membership_qr_token"]
    assert token.startswith("ACTIVELIFE-MEMBER-")
    assert client.get(f"/api/membership/qr/{token}").headers["content-type"]=="image/png"

def test_tc02_confidence_threshold_boundary():
    assert main.route_by_confidence(0.820) is True
    assert main.route_by_confidence(0.819) is False
    assert main.classify_goal_intent("muốn giảm cân eo thon",0.82)["next_step"]=="T6_PRICING"

def test_tc03_invalid_data_and_medical_alert(client):
    # API chặn người chưa đăng nhập và giới hạn quyền theo role.
    with TestClient(main.app) as anonymous:
        assert anonymous.get("/api/survey/questions").status_code==401
        bad_login=anonymous.post("/api/auth/login",json={"username":"admin","password":"sai-mat-khau"})
        assert bad_login.status_code==401
    with TestClient(main.app) as consultant:
        assert consultant.post("/api/auth/login",json={"username":"consultant","password":"Consult@123"}).status_code==200
        assert consultant.get("/api/survey/questions").status_code==403
    assert client.get("/api/consultant/pending-reviews").status_code==403
    assert client.get("/static/activelife-logo.png").status_code==200
    bad=survey_payload("02");bad["phone"]="abc1234"
    assert client.post("/api/survey/submit",json=bad).status_code==422
    bad=survey_payload("03");bad["email"]="email-khong-hop-le"
    assert client.post("/api/survey/submit",json=bad).status_code==422
    risk=survey_payload("04",parq=[True,False,False,False,False,False,False])
    response=client.post("/api/survey/submit",json=risk)
    assert response.status_code==200
    assert response.json()["medical_alert"] is True

def test_tc04_failed_payment_keeps_draft_and_retry_link(client):
    contract=signed_contract(client,"05")
    response=client.post("/api/payments/checkout",json={"contract_id":contract["contract_id"],"payment_method":"MOMO","simulate_failure":True})
    assert response.json()["status"]=="FAILED"
    assert response.json()["retry_link"]
    current=client.get(f"/api/contracts/{contract['contract_id']}").json()
    assert current["status"]=="DRAFT"
    released=client.post(f"/api/slots/release-failed-payment?contract_id={contract['contract_id']}")
    assert released.status_code==200
    assert client.get(f"/api/contracts/{contract['contract_id']}").json()["status"]=="CANCELLED"

def test_tc05_checkout_idempotency_by_transaction_reference(client):
    contract=signed_contract(client,"06")
    body={"contract_id":contract["contract_id"],"payment_method":"VNPAY","transaction_ref":"TXN_TEST_999"}
    first=client.post("/api/payments/checkout",json=body)
    second=client.post("/api/payments/checkout",json=body)
    assert first.status_code==second.status_code==200
    assert second.json()["message"]=="Idempotent OK"
    with main.connection() as c:
        assert c.execute("SELECT COUNT(*) FROM payments WHERE transaction_ref='TXN_TEST_999'").fetchone()[0]==1
