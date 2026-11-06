"""ActiveLife Gym BPM prototype: FastAPI + SQLite, with a local demo payment flow."""
from contextlib import closing
from datetime import datetime, timedelta, timezone
from pathlib import Path
import re
import secrets
import sqlite3
import uuid
from io import BytesIO

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, EmailStr, Field

ROOT = Path(__file__).parent
DB = ROOT / "gym_database.db"
app = FastAPI(title="ActiveLife Gym BPM Prototype", version="1.0.0")
app.mount("/static", StaticFiles(directory=ROOT / "static"), name="static")

def db():
    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn

def init_db():
    with closing(db()) as c:
        c.executescript("""
        CREATE TABLE IF NOT EXISTS customers(customer_id INTEGER PRIMARY KEY, full_name TEXT NOT NULL, phone TEXT NOT NULL UNIQUE, email TEXT NOT NULL UNIQUE, created_at TEXT DEFAULT CURRENT_TIMESTAMP);
        CREATE TABLE IF NOT EXISTS surveys(survey_id INTEGER PRIMARY KEY, customer_id INTEGER NOT NULL REFERENCES customers, parq_json TEXT NOT NULL, medical_alert INTEGER NOT NULL, raw_goal_text TEXT NOT NULL, goal TEXT NOT NULL, confidence REAL NOT NULL, status TEXT NOT NULL, consultant_notes TEXT DEFAULT '', created_at TEXT DEFAULT CURRENT_TIMESTAMP);
        CREATE TABLE IF NOT EXISTS trainers(trainer_id INTEGER PRIMARY KEY, full_name TEXT NOT NULL, specialty TEXT NOT NULL, coaching_style TEXT NOT NULL, active_clients INTEGER NOT NULL, capacity INTEGER NOT NULL, rating REAL NOT NULL, available INTEGER NOT NULL DEFAULT 1);
        CREATE TABLE IF NOT EXISTS contracts(contract_id INTEGER PRIMARY KEY, contract_code TEXT NOT NULL UNIQUE, customer_id INTEGER NOT NULL REFERENCES customers, survey_id INTEGER NOT NULL REFERENCES surveys, trainer_id INTEGER REFERENCES trainers, package_name TEXT NOT NULL, months INTEGER NOT NULL, total_amount INTEGER NOT NULL, status TEXT NOT NULL DEFAULT 'DRAFT', signature_data TEXT, signed_at TEXT, hold_expire_at TEXT, qr_token TEXT UNIQUE, created_at TEXT DEFAULT CURRENT_TIMESTAMP);
        CREATE TABLE IF NOT EXISTS payments(payment_id INTEGER PRIMARY KEY, contract_id INTEGER NOT NULL REFERENCES contracts, transaction_ref TEXT NOT NULL UNIQUE, method TEXT NOT NULL, amount INTEGER NOT NULL, status TEXT NOT NULL, paid_at TEXT);
        """)
        if c.execute("SELECT COUNT(*) FROM trainers").fetchone()[0] == 0:
            c.executemany("INSERT INTO trainers(full_name,specialty,coaching_style,active_clients,capacity,rating,available) VALUES(?,?,?,?,?,?,?)", [
                ("Nguyễn Minh Khôi","WEIGHT_LOSS","MOTIVATIONAL",6,15,4.9,1),("Trần Thu Hà","MUSCLE_GAIN","STRICT",9,15,4.8,1),
                ("Lê Quốc Bảo","REHAB","GENTLE",5,12,5.0,1),("Phạm Ngọc Linh","GENERAL_FITNESS","MOTIVATIONAL",8,15,4.7,1)])
        c.commit()

@app.on_event("startup")
def startup(): init_db()

@app.get("/")
def home(): return FileResponse(ROOT / "static" / "index.html")

@app.get("/api/health")
def health(): return {"ok": True, "app": "ActiveLife Gym"}

@app.get("/api/membership/qr/{token}")
def membership_qr(token: str):
    try:
        import qrcode
        image = qrcode.make(token)
        output = BytesIO(); image.save(output, format="PNG"); output.seek(0)
        return StreamingResponse(output, media_type="image/png", headers={"Cache-Control":"no-store"})
    except ImportError as exc:
        raise HTTPException(503,"Thiếu thư viện tạo QR. Cài requirements.txt để bật mã QR.") from exc

GOALS = {
 "WEIGHT_LOSS": ["giảm cân","giảm mỡ","thon gọn","cardio","béo","eo thon","xuống cân","giảm kg"],
 "MUSCLE_GAIN": ["tăng cơ","tăng cân","thể hình","cơ bắp","to ngực","vai rộng","bulk"],
 "REHAB": ["đau lưng","thoát vị","cổ vai gáy","khớp","phục hồi","chấn thương"],
 "GENERAL_FITNESS": ["khỏe mạnh","dẻo dai","xả stress","duy trì","sức bền","năng động"]}

def classify(text):
    normalized = text.lower(); scores = {g: sum(w in normalized for w in words) for g, words in GOALS.items()}
    best = max(scores, key=scores.get); n = scores[best]
    confidence = min(.85+n*.05,.98) if n >= 2 else (.825 if n == 1 else .65)
    if n == 0: best = "GENERAL_FITNESS"
    return best, round(confidence,3)

def trainer_scores(goal):
    with closing(db()) as c:
        trainers = c.execute("SELECT * FROM trainers WHERE available=1 AND active_clients < capacity").fetchall()
    result=[]
    for t in trainers:
        sg=1.0 if t['specialty']==goal else .4
        load=max(0,1-t['active_clients']/t['capacity'])
        score=.30*sg+.20+.20*load+.15+.15
        result.append({"trainer_id":t['trainer_id'],"full_name":t['full_name'],"specialty":t['specialty'],"rating":t['rating'],"score":round(score,3),"load":t['active_clients']/t['capacity']})
    return sorted(result,key=lambda x:x['score'],reverse=True)

class SurveyIn(BaseModel):
    full_name: str = Field(min_length=2,max_length=100)
    phone: str = Field(min_length=9,max_length=15)
    email: EmailStr
    raw_goal_text: str = Field(min_length=3,max_length=1000)
    parq: list[bool] = Field(min_length=5,max_length=7)

@app.post("/api/survey/submit")
def submit_survey(req: SurveyIn):
    if not re.fullmatch(r"[+0-9 ()-]{9,15}",req.phone): raise HTTPException(422,"Số điện thoại không hợp lệ")
    goal, confidence=classify(req.raw_goal_text); status="AUTO_ACCEPTED" if confidence>=.82 else "MANUAL_REVIEW_T5"
    with closing(db()) as c:
        try:
            cur=c.execute("INSERT INTO customers(full_name,phone,email) VALUES(?,?,?)",(req.full_name.strip(),req.phone.strip(),req.email.lower()))
            customer_id=cur.lastrowid; alert=int(any(req.parq))
            cur=c.execute("INSERT INTO surveys(customer_id,parq_json,medical_alert,raw_goal_text,goal,confidence,status) VALUES(?,?,?,?,?,?,?)",(customer_id,str([int(x) for x in req.parq]),alert,req.raw_goal_text,goal,confidence,status))
            survey_id=cur.lastrowid;c.commit()
        except sqlite3.IntegrityError as e: raise HTTPException(409,"Email hoặc số điện thoại đã được đăng ký") from e
    return {"survey_id":survey_id,"customer_id":customer_id,"goal":goal,"confidence":confidence,"status":status,"medical_alert":bool(alert),"trainers":trainer_scores(goal)}

@app.get("/api/consultant/pending-reviews")
def pending_reviews():
    with closing(db()) as c:
        rows=c.execute("SELECT s.*,cu.full_name,cu.phone FROM surveys s JOIN customers cu USING(customer_id) WHERE s.status='MANUAL_REVIEW_T5' ORDER BY s.survey_id DESC").fetchall()
    return [dict(r) for r in rows]

class VerifyIn(BaseModel):
    goal: str
    notes: str = ""

@app.put("/api/consultant/verify-goal/{survey_id}")
def verify_goal(survey_id:int, req:VerifyIn):
    if req.goal not in GOALS: raise HTTPException(422,"Mục tiêu không hợp lệ")
    with closing(db()) as c:
        cur=c.execute("UPDATE surveys SET goal=?,status='CONSULTANT_VERIFIED',consultant_notes=? WHERE survey_id=? AND status='MANUAL_REVIEW_T5'",(req.goal,req.notes,survey_id));c.commit()
        if cur.rowcount==0: raise HTTPException(404,"Không tìm thấy hồ sơ đang chờ duyệt")
    return {"ok":True,"trainers":trainer_scores(req.goal)}

@app.get("/api/packages")
def packages(): return [{"id":"BASIC","name":"Basic","monthly":490000},{"id":"CLASSIC","name":"Classic","monthly":890000},{"id":"VIP_PT","name":"VIP PT","monthly":1590000}]

class ContractIn(BaseModel):
    survey_id:int
    trainer_id:int
    package_name:str
    months:int=Field(ge=1,le=12)

@app.post("/api/contracts/generate")
def create_contract(req:ContractIn):
    prices={"BASIC":490000,"CLASSIC":890000,"VIP_PT":1590000}
    if req.package_name not in prices: raise HTTPException(422,"Gói tập không hợp lệ")
    with closing(db()) as c:
        s=c.execute("SELECT * FROM surveys WHERE survey_id=?",(req.survey_id,)).fetchone()
        t=c.execute("SELECT * FROM trainers WHERE trainer_id=? AND available=1",(req.trainer_id,)).fetchone()
        if not s: raise HTTPException(404,"Không tìm thấy khảo sát")
        if s['status']=="MANUAL_REVIEW_T5": raise HTTPException(409,"Hồ sơ cần tư vấn viên xác nhận trước")
        if not t: raise HTTPException(404,"Huấn luyện viên không khả dụng")
        amount=prices[req.package_name]*req.months
        code=f"AL-{datetime.now().year}-{uuid.uuid4().hex[:6].upper()}"
        cur=c.execute("INSERT INTO contracts(contract_code,customer_id,survey_id,trainer_id,package_name,months,total_amount,hold_expire_at) VALUES(?,?,?,?,?,?,?,?)",(code,s['customer_id'],s['survey_id'],t['trainer_id'],req.package_name,req.months,amount,(datetime.now(timezone.utc)+timedelta(hours=48)).isoformat()))
        contract_id=cur.lastrowid;c.commit()
        return contract_detail(c,contract_id)

def contract_detail(c,contract_id):
    row=c.execute("SELECT co.*,cu.full_name,cu.email,cu.phone,tr.full_name trainer_name,tr.specialty FROM contracts co JOIN customers cu USING(customer_id) LEFT JOIN trainers tr USING(trainer_id) WHERE contract_id=?",(contract_id,)).fetchone()
    if not row: raise HTTPException(404,"Không tìm thấy hợp đồng")
    return dict(row)

@app.get("/api/contracts/{contract_id}")
def get_contract(contract_id:int):
    with closing(db()) as c:return contract_detail(c,contract_id)

class SignIn(BaseModel): signature_data:str=Field(min_length=2,max_length=300)

@app.post("/api/contracts/{contract_id}/sign")
def sign_contract(contract_id:int, req:SignIn):
    with closing(db()) as c:
        row=c.execute("SELECT status FROM contracts WHERE contract_id=?",(contract_id,)).fetchone()
        if not row: raise HTTPException(404,"Không tìm thấy hợp đồng")
        if row['status'] not in ("DRAFT","SIGNED"): raise HTTPException(409,"Hợp đồng không thể ký ở trạng thái này")
        c.execute("UPDATE contracts SET status='SIGNED',signature_data=?,signed_at=? WHERE contract_id=?",(req.signature_data,datetime.now(timezone.utc).isoformat(),contract_id));c.commit()
    return {"ok":True,"message":"Đã ký hợp đồng"}

class PayIn(BaseModel): method:str="DEMO"; transaction_ref:str|None=None

@app.post("/api/contracts/{contract_id}/pay")
def pay_contract(contract_id:int,req:PayIn):
    with closing(db()) as c:
        row=c.execute("SELECT * FROM contracts WHERE contract_id=?",(contract_id,)).fetchone()
        if not row: raise HTTPException(404,"Không tìm thấy hợp đồng")
        if row['status']=="PAID": return {"status":"SUCCESS","contract":contract_detail(c,contract_id),"message":"Giao dịch đã được ghi nhận (idempotent)"}
        if row['status']!="SIGNED": raise HTTPException(409,"Vui lòng ký hợp đồng trước khi thanh toán")
        ref=req.transaction_ref or f"DEMO-{uuid.uuid4().hex}"
        existing=c.execute("SELECT * FROM payments WHERE transaction_ref=?",(ref,)).fetchone()
        if existing and existing['contract_id']!=contract_id: raise HTTPException(409,"Mã giao dịch đã được sử dụng")
        if not existing: c.execute("INSERT INTO payments(contract_id,transaction_ref,method,amount,status,paid_at) VALUES(?,?,?,?,?,?)",(contract_id,ref,req.method,row['total_amount'],"SUCCESS",datetime.now(timezone.utc).isoformat()))
        token=secrets.token_urlsafe(24)
        c.execute("UPDATE contracts SET status='PAID',qr_token=? WHERE contract_id=?",(token,contract_id));c.commit()
        return {"status":"SUCCESS","contract":contract_detail(c,contract_id),"qr_token":token,"message":"Thanh toán demo thành công; thẻ hội viên đã kích hoạt"}

@app.get("/api/dashboard")
def dashboard():
    with closing(db()) as c:
        return {"members":c.execute("SELECT COUNT(*) FROM contracts WHERE status='PAID'").fetchone()[0],"pending_reviews":c.execute("SELECT COUNT(*) FROM surveys WHERE status='MANUAL_REVIEW_T5'").fetchone()[0],"contracts":c.execute("SELECT COUNT(*) FROM contracts").fetchone()[0],"trainers":c.execute("SELECT COUNT(*) FROM trainers WHERE available=1").fetchone()[0]}
