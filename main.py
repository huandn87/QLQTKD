"""ActiveLife Gym BPM prototype. Các endpoint ghi Task ID theo mô hình TO-BE."""
from contextlib import asynccontextmanager, contextmanager
from datetime import datetime, timedelta, timezone
import base64
import hashlib
import hmac
from pathlib import Path
from typing import Optional
import asyncio
import json
import os
import re
import secrets
import sqlite3
import uuid

from fastapi import BackgroundTasks, Depends, FastAPI, HTTPException, Request, Response
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from pydantic import BaseModel, EmailStr, Field, field_validator

ROOT = Path(__file__).parent
DB_PATH = Path(os.getenv("GYM_DB_PATH", str(ROOT / "gym_database.db")))
THRESHOLD = 0.82
@asynccontextmanager
async def lifespan(application: FastAPI):
    """Khởi tạo SQLite và chạy worker hết hạn slot theo vòng đời ứng dụng."""
    init_db()
    worker=asyncio.create_task(expiry_worker())
    application.state.expiry_task=worker
    try:
        yield
    finally:
        worker.cancel()
        try: await worker
        except asyncio.CancelledError: pass

app = FastAPI(title="ActiveLife Gym BPM Prototype", version="2.0.0", description="Mô phỏng quy trình TO-BE đăng ký hội viên và ghép huấn luyện viên.", lifespan=lifespan)
NOTIFICATION_LOG: list[dict] = []
SESSION_COOKIE = "activelife_session"
SESSION_SECRET = os.getenv("ACTIVELIFE_SESSION_SECRET", "local-demo-change-this-secret-before-deployment").encode()
DEMO_USERS = {
    "customer": {"password":"Member@123", "role":"customer", "name":"Khách hàng demo"},
    "consultant": {"password":"Consult@123", "role":"consultant", "name":"Tư vấn viên demo"},
    "manager": {"password":"Manager@123", "role":"manager", "name":"Quản lý PT demo"},
    "pt": {"password":"Trainer@123", "role":"pt", "name":"Huấn luyện viên demo"},
    "admin": {"password":"Admin@123", "role":"admin", "name":"Quản trị viên"},
}

def _signature(payload: str) -> str:
    return hmac.new(SESSION_SECRET, payload.encode(), hashlib.sha256).hexdigest()

def _session_token(username: str) -> str:
    expiry=str(int((now_utc()+timedelta(hours=8)).timestamp()))
    payload=f"{username}|{expiry}"
    token=base64.urlsafe_b64encode(payload.encode()).decode().rstrip("=")
    return f"{token}.{_signature(token)}"

def current_user(request: Request) -> dict:
    """Đọc cookie phiên đã ký; không nhận vai trò do trình duyệt tự chọn."""
    token=request.cookies.get(SESSION_COOKIE, "")
    try:
        encoded,signature=token.rsplit(".",1)
        if not hmac.compare_digest(signature,_signature(encoded)): raise ValueError
        payload=base64.urlsafe_b64decode(encoded+"="*((4-len(encoded)%4)%4)).decode()
        username,expiry=payload.rsplit("|",1)
        if int(expiry)<int(now_utc().timestamp()): raise ValueError
        user=DEMO_USERS[username]
        return {"username":username,"role":user["role"],"name":user["name"]}
    except (ValueError,KeyError,TypeError):
        raise HTTPException(status_code=401,detail="Phiên đăng nhập không hợp lệ hoặc đã hết hạn. Vui lòng đăng nhập lại.")

def require_roles(*allowed: str):
    def dependency(user: dict=Depends(current_user)):
        if user["role"] not in allowed:
            raise HTTPException(status_code=403,detail="Bạn không có quyền thực hiện thao tác này.")
        return user
    return dependency

GOALS = {
    "WEIGHT_LOSS": ["giảm cân", "giảm mỡ", "thon gọn", "cardio", "béo", "eo thon", "xuống cân"],
    "MUSCLE_GAIN": ["tăng cơ", "tăng cân", "thể hình", "cơ bắp", "to ngực", "vai rộng", "bulk"],
    "REHAB": ["đau lưng", "thoát vị", "cổ vai gáy", "khớp", "phục hồi", "chấn thương", "yếu"],
    "GENERAL_FITNESS": ["khỏe mạnh", "dẻo dai", "xả stress", "duy trì", "sức bền", "năng động"],
}
GOAL_LABELS = {"WEIGHT_LOSS":"Giảm cân & giảm mỡ", "MUSCLE_GAIN":"Tăng cơ & thể hình", "REHAB":"Phục hồi & vận động", "GENERAL_FITNESS":"Thể lực tổng quát"}
PACKAGES = {
    "BASIC": {"name":"Basic", "monthly_price":490000, "benefits":["Tập luyện không giới hạn", "Đo chỉ số cơ thể mỗi tháng"]},
    "CLASSIC": {"name":"Classic", "monthly_price":890000, "benefits":["Tập luyện không giới hạn", "2 buổi hướng dẫn PT", "Đo chỉ số cơ thể hàng tháng"]},
    "VIP": {"name":"VIP", "monthly_price":1590000, "benefits":["Tập luyện không giới hạn", "8 buổi PT cá nhân/tháng", "Ưu tiên đặt lịch", "Đánh giá thể lực định kỳ"]},
}
PT_PACKAGES = {"CLASSIC", "VIP"}
QUESTIONS = [
    "Bạn có bệnh tim hoặc từng được chẩn đoán vấn đề tim mạch?", "Bạn có đau ngực khi nghỉ ngơi hoặc khi vận động?",
    "Bạn có thường chóng mặt, mất thăng bằng hoặc ngất?", "Bạn có vấn đề về xương khớp ảnh hưởng đến tập luyện?",
    "Bạn có huyết áp cao hoặc đang dùng thuốc huyết áp?", "Bác sĩ có khuyến cáo bạn cần giám sát y tế khi tập?",
    "Có lý do sức khỏe nào khác khiến bạn cần tư vấn trước khi tập?",
]

@contextmanager
def connection():
    """Mở và tự đóng kết nối SQLite; mọi truy vấn dùng placeholder tham số."""
    conn = sqlite3.connect(DB_PATH, timeout=15)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()

def init_db():
    """Khởi tạo 5 bảng 3NF và dữ liệu mẫu (T2, TS)."""
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    with connection() as c:
        c.executescript("""
        CREATE TABLE IF NOT EXISTS customers(customer_id INTEGER PRIMARY KEY, full_name TEXT NOT NULL, phone TEXT NOT NULL UNIQUE, email TEXT NOT NULL UNIQUE, date_of_birth TEXT, gender TEXT CHECK(gender IN ('MALE','FEMALE','OTHER')), created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP);
        CREATE TABLE IF NOT EXISTS health_surveys(survey_id INTEGER PRIMARY KEY, customer_id INTEGER NOT NULL REFERENCES customers(customer_id), parq_q1_heart_condition INTEGER NOT NULL DEFAULT 0, parq_q2_chest_pain INTEGER NOT NULL DEFAULT 0, parq_q3_dizziness INTEGER NOT NULL DEFAULT 0, parq_q4_joint_problem INTEGER NOT NULL DEFAULT 0, parq_q5_blood_pressure INTEGER NOT NULL DEFAULT 0, parq_q6_medical_supervision INTEGER NOT NULL DEFAULT 0, parq_q7_other_risk INTEGER NOT NULL DEFAULT 0, medical_alert INTEGER NOT NULL DEFAULT 0, raw_goal_text TEXT NOT NULL, predicted_goal TEXT NOT NULL, confidence_score REAL NOT NULL, ai_status TEXT NOT NULL CHECK(ai_status IN ('AUTO_ACCEPTED','MANUAL_REVIEW_T5','CONSULTANT_VERIFIED')), consultant_notes TEXT DEFAULT '', package_name TEXT, created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP);
        CREATE TABLE IF NOT EXISTS trainers(trainer_id INTEGER PRIMARY KEY, full_name TEXT NOT NULL, specialty TEXT NOT NULL, coaching_style TEXT NOT NULL, tier TEXT NOT NULL DEFAULT 'STANDARD', active_clients_count INTEGER NOT NULL DEFAULT 0, max_clients_capacity INTEGER NOT NULL DEFAULT 15, rating REAL NOT NULL DEFAULT 5.0, is_available INTEGER NOT NULL DEFAULT 1);
        CREATE TABLE IF NOT EXISTS trainer_slots(slot_id INTEGER PRIMARY KEY, trainer_id INTEGER NOT NULL REFERENCES trainers(trainer_id), session_date TEXT NOT NULL, start_time TEXT NOT NULL, end_time TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'OPEN' CHECK(status IN ('OPEN','HELD','CONFIRMED')), held_by_survey_id INTEGER REFERENCES health_surveys(survey_id), hold_expire_at TEXT, pt_note TEXT DEFAULT '', created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP, UNIQUE(trainer_id,session_date,start_time));
        CREATE TABLE IF NOT EXISTS workflow_cases(survey_id INTEGER PRIMARY KEY REFERENCES health_surveys(survey_id), current_task TEXT NOT NULL DEFAULT 'T1', status TEXT NOT NULL DEFAULT 'ACTIVE', package_name TEXT, months INTEGER, coaching_style TEXT NOT NULL DEFAULT 'MOTIVATIONAL', trainer_id INTEGER REFERENCES trainers(trainer_id), slot_id INTEGER REFERENCES trainer_slots(slot_id), match_attempts INTEGER NOT NULL DEFAULT 0, completed_tasks TEXT NOT NULL DEFAULT '[]', cancellation_reason TEXT DEFAULT '', updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP);
        CREATE TABLE IF NOT EXISTS consultation_requests(survey_id INTEGER PRIMARY KEY REFERENCES health_surveys(survey_id), requested_details TEXT NOT NULL, consultant_response TEXT DEFAULT '', status TEXT NOT NULL DEFAULT 'PENDING' CHECK(status IN ('PENDING','COMPLETED')), created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP, completed_at TEXT);
        CREATE TABLE IF NOT EXISTS contracts(contract_id INTEGER PRIMARY KEY, contract_code TEXT NOT NULL UNIQUE, customer_id INTEGER NOT NULL REFERENCES customers(customer_id), survey_id INTEGER NOT NULL REFERENCES health_surveys(survey_id), trainer_id INTEGER REFERENCES trainers(trainer_id), trainer_slot_id INTEGER REFERENCES trainer_slots(slot_id), package_name TEXT NOT NULL, total_amount INTEGER NOT NULL, status TEXT NOT NULL CHECK(status IN ('DRAFT','SIGNED','PAID','EXPIRED','CANCELLED')) DEFAULT 'DRAFT', signature_data TEXT, signed_at TEXT, slot_hold_expire_at TEXT, membership_qr_token TEXT UNIQUE, member_id TEXT UNIQUE, first_session_confirmed INTEGER NOT NULL DEFAULT 0, reminder_sent_at TEXT, created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP);
        CREATE TABLE IF NOT EXISTS payments(payment_id INTEGER PRIMARY KEY, contract_id INTEGER NOT NULL REFERENCES contracts(contract_id), transaction_ref TEXT NOT NULL UNIQUE, payment_method TEXT NOT NULL, amount INTEGER NOT NULL, payment_status TEXT NOT NULL CHECK(payment_status IN ('PENDING','SUCCESS','FAILED')), paid_at TEXT, invoice_number TEXT UNIQUE);
        """)
        # Hỗ trợ nâng cấp DB prototype bản trước, giữ lại dữ liệu đang có.
        added={}
        migrations=[("customers","date_of_birth","TEXT"),("customers","gender","TEXT"),
            ("health_surveys","parq_q6_medical_supervision","INTEGER NOT NULL DEFAULT 0"),("health_surveys","parq_q7_other_risk","INTEGER NOT NULL DEFAULT 0"),("health_surveys","package_name","TEXT"),
            ("trainers","tier","TEXT NOT NULL DEFAULT 'STANDARD'"),("trainers","active_clients_count","INTEGER NOT NULL DEFAULT 0"),("trainers","max_clients_capacity","INTEGER NOT NULL DEFAULT 15"),("trainers","is_available","INTEGER NOT NULL DEFAULT 1"),
            ("contracts","survey_id","INTEGER REFERENCES health_surveys(survey_id)"),("contracts","trainer_slot_id","INTEGER REFERENCES trainer_slots(slot_id)"),("contracts","months","INTEGER NOT NULL DEFAULT 3"),("contracts","slot_hold_expire_at","TEXT"),("contracts","membership_qr_token","TEXT"),("contracts","member_id","TEXT"),("contracts","first_session_confirmed","INTEGER NOT NULL DEFAULT 0"),("contracts","reminder_sent_at","TEXT"),
            ("payments","payment_method","TEXT NOT NULL DEFAULT 'VNPAY'"),("payments","payment_status","TEXT NOT NULL DEFAULT 'PENDING'"),("payments","invoice_number","TEXT"),
            ("workflow_cases","coaching_style","TEXT NOT NULL DEFAULT 'MOTIVATIONAL'")]
        for table,col,declaration in migrations:
            cols={r[1] for r in c.execute(f"PRAGMA table_info({table})")}
            if col not in cols:
                c.execute(f"ALTER TABLE {table} ADD COLUMN {col} {declaration}")
                added.setdefault(table,set()).add(col)
        trainer_cols={r[1] for r in c.execute("PRAGMA table_info(trainers)")}
        if "active_clients_count" in added.get("trainers",set()) and "active_clients" in trainer_cols: c.execute("UPDATE trainers SET active_clients_count=active_clients")
        if "max_clients_capacity" in added.get("trainers",set()) and "capacity" in trainer_cols: c.execute("UPDATE trainers SET max_clients_capacity=capacity")
        if "is_available" in added.get("trainers",set()) and "available" in trainer_cols: c.execute("UPDATE trainers SET is_available=available")
        contract_cols={r[1] for r in c.execute("PRAGMA table_info(contracts)")}
        if "slot_hold_expire_at" in added.get("contracts",set()) and "hold_expire_at" in contract_cols: c.execute("UPDATE contracts SET slot_hold_expire_at=hold_expire_at")
        if "membership_qr_token" in added.get("contracts",set()) and "qr_token" in contract_cols: c.execute("UPDATE contracts SET membership_qr_token=qr_token")
        payment_cols={r[1] for r in c.execute("PRAGMA table_info(payments)")}
        if "payment_method" in added.get("payments",set()) and "method" in payment_cols: c.execute("UPDATE payments SET payment_method=method")
        if "payment_status" in added.get("payments",set()) and "status" in payment_cols: c.execute("UPDATE payments SET payment_status=status")
        # Bản prototype cũ dùng bảng `surveys`; nhập dữ liệu một lần vào bảng chuẩn mới.
        legacy=c.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='surveys'").fetchone()
        if legacy and c.execute("SELECT COUNT(*) FROM health_surveys").fetchone()[0]==0:
            legacy_rows=c.execute("SELECT * FROM surveys").fetchall()
            for old in legacy_rows:
                try: answers=json.loads(old["parq_json"] or "[]")
                except (ValueError,TypeError): answers=[]
                answers=(list(answers)+[0]*7)[:7]
                old_status=old["status"] if "status" in old.keys() else "AUTO_ACCEPTED"
                ai_status=old_status if old_status in ("AUTO_ACCEPTED","MANUAL_REVIEW_T5","CONSULTANT_VERIFIED") else "AUTO_ACCEPTED"
                c.execute("INSERT OR IGNORE INTO health_surveys(survey_id,customer_id,parq_q1_heart_condition,parq_q2_chest_pain,parq_q3_dizziness,parq_q4_joint_problem,parq_q5_blood_pressure,parq_q6_medical_supervision,parq_q7_other_risk,medical_alert,raw_goal_text,predicted_goal,confidence_score,ai_status,consultant_notes) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",(old["survey_id"],old["customer_id"],*map(int,answers),int(old["medical_alert"]),old["raw_goal_text"],old["goal"],old["confidence"],ai_status,old["consultant_notes"] or ""))
                c.execute("UPDATE contracts SET survey_id=? WHERE customer_id=? AND survey_id IS NULL",(old["survey_id"],old["customer_id"]))
        # Nếu app cũ đã tạo hồ sơ mới trước khi được cập nhật, đồng bộ lại để FK cũ không chặn hợp đồng.
        if legacy:
            for survey in c.execute("SELECT * FROM health_surveys").fetchall():
                answers=[survey[f"parq_q{i}_{key}"] for i,key in enumerate(["heart_condition","chest_pain","dizziness","joint_problem","blood_pressure","medical_supervision","other_risk"],1)]
                c.execute("INSERT OR IGNORE INTO surveys(survey_id,customer_id,parq_json,medical_alert,raw_goal_text,goal,confidence,status,consultant_notes) VALUES(?,?,?,?,?,?,?,?,?)",(survey["survey_id"],survey["customer_id"],json.dumps(answers),survey["medical_alert"],survey["raw_goal_text"],survey["predicted_goal"],survey["confidence_score"],survey["ai_status"],survey["consultant_notes"] or ""))
        c.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_contract_membership_qr_unique ON contracts(membership_qr_token)")
        c.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_contract_member_id_unique ON contracts(member_id)")
        c.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_payment_invoice_unique ON payments(invoice_number)")
        if c.execute("SELECT COUNT(*) FROM trainers").fetchone()[0] == 0:
            c.executemany("INSERT INTO trainers(full_name,specialty,coaching_style,tier,active_clients_count,max_clients_capacity,rating,is_available) VALUES(?,?,?,?,?,?,?,1)", [
                ("Nguyễn Minh Khôi","WEIGHT_LOSS","MOTIVATIONAL","SENIOR",6,15,4.9),("Trần Thu Hà","MUSCLE_GAIN","STRICT","SENIOR",9,15,4.8),
                ("Lê Quốc Bảo","REHAB","GENTLE","SENIOR",5,12,5.0),("Phạm Ngọc Linh","GENERAL_FITNESS","MOTIVATIONAL","STANDARD",8,15,4.7),
                ("Võ Thanh Tùng","WEIGHT_LOSS","STRICT","STANDARD",4,15,4.8),("Đặng Mỹ Duyên","MUSCLE_GAIN","MOTIVATIONAL","STANDARD",7,15,4.9)])
        # Tạo lịch mẫu cho 21 ngày tới; mỗi ca là một slot thật có trạng thái giữ/chốt.
        trainers=c.execute("SELECT trainer_id FROM trainers WHERE is_available=1").fetchall()
        today=datetime.now().date()
        for offset in range(21):
            day=today+timedelta(days=offset)
            if day.weekday()==6: continue
            for trainer in trainers:
                c.executemany("INSERT OR IGNORE INTO trainer_slots(trainer_id,session_date,start_time,end_time,status) VALUES(?,?,?,?, 'OPEN')",[(trainer[0],day.isoformat(),start,f"{int(start[:2])+1:02d}:{start[3:]}") for start in ("08:00","10:00","14:00","16:00")])
        # Tạo tiến trình cho dữ liệu khảo sát đã có trước lần nâng cấp này.
        for survey in c.execute("SELECT survey_id,ai_status,package_name FROM health_surveys").fetchall():
            initial="T5" if survey["ai_status"]=="MANUAL_REVIEW_T5" else "T6"
            completed='["T1","T2","T3","T4"]'
            c.execute("INSERT OR IGNORE INTO workflow_cases(survey_id,current_task,status,package_name,completed_tasks) VALUES(?,?,'ACTIVE',?,?)",(survey["survey_id"],initial,survey["package_name"],completed))

def now_utc(): return datetime.now(timezone.utc)
def classify_goal_intent(raw_text: str, threshold: float = THRESHOLD):
    """T4/G1: phân loại từ khóa và rẽ nhánh theo ngưỡng truyền vào."""
    text=raw_text.lower(); scores={g:sum(word in text for word in words) for g,words in GOALS.items()}
    goal=max(scores,key=scores.get); matches=scores[goal]
    confidence=min(.85+matches*.05,.98) if matches>=2 else (.825 if matches==1 else .65)
    if matches==0: goal="GENERAL_FITNESS"
    accepted=route_by_confidence(confidence,threshold)
    return {"predicted_goal":goal,"confidence":round(confidence,3),"is_auto_accepted":accepted,"next_step":"T6_PRICING" if accepted else "T5_CONSULTANT_VERIFY","match_count":matches}

def route_by_confidence(confidence: float, threshold: float = THRESHOLD) -> bool:
    """G1: tách logic biên để chứng minh 0.820 được duyệt, 0.819 chuyển T5."""
    return confidence >= threshold

def evaluate_parq(answers):
    """T3: bật cảnh báo sức khỏe nếu có ít nhất một câu trả lời Có."""
    return any(bool(x) for x in answers)

def workflow_case(c, survey_id):
    row=c.execute("SELECT * FROM workflow_cases WHERE survey_id=?",(survey_id,)).fetchone()
    if not row: raise HTTPException(404,"Không tìm thấy tiến trình BPMN của hồ sơ")
    return row

def mark_workflow(c, survey_id, *, task=None, status=None, completed=(), **fields):
    row=workflow_case(c,survey_id)
    done=set(json.loads(row["completed_tasks"] or "[]"))
    done.update(completed)
    updates={"completed_tasks":json.dumps(sorted(done)),"updated_at":now_utc().isoformat()}
    if task is not None: updates["current_task"]=task
    if status is not None: updates["status"]=status
    updates.update(fields)
    setters=", ".join(f"{key}=?" for key in updates)
    c.execute(f"UPDATE workflow_cases SET {setters} WHERE survey_id=?",[*updates.values(),survey_id])
    return workflow_case(c,survey_id)

def current_process(c, survey_id):
    row=c.execute("""SELECT wc.*,s.predicted_goal,s.raw_goal_text,s.medical_alert,s.ai_status,s.confidence_score,
        cu.full_name,cu.phone,cu.email,co.contract_id,co.contract_code,co.status contract_status,co.package_name contract_package,
        co.months contract_months,co.total_amount,co.signature_data,co.signed_at,co.trainer_slot_id,
        COALESCE(sl.hold_expire_at,co.slot_hold_expire_at) slot_hold_expire_at,co.membership_qr_token,co.member_id,
        tr.full_name trainer_name,sl.session_date,sl.start_time,sl.end_time,sl.status slot_status,sl.pt_note,
        pay.payment_status latest_payment_status,pay.invoice_number
        FROM workflow_cases wc JOIN health_surveys s USING(survey_id)
        JOIN customers cu USING(customer_id)
        LEFT JOIN contracts co USING(survey_id)
        LEFT JOIN trainers tr ON tr.trainer_id=COALESCE(wc.trainer_id,co.trainer_id)
        LEFT JOIN trainer_slots sl ON sl.slot_id=COALESCE(wc.slot_id,co.trainer_slot_id)
        LEFT JOIN payments pay ON pay.payment_id=(SELECT MAX(p2.payment_id) FROM payments p2 WHERE p2.contract_id=co.contract_id)
        WHERE wc.survey_id=? ORDER BY co.contract_id DESC LIMIT 1""",(survey_id,)).fetchone()
    return asdict(row)

def trainer_matches(goal, style="MOTIVATIONAL", package="CLASSIC", limit=3):
    """TS: NSC có trọng số, chỉ giữ PT đạt 60 điểm và còn slot thực sự."""
    with connection() as c:
        trainers=c.execute("SELECT * FROM trainers WHERE is_available=1 AND active_clients_count < max_clients_capacity").fetchall()
        slots={t["trainer_id"]:[asdict(s) for s in c.execute("SELECT slot_id,session_date,start_time,end_time FROM trainer_slots WHERE trainer_id=? AND status='OPEN' AND session_date>=? ORDER BY session_date,start_time LIMIT 8",(t["trainer_id"],datetime.now().date().isoformat())).fetchall()] for t in trainers}
    scored=[]
    for t in trainers:
        open_slots=slots.get(t["trainer_id"],[])
        if not open_slots: continue
        parts={"goal":1.0 if t["specialty"]==goal else .4,"schedule":1.0,
               "load":max(0.0,1-t["active_clients_count"]/max(1,t["max_clients_capacity"])),
               "style":1.0 if t["coaching_style"]==style else .5,
               "budget":1.0 if (package=="VIP" and t["tier"]=="SENIOR") or (package=="CLASSIC" and t["tier"]=="STANDARD") or package=="BASIC" else .5}
        score=.30*parts["goal"]+.20*parts["schedule"]+.20*parts["load"]+.15*parts["style"]+.15*parts["budget"]
        if score < .60: continue
        scored.append({"trainer_id":t["trainer_id"],"full_name":t["full_name"],"specialty":t["specialty"],"coaching_style":t["coaching_style"],"tier":t["tier"],"rating":t["rating"],"active_clients_count":t["active_clients_count"],"max_clients_capacity":t["max_clients_capacity"],"score":round(score,4),"score_components":parts,"available_slots":open_slots})
    return sorted(scored,key=lambda x:(x["score"],x["rating"]),reverse=True)[:limit]

def asdict(row): return dict(row) if row else None
def contract_row(c, contract_id):
    row=c.execute("SELECT co.*,cu.full_name,cu.email,cu.phone,tr.full_name trainer_name,tr.specialty trainer_specialty FROM contracts co JOIN customers cu ON cu.customer_id=co.customer_id LEFT JOIN trainers tr ON tr.trainer_id=co.trainer_id WHERE co.contract_id=?",(contract_id,)).fetchone()
    if not row: raise HTTPException(404,"Không tìm thấy hợp đồng")
    return asdict(row)
def invoice(c, contract_id):
    row=c.execute("SELECT * FROM payments WHERE contract_id=? AND payment_status='SUCCESS'",(contract_id,)).fetchone()
    if row and not row["invoice_number"]: c.execute("UPDATE payments SET invoice_number=? WHERE payment_id=?",(f"AL-HD-{datetime.now().year}-{uuid.uuid4().hex[:8].upper()}",row["payment_id"]))
    return c.execute("SELECT invoice_number FROM payments WHERE contract_id=? AND payment_status='SUCCESS'",(contract_id,)).fetchone()

def activate_membership_record(c, contract_id):
    co=c.execute("SELECT * FROM contracts WHERE contract_id=?",(contract_id,)).fetchone()
    if not co: raise HTTPException(404,"Không tìm thấy hợp đồng")
    if co["status"]!="PAID": raise HTTPException(409,"Chỉ kích hoạt sau thanh toán thành công")
    if not co["membership_qr_token"]:
        c.execute("UPDATE contracts SET membership_qr_token=?,member_id=? WHERE contract_id=?",(f"ACTIVELIFE-MEMBER-{secrets.token_hex(4).upper()}",f"AL{now_utc():%y%m%d}{secrets.token_hex(3).upper()}",contract_id))
    return contract_row(c,contract_id)

def issue_invoice_record(c, contract_id):
    co=c.execute("SELECT status FROM contracts WHERE contract_id=?",(contract_id,)).fetchone()
    if not co: raise HTTPException(404,"Không tìm thấy hợp đồng")
    if co["status"]!="PAID": raise HTTPException(409,"Chỉ xuất hóa đơn sau thanh toán")
    inv=invoice(c,contract_id)
    return {"contract_id":contract_id,"invoice_number":inv[0] if inv else None,"status":"ISSUED"}

async def expiry_worker():
    """TNR nhắc sau 24h và TR_Slot giải phóng lịch hết hạn sau 48h."""
    while True:
        await asyncio.sleep(60)
        send_due_contract_reminders()
        released=release_expired_slots()
        if released: NOTIFICATION_LOG.append({"task":"TR_Slot","released":released,"at":now_utc().isoformat()})

def send_due_contract_reminders():
    """TNR: gửi log nhắc ký một lần khi hợp đồng DRAFT đã tồn tại 24 giờ."""
    cutoff=(now_utc()-timedelta(hours=24)).isoformat()
    with connection() as c:
        rows=c.execute("SELECT contract_id FROM contracts WHERE status='DRAFT' AND reminder_sent_at IS NULL AND datetime(created_at)<=datetime(?)",(cutoff,)).fetchall()
        sent_at=now_utc().isoformat()
        for row in rows:
            c.execute("UPDATE contracts SET reminder_sent_at=? WHERE contract_id=? AND reminder_sent_at IS NULL",(sent_at,row["contract_id"]))
            survey_id=c.execute("SELECT survey_id FROM contracts WHERE contract_id=?",(row["contract_id"],)).fetchone()[0]
            mark_workflow(c,survey_id,completed=("TNR",))
            NOTIFICATION_LOG.append({"task":"TNR","contract_id":row["contract_id"],"at":sent_at,"channel":"DEMO"})
    return len(rows)

@app.get("/", include_in_schema=False)
def home(): return FileResponse(ROOT/"index.html")

class LoginIn(BaseModel): username: str; password: str

@app.post("/api/auth/login",summary="AUTH: Đăng nhập và cấp phiên theo vai trò")
def login(req:LoginIn,response:Response):
    user=DEMO_USERS.get(req.username.strip().lower())
    if not user or not hmac.compare_digest(req.password,user["password"]):
        raise HTTPException(status_code=401,detail="Tên đăng nhập hoặc mật khẩu không đúng.")
    response.set_cookie(SESSION_COOKIE,_session_token(req.username.strip().lower()),httponly=True,samesite="lax",secure=False,max_age=8*60*60,path="/")
    return {"username":req.username.strip().lower(),"role":user["role"],"name":user["name"],"expires_in":8*60*60}

@app.get("/api/auth/me",summary="AUTH: Lấy người dùng và quyền hiện tại")
def auth_me(user:dict=Depends(current_user)): return user

@app.post("/api/auth/logout",summary="AUTH: Đăng xuất và hủy cookie phiên")
def logout(response:Response):
    response.delete_cookie(SESSION_COOKIE,path="/")
    return {"ok":True}

@app.get("/static/activelife-logo.png",include_in_schema=False)
def logo(): return FileResponse(ROOT/"static"/"activelife-logo.png",media_type="image/png")

@app.get("/static/app.js",include_in_schema=False)
def frontend_script(): return FileResponse(ROOT/"static"/"app.js",media_type="application/javascript")

@app.get("/api/survey/questions",summary="T1: Lấy 7 câu hỏi PAR-Q",dependencies=[Depends(require_roles("customer","admin"))])
def survey_questions(): return {"questions":QUESTIONS}

class SurveyIn(BaseModel):
    full_name:str=Field(min_length=2,max_length=100); phone:str; email:EmailStr; raw_goal_text:str=Field(min_length=3,max_length=1000)
    parq_answers:list[bool]=Field(min_length=7,max_length=7); coaching_style:str="MOTIVATIONAL"; date_of_birth:Optional[str]=None; gender:Optional[str]=None
    @field_validator("phone")
    @classmethod
    def valid_phone(cls,v):
        if not re.fullmatch(r"(?:\+?84|0)(?:3|5|7|8|9)[0-9]{8}",re.sub(r"[ .-]","",v)):
            raise ValueError("Số điện thoại Việt Nam không hợp lệ (ví dụ 0901234567)")
        return re.sub(r"[ .-]","",v)
    @field_validator("gender")
    @classmethod
    def valid_gender(cls,v):
        if v is not None and v not in ("MALE","FEMALE","OTHER"): raise ValueError("Giới tính không hợp lệ")
        return v

@app.post("/api/survey/submit",summary="T1–T4, G1: Nhận khảo sát, sàng lọc PAR-Q và phân loại mục tiêu",dependencies=[Depends(require_roles("customer","admin"))])
def submit_survey(req:SurveyIn):
    result=classify_goal_intent(req.raw_goal_text); alert=evaluate_parq(req.parq_answers); status="AUTO_ACCEPTED" if result["is_auto_accepted"] else "MANUAL_REVIEW_T5"
    with connection() as c:
        try:
            cur=c.execute("INSERT INTO customers(full_name,phone,email,date_of_birth,gender) VALUES(?,?,?,?,?)",(req.full_name.strip(),req.phone,req.email.lower(),req.date_of_birth,req.gender)); customer_id=cur.lastrowid
            cols=[f"parq_q{i}_{key}" for i,key in enumerate(["heart_condition","chest_pain","dizziness","joint_problem","blood_pressure","medical_supervision","other_risk"],1)]
            sql=f"INSERT INTO health_surveys(customer_id,{','.join(cols)},medical_alert,raw_goal_text,predicted_goal,confidence_score,ai_status) VALUES({','.join(['?']*(1+len(cols)+5))})"
            cur=c.execute(sql,[customer_id,*[int(x) for x in req.parq_answers],int(alert),req.raw_goal_text,result["predicted_goal"],result["confidence"],status]); survey_id=cur.lastrowid
            # DB cũ có thể còn FK hợp đồng -> surveys; ghi song song để khóa ngoại đó vẫn hợp lệ.
            legacy=c.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='surveys'").fetchone()
            if legacy:
                c.execute("INSERT OR IGNORE INTO surveys(survey_id,customer_id,parq_json,medical_alert,raw_goal_text,goal,confidence,status,consultant_notes) VALUES(?,?,?,?,?,?,?,?,?)",(survey_id,customer_id,json.dumps(req.parq_answers),int(alert),req.raw_goal_text,result["predicted_goal"],result["confidence"],status,""))
        except sqlite3.IntegrityError as e: raise HTTPException(409,"Email hoặc số điện thoại đã được đăng ký") from e
    with connection() as c:
        first_task="T5" if status=="MANUAL_REVIEW_T5" else "T6"
        c.execute("INSERT INTO workflow_cases(survey_id,current_task,status,coaching_style,completed_tasks,updated_at) VALUES(?,?,'ACTIVE',?,?,?)",(survey_id,first_task,req.coaching_style,json.dumps(["T1","T2","T3","T4"]),now_utc().isoformat()))
    return {"survey_id":survey_id,"customer_id":customer_id,**result,"status":status,"medical_alert":alert,"next_task":first_task}

@app.get("/api/customer/processes",summary="Tiếp tục tiến trình BPMN đã lưu",dependencies=[Depends(require_roles("customer","admin"))])
def customer_processes():
    with connection() as c:
        ids=[r[0] for r in c.execute("SELECT survey_id FROM workflow_cases ORDER BY updated_at DESC,survey_id DESC LIMIT 30").fetchall()]
        return [current_process(c,survey_id) for survey_id in ids]

@app.get("/api/consultant/pending-reviews",summary="T5: Danh sách hồ sơ cần xác nhận mục tiêu",dependencies=[Depends(require_roles("consultant","admin"))])
def pending_reviews():
    with connection() as c: rows=c.execute("SELECT s.*,cu.full_name,cu.phone,cu.email,w.current_task,w.completed_tasks FROM health_surveys s JOIN customers cu USING(customer_id) JOIN workflow_cases w USING(survey_id) WHERE ai_status='MANUAL_REVIEW_T5' ORDER BY s.survey_id DESC").fetchall()
    return [asdict(r) for r in rows]
class VerifyIn(BaseModel): goal:str; notes:str=""
@app.put("/api/consultant/verify-goal/{survey_id}",summary="T5: Tư vấn viên xác nhận mục tiêu và thể trạng",dependencies=[Depends(require_roles("consultant","admin"))])
def verify_goal(survey_id:int,req:VerifyIn):
    if req.goal not in GOALS: raise HTTPException(422,"Mục tiêu không hợp lệ")
    with connection() as c:
        cur=c.execute("UPDATE health_surveys SET predicted_goal=?,ai_status='CONSULTANT_VERIFIED',consultant_notes=? WHERE survey_id=? AND ai_status='MANUAL_REVIEW_T5'",(req.goal,req.notes,survey_id))
        if not cur.rowcount: raise HTTPException(404,"Không tìm thấy hồ sơ đang chờ xác nhận")
        legacy=c.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='surveys'").fetchone()
        if legacy: c.execute("UPDATE surveys SET goal=?,status='CONSULTANT_VERIFIED',consultant_notes=? WHERE survey_id=?",(req.goal,req.notes,survey_id))
        row=c.execute("SELECT * FROM health_surveys WHERE survey_id=?",(survey_id,)).fetchone()
        mark_workflow(c,survey_id,task="T6",completed=("T5",))
    return {"ok":True,"survey":asdict(row),"next_task":"T6"}

@app.get("/api/packages",summary="TV: Danh sách gói tập Basic, Classic, VIP",dependencies=[Depends(require_roles("customer","admin"))])
def get_packages(): return [{"id":k,**v,"durations":[1,3,6,12]} for k,v in PACKAGES.items()]
class PricingIn(BaseModel): package_name:str; months:int=Field(ge=1,le=12); goal:str="GENERAL_FITNESS"; survey_id:Optional[int]=None
@app.post("/api/pricing/calculate",summary="T6: Tính báo giá và quyền lợi gói tập",dependencies=[Depends(require_roles("customer","admin"))])
def pricing(req:PricingIn):
    if req.package_name not in PACKAGES: raise HTTPException(422,"Gói tập không hợp lệ")
    if req.months not in (1,3,6,12): raise HTTPException(422,"Thời hạn hỗ trợ: 1, 3, 6 hoặc 12 tháng")
    info=PACKAGES[req.package_name]; discount={1:0,3:.05,6:.10,12:.15}[req.months]; subtotal=info["monthly_price"]*req.months
    if req.survey_id:
        with connection() as c:
            case=workflow_case(c,req.survey_id)
            if case["current_task"] in ("T6","TV","TD"):
                mark_workflow(c,req.survey_id,task="TV",completed=("T6",),package_name=req.package_name,months=req.months)
    return {"package_name":req.package_name,"months":req.months,"monthly_price":info["monthly_price"],"discount_rate":discount,"total_amount":round(subtotal*(1-discount)),"benefits":info["benefits"],"goal":req.goal,"includes_pt":req.package_name in PT_PACKAGES}
class SelectPackageIn(BaseModel): survey_id:int; package_name:str; months:int=Field(ge=1,le=12)
@app.post("/api/packages/select",summary="TX: Ghi nhận lựa chọn gói hội viên",dependencies=[Depends(require_roles("customer","admin"))])
def select_package(req:SelectPackageIn):
    quote=pricing(PricingIn(package_name=req.package_name,months=req.months))
    with connection() as c:
        cur=c.execute("UPDATE health_surveys SET package_name=? WHERE survey_id=? AND ai_status!='MANUAL_REVIEW_T5'",(req.package_name,req.survey_id))
        if not cur.rowcount: raise HTTPException(404,"Không tìm thấy hồ sơ sẵn sàng chọn gói")
        case=workflow_case(c,req.survey_id)
        if case["current_task"] not in ("T6","TV","TD"): raise HTTPException(409,"Hồ sơ chưa ở bước chọn gói")
        next_task="TS" if req.package_name in PT_PACKAGES else "TC"
        mark_workflow(c,req.survey_id,task=next_task,completed=("T6","TV","TX"),package_name=req.package_name,months=req.months)
    return {"ok":True,"quote":quote,"next_task":next_task,"includes_pt":req.package_name in PT_PACKAGES}
class ConsultIn(BaseModel): survey_id:int; details:str=Field(min_length=2,max_length=1000)
@app.post("/api/consultant/deep-consult",summary="G2: Khách chuyển yêu cầu vào hàng đợi TD",dependencies=[Depends(require_roles("customer","admin"))])
def deep_consult(req:ConsultIn):
    with connection() as c:
        case=workflow_case(c,req.survey_id)
        if case["current_task"]!="TV": raise HTTPException(409,"Yêu cầu TD chỉ bắt đầu từ gateway G2 sau báo giá")
        c.execute("INSERT INTO consultation_requests(survey_id,requested_details,status) VALUES(?,?,'PENDING') ON CONFLICT(survey_id) DO UPDATE SET requested_details=excluded.requested_details,consultant_response='',status='PENDING',created_at=CURRENT_TIMESTAMP,completed_at=NULL",(req.survey_id,req.details))
        mark_workflow(c,req.survey_id,task="TD")
    NOTIFICATION_LOG.append({"task":"TD","survey_id":req.survey_id,"details":req.details,"at":now_utc().isoformat()}); return {"ok":True,"message":"Đã chuyển yêu cầu đến hàng đợi Tư vấn viên","next_task":"TD"}

@app.get("/api/consultant/pending-consults",summary="TD: Hàng đợi tư vấn chuyên sâu",dependencies=[Depends(require_roles("consultant","admin"))])
def pending_consults():
    with connection() as c:
        rows=c.execute("SELECT cr.survey_id,cr.requested_details,cr.created_at,s.predicted_goal,s.medical_alert,cu.full_name,cu.phone FROM consultation_requests cr JOIN health_surveys s USING(survey_id) JOIN customers cu USING(customer_id) WHERE cr.status='PENDING' ORDER BY cr.created_at").fetchall()
    return [asdict(row) for row in rows]

class ConsultCompleteIn(BaseModel): survey_id:int; response:str=Field(min_length=2,max_length=1000)
@app.post("/api/consultant/complete-consult",summary="TD: Hoàn tất tư vấn và quay lại TV",dependencies=[Depends(require_roles("consultant","admin"))])
def complete_consult(req:ConsultCompleteIn):
    with connection() as c:
        row=c.execute("SELECT status FROM consultation_requests WHERE survey_id=?",(req.survey_id,)).fetchone()
        if not row or row["status"]!="PENDING": raise HTTPException(404,"Không tìm thấy yêu cầu TD đang chờ")
        c.execute("UPDATE consultation_requests SET consultant_response=?,status='COMPLETED',completed_at=? WHERE survey_id=?",(req.response,now_utc().isoformat(),req.survey_id))
        c.execute("UPDATE health_surveys SET consultant_notes=? WHERE survey_id=?",(req.response,req.survey_id))
        mark_workflow(c,req.survey_id,task="TV",completed=("TD",))
    NOTIFICATION_LOG.append({"task":"TD","survey_id":req.survey_id,"response":req.response,"at":now_utc().isoformat()})
    return {"ok":True,"next_task":"TV","message":"Đã hoàn tất TD; hồ sơ quay lại TV."}
class LeadIn(BaseModel): survey_id:int; reason:str="Khách hàng tạm dừng đăng ký"
@app.post("/api/leads/save-drop",summary="TL: Lưu khách tiềm năng hủy quy trình",dependencies=[Depends(require_roles("customer","admin"))])
def save_lead(req:LeadIn):
    with connection() as c:
        case=workflow_case(c,req.survey_id)
        if case["current_task"] not in ("T6","TV","TD"): raise HTTPException(409,"TL chỉ nhận nhánh khách từ chối tại G2/G3, trước TX")
        mark_workflow(c,req.survey_id,task="E1",status="LEAD_SAVED",completed=("T6","TV","TL"),cancellation_reason=req.reason)
    NOTIFICATION_LOG.append({"task":"TL","survey_id":req.survey_id,"reason":req.reason,"at":now_utc().isoformat()}); return {"ok":True,"message":"Đã lưu khách tiềm năng vào CRM demo","next_task":"E1"}

class MatchIn(BaseModel): survey_id:int
@app.post("/api/matching/find-trainers",summary="TS/GA: Chấm NSC và chỉ trả PT đạt 60 điểm, còn ca trống",dependencies=[Depends(require_roles("customer","manager","admin"))])
def find_trainers(req:MatchIn):
    with connection() as c:
        case=workflow_case(c,req.survey_id)
        if case["package_name"] not in PT_PACKAGES: raise HTTPException(409,"Gói đã chọn không cần PT")
        survey=c.execute("SELECT predicted_goal FROM health_surveys WHERE survey_id=?",(req.survey_id,)).fetchone()
        if case["current_task"] not in ("TS","TA","TQ"): raise HTTPException(409,"Hồ sơ chưa đến bước ghép PT")
        matches=trainer_matches(survey["predicted_goal"],case["coaching_style"],case["package_name"])
        if matches:
            mark_workflow(c,req.survey_id,task="TQ",completed=("TS",))
        else:
            task="TA" if case["match_attempts"]<3 else "TM"
            mark_workflow(c,req.survey_id,task=task,completed=("TS","TR_Slot"))
            NOTIFICATION_LOG.append({"task":"TR_Slot","survey_id":req.survey_id,"at":now_utc().isoformat(),"reason":"Không tìm thấy PT đạt ngưỡng và còn lịch"})
    return {"matched_trainers":matches,"next_task":"TQ" if matches else task,"match_attempts":case["match_attempts"],"formula":"0.30 Goal + 0.20 Schedule + 0.20 Load + 0.15 Style + 0.15 Budget","minimum_score":60}

@app.post("/api/matching/alternative-slots",summary="TA/GB: Gợi ý PT/ca thay thế và kiểm tra số lần thử",dependencies=[Depends(require_roles("customer","manager","admin"))])
def alternatives(req:MatchIn):
    with connection() as c:
        case=workflow_case(c,req.survey_id)
        if case["current_task"]!="TA": raise HTTPException(409,"Hồ sơ chưa đến nhánh tìm phương án thay thế")
        attempts=case["match_attempts"]+1
        survey=c.execute("SELECT predicted_goal FROM health_surveys WHERE survey_id=?",(req.survey_id,)).fetchone()
        candidates=trainer_matches(survey["predicted_goal"],case["coaching_style"],case["package_name"] or "CLASSIC",limit=6)
        # TA -> GB -> M3 -> TS: quay lại chấm/lọc lần nữa trước khi khóa ca.
        next_task="TM" if attempts>=3 else "TS"
        completed=("TA",)
        mark_workflow(c,req.survey_id,task=next_task,completed=completed,match_attempts=attempts)
    return {"alternatives":candidates,"attempts":attempts,"attempts_remaining":max(0,3-attempts),"next_task":next_task,"message":"Đã xếp hạng PT theo NSC và lịch còn trống." if candidates else "Chưa có PT/ca thay thế còn trống."}

@app.get("/api/trainers/slots",summary="Danh sách ca còn trống của một PT",dependencies=[Depends(require_roles("customer","manager","admin"))])
def trainer_slots(trainer_id:int):
    with connection() as c:
        if not c.execute("SELECT 1 FROM trainers WHERE trainer_id=? AND is_available=1 AND active_clients_count<max_clients_capacity",(trainer_id,)).fetchone(): return []
        return [asdict(r) for r in c.execute("SELECT slot_id,session_date,start_time,end_time FROM trainer_slots WHERE trainer_id=? AND status='OPEN' AND session_date>=? ORDER BY session_date,start_time LIMIT 20",(trainer_id,datetime.now().date().isoformat())).fetchall()]

@app.get("/api/trainers",summary="Danh sách PT có thể phân bổ thủ công",dependencies=[Depends(require_roles("manager","admin"))])
def list_trainers():
    with connection() as c:
        return [asdict(r) for r in c.execute("SELECT trainer_id,full_name,specialty,coaching_style,tier,rating,is_available,active_clients_count,max_clients_capacity FROM trainers WHERE is_available=1 AND active_clients_count<max_clients_capacity ORDER BY full_name").fetchall()]

class HoldSlotIn(BaseModel): survey_id:int; trainer_id:int; slot_id:int
@app.post("/api/slots/hold",summary="TQ: Giữ ca PT đã chọn trong 48 giờ",dependencies=[Depends(require_roles("customer","manager","admin"))])
def hold_workflow_slot(req:HoldSlotIn):
    with connection() as c:
        case=workflow_case(c,req.survey_id)
        if case["current_task"]!="TQ": raise HTTPException(409,"Hồ sơ chưa sẵn sàng giữ ca")
        trainer=c.execute("SELECT 1 FROM trainers WHERE trainer_id=? AND is_available=1 AND active_clients_count<max_clients_capacity",(req.trainer_id,)).fetchone()
        if not trainer: raise HTTPException(409,"PT hiện không còn khả dụng")
        survey=c.execute("SELECT predicted_goal FROM health_surveys WHERE survey_id=?",(req.survey_id,)).fetchone()
        if not any(t["trainer_id"]==req.trainer_id for t in trainer_matches(survey["predicted_goal"],case["coaching_style"],case["package_name"],limit=6)): raise HTTPException(409,"PT không đạt ngưỡng ghép hoặc không còn lịch phù hợp")
        expiry=(now_utc()+timedelta(hours=48)).isoformat()
        cur=c.execute("UPDATE trainer_slots SET status='HELD',held_by_survey_id=?,hold_expire_at=? WHERE slot_id=? AND trainer_id=? AND status='OPEN' AND session_date>=?",(req.survey_id,expiry,req.slot_id,req.trainer_id,datetime.now().date().isoformat()))
        if not cur.rowcount: raise HTTPException(409,"Ca vừa được giữ bởi hồ sơ khác. Hãy chọn ca khác.")
        mark_workflow(c,req.survey_id,task="TP",completed=("TQ",),trainer_id=req.trainer_id,slot_id=req.slot_id)
        slot=asdict(c.execute("SELECT * FROM trainer_slots WHERE slot_id=?",(req.slot_id,)).fetchone())
        name=c.execute("SELECT full_name FROM trainers WHERE trainer_id=?",(req.trainer_id,)).fetchone()[0]
    return {"ok":True,"slot":slot,"trainer_name":name,"next_task":"TP"}

@app.get("/api/manager/unassigned-slots",summary="TM: Xem hồ sơ/lịch chờ phân PT thủ công",dependencies=[Depends(require_roles("manager","admin"))])
def unassigned_slots():
    with connection() as c: rows=c.execute("SELECT s.survey_id,s.customer_id,s.predicted_goal,s.medical_alert,w.package_name,w.match_attempts,w.current_task,w.completed_tasks,cu.full_name FROM workflow_cases w JOIN health_surveys s USING(survey_id) JOIN customers cu USING(customer_id) WHERE w.current_task='TM' AND w.status='ACTIVE' ORDER BY w.updated_at DESC").fetchall()
    return [asdict(r) for r in rows]
class AssignIn(BaseModel): survey_id:int; trainer_id:int; slot_id:int
@app.put("/api/manager/assign-trainer",summary="TM: Quản lý phân bổ PT thủ công",dependencies=[Depends(require_roles("manager","admin"))])
def assign_trainer(req:AssignIn):
    with connection() as c:
        case=workflow_case(c,req.survey_id)
        if case["current_task"]!="TM": raise HTTPException(409,"Chỉ hồ sơ ở Task TM mới được phân PT thủ công")
        if not c.execute("SELECT 1 FROM trainers WHERE trainer_id=? AND is_available=1 AND active_clients_count<max_clients_capacity",(req.trainer_id,)).fetchone(): raise HTTPException(409,"PT không khả dụng hoặc đã đủ tải")
        expiry=(now_utc()+timedelta(hours=48)).isoformat()
        cur=c.execute("UPDATE trainer_slots SET status='HELD',held_by_survey_id=?,hold_expire_at=? WHERE slot_id=? AND trainer_id=? AND status='OPEN' AND session_date>=?",(req.survey_id,expiry,req.slot_id,req.trainer_id,datetime.now().date().isoformat()))
        if not cur.rowcount: raise HTTPException(409,"PT hoặc ca được chọn không còn trống")
        mark_workflow(c,req.survey_id,task="TP",completed=("TM","TQ"),trainer_id=req.trainer_id,slot_id=req.slot_id)
        return {"ok":True,"next_task":"TP","slot":asdict(c.execute("SELECT * FROM trainer_slots WHERE slot_id=?",(req.slot_id,)).fetchone())}

@app.post("/api/manager/close-unassigned",summary="G_TM no: Lưu hồ sơ tiềm năng khi không bố trí được PT",dependencies=[Depends(require_roles("manager","admin"))])
def close_unassigned(req:LeadIn):
    with connection() as c:
        case=workflow_case(c,req.survey_id)
        if case["current_task"]!="TM": raise HTTPException(409,"Hồ sơ chưa ở nhánh phân bổ thủ công")
        mark_workflow(c,req.survey_id,task="E1",status="LEAD_SAVED",completed=("TM","TL"),cancellation_reason=req.reason)
    NOTIFICATION_LOG.append({"task":"TL","survey_id":req.survey_id,"reason":req.reason,"at":now_utc().isoformat()})
    return {"ok":True,"next_task":"E1"}

def insert_contract(c, survey_id, trainer_id=None, slot_id=None):
    case=workflow_case(c,survey_id)
    survey=c.execute("SELECT * FROM health_surveys WHERE survey_id=?",(survey_id,)).fetchone()
    if not survey: raise HTTPException(404,"Không tìm thấy khảo sát")
    package_name=case["package_name"] or survey["package_name"] or "BASIC"
    months=case["months"] or 3
    quote=pricing(PricingIn(package_name=package_name,months=months))
    code=f"HD-{now_utc().year}-{uuid.uuid4().hex[:8].upper()}"
    slot=c.execute("SELECT hold_expire_at FROM trainer_slots WHERE slot_id=?",(slot_id,)).fetchone() if slot_id else None
    expiry=slot["hold_expire_at"] if slot else None
    cur=c.execute("INSERT INTO contracts(contract_code,customer_id,survey_id,trainer_id,trainer_slot_id,package_name,months,total_amount,status,slot_hold_expire_at) VALUES(?,?,?,?,?,?,?,?,?,?)",(code,survey["customer_id"],survey_id,trainer_id,slot_id,package_name,months,quote["total_amount"],"DRAFT",expiry))
    contract_id=cur.lastrowid
    mark_workflow(c,survey_id,task="TSG",completed=("TC",))
    return contract_row(c,contract_id)

class ContractIn(BaseModel): survey_id:int; trainer_id:Optional[int]=None; package_name:str; months:int=Field(ge=1,le=12)
@app.post("/api/contracts/generate",summary="TC: Tạo hợp đồng DRAFT sau nhánh gói không PT hoặc PT xác nhận",dependencies=[Depends(require_roles("customer","manager","admin"))])
def create_contract(req:ContractIn):
    with connection() as c:
        case=workflow_case(c,req.survey_id)
        if case["current_task"]!="TC": raise HTTPException(409,"Chỉ tạo hợp đồng sau nhánh G3 hoặc sau khi PT xác nhận Task TP")
        if req.trainer_id is not None or req.package_name not in ("BASIC",): raise HTTPException(409,"Gói có PT phải đi qua TQ và TP; chỉ gói không PT tạo hợp đồng trực tiếp")
        if case["package_name"]!=req.package_name or case["months"]!=req.months: raise HTTPException(409,"Thông tin hợp đồng phải khớp gói đã chọn tại TX")
        if c.execute("SELECT 1 FROM contracts WHERE survey_id=? AND status IN ('DRAFT','SIGNED','PAID')",(req.survey_id,)).fetchone(): raise HTTPException(409,"Hồ sơ đã có hợp đồng đang hoạt động")
        return insert_contract(c,req.survey_id)

class PTResponseIn(BaseModel): survey_id:int; accepted:bool; note:str=""
@app.post("/api/pt/respond-schedule",summary="TP/GC: PT xác nhận hoặc từ chối lịch buổi đầu",dependencies=[Depends(require_roles("pt","admin"))])
def respond_schedule(req:PTResponseIn):
    with connection() as c:
        case=workflow_case(c,req.survey_id)
        if case["current_task"]!="TP" or not case["slot_id"] or not case["trainer_id"]: raise HTTPException(409,"Không có lịch đang chờ PT xác nhận")
        slot=c.execute("SELECT * FROM trainer_slots WHERE slot_id=? AND held_by_survey_id=? AND status='HELD'",(case["slot_id"],req.survey_id)).fetchone()
        if not slot: raise HTTPException(409,"Ca đã hết hạn hoặc được giải phóng")
        if req.accepted:
            if slot["hold_expire_at"] and slot["hold_expire_at"]<now_utc().isoformat(): raise HTTPException(409,"Thời hạn giữ ca đã hết")
            # BE_TP 48h chỉ áp dụng lúc chờ PT phản hồi. Sau khi nhận ca, slot được chốt.
            c.execute("UPDATE trainer_slots SET status='CONFIRMED',pt_note=?,hold_expire_at=NULL WHERE slot_id=?",(req.note,case["slot_id"]))
            mark_workflow(c,req.survey_id,task="TN",completed=("TP",))
            NOTIFICATION_LOG.append({"task":"TN","survey_id":req.survey_id,"trainer_id":case["trainer_id"],"slot_id":case["slot_id"],"at":now_utc().isoformat(),"channel":"DEMO"})
            mark_workflow(c,req.survey_id,task="TC",completed=("TN",))
            contract=insert_contract(c,req.survey_id,case["trainer_id"],case["slot_id"])
            return {"ok":True,"accepted":True,"next_task":"TSG","contract":contract,"message":"PT đã nhận lịch; hệ thống đã gửi TN và tạo hợp đồng TC."}
        c.execute("UPDATE trainer_slots SET status='OPEN',held_by_survey_id=NULL,hold_expire_at=NULL,pt_note=? WHERE slot_id=?",(req.note,case["slot_id"]))
        attempts=case["match_attempts"]
        next_task="TA" if attempts<3 else "TM"
        mark_workflow(c,req.survey_id,task=next_task,completed=("TP","TR_Slot"),trainer_id=None,slot_id=None)
        NOTIFICATION_LOG.append({"task":"TR_Slot","survey_id":req.survey_id,"slot_id":case["slot_id"],"at":now_utc().isoformat(),"reason":"PT từ chối lịch"})
        return {"ok":True,"accepted":False,"next_task":next_task,"attempts":attempts,"message":"Đã giải phóng ca. Hệ thống chuyển sang đề xuất lịch/PT khác hoặc quản lý phân bổ."}
def release_expired_slots():
    now=now_utc().isoformat(); released=0
    with connection() as c:
        pending=c.execute("SELECT survey_id,slot_id,match_attempts FROM workflow_cases WHERE current_task='TP' AND slot_id IN (SELECT slot_id FROM trainer_slots WHERE status='HELD' AND hold_expire_at<?)",(now,)).fetchall()
        for case in pending:
            c.execute("UPDATE trainer_slots SET status='OPEN',held_by_survey_id=NULL,hold_expire_at=NULL WHERE slot_id=?",(case["slot_id"],))
            next_task="TA" if case["match_attempts"]<3 else "TM"
            mark_workflow(c,case["survey_id"],task=next_task,completed=("TR_Slot",),trainer_id=None,slot_id=None)
            NOTIFICATION_LOG.append({"task":"TR_Slot","survey_id":case["survey_id"],"slot_id":case["slot_id"],"at":now,"reason":"Hết 48 giờ chờ PT xác nhận"})
            released+=1
        expired=c.execute("SELECT contract_id,survey_id,trainer_slot_id FROM contracts WHERE status IN ('DRAFT','SIGNED') AND slot_hold_expire_at IS NOT NULL AND slot_hold_expire_at<?",(now,)).fetchall()
        for row in expired:
            c.execute("UPDATE contracts SET status='EXPIRED' WHERE contract_id=?",(row["contract_id"],))
            if row["trainer_slot_id"]: c.execute("UPDATE trainer_slots SET status='OPEN',held_by_survey_id=NULL,hold_expire_at=NULL WHERE slot_id=?",(row["trainer_slot_id"],))
            mark_workflow(c,row["survey_id"],task="E2",status="EXPIRED",completed=("TR_Slot",))
            released+=1
        return released
@app.post("/api/slots/release-expired",summary="TR_Slot: Giải phóng slot đã hết hạn 48 giờ",dependencies=[Depends(require_roles("manager","admin"))])
def release_expired(): return {"released":release_expired_slots()}

@app.get("/api/contracts/{contract_id}",summary="TSG: Xem hợp đồng điện tử",dependencies=[Depends(require_roles("customer","manager","admin"))])
def get_contract(contract_id:int):
    with connection() as c:return contract_row(c,contract_id)
class SignIn(BaseModel): signature_data:str=Field(min_length=2,max_length=500)
@app.post("/api/contracts/{contract_id}/sign",summary="TSG: Ký hợp đồng điện tử (OTP/chữ ký demo)",dependencies=[Depends(require_roles("customer","admin"))])
def sign_contract(contract_id:int,req:SignIn):
    with connection() as c:
        cur=c.execute("UPDATE contracts SET status='SIGNED',signature_data=?,signed_at=? WHERE contract_id=? AND status='DRAFT' AND (slot_hold_expire_at IS NULL OR slot_hold_expire_at>?)",(req.signature_data,now_utc().isoformat(),contract_id,now_utc().isoformat()))
        if not cur.rowcount: raise HTTPException(409,"Hợp đồng không còn ở trạng thái có thể ký")
        survey_id=c.execute("SELECT survey_id FROM contracts WHERE contract_id=?",(contract_id,)).fetchone()[0]
        mark_workflow(c,survey_id,task="TPAY",completed=("TSG",))
    return {"ok":True,"message":"Đã ký hợp đồng"}
@app.post("/api/notifications/remind-contract",summary="TNR: Giả lập gửi nhắc ký hợp đồng",dependencies=[Depends(require_roles("customer","consultant","admin"))])
def remind_contract(contract_id:int):
    with connection() as c:
        row=c.execute("SELECT status,reminder_sent_at FROM contracts WHERE contract_id=?",(contract_id,)).fetchone()
        if not row: raise HTTPException(404,"Không tìm thấy hợp đồng")
        if row["reminder_sent_at"]: return {"ok":True,"already_sent":True,"message":"Hợp đồng này đã có log nhắc ký"}
        sent_at=now_utc().isoformat();c.execute("UPDATE contracts SET reminder_sent_at=? WHERE contract_id=?",(sent_at,contract_id))
        survey_id=c.execute("SELECT survey_id FROM contracts WHERE contract_id=?",(contract_id,)).fetchone()[0]
        mark_workflow(c,survey_id,completed=("TNR",))
        NOTIFICATION_LOG.append({"task":"TNR","contract_id":contract_id,"at":sent_at,"channel":"DEMO"})
    return {"ok":True,"message":"Đã ghi log nhắc ký (demo)"}

class CheckoutIn(BaseModel): contract_id:int; payment_method:str="VNPAY"; transaction_ref:Optional[str]=None; simulate_failure:bool=False
@app.post("/api/payments/checkout",summary="TPAY: Tạo thanh toán giả lập, có thể mô phỏng thất bại",dependencies=[Depends(require_roles("customer","admin"))])
def checkout(req:CheckoutIn):
    if req.payment_method not in ("VNPAY","MOMO","CREDIT_CARD"): raise HTTPException(422,"Phương thức thanh toán không hợp lệ")
    with connection() as c:
        co=c.execute("SELECT * FROM contracts WHERE contract_id=?",(req.contract_id,)).fetchone()
        if not co: raise HTTPException(404,"Không tìm thấy hợp đồng")
        if co["status"]!="SIGNED": raise HTTPException(409,"Hợp đồng phải được ký trước khi thanh toán")
        ref=req.transaction_ref or f"TXN_{uuid.uuid4().hex.upper()}"
        existing=c.execute("SELECT * FROM payments WHERE transaction_ref=?",(ref,)).fetchone()
        if existing: return {"status":existing["payment_status"],"transaction_ref":ref,"message":"Idempotent OK","payment":asdict(existing)}
        # TPAY chỉ tạo giao dịch; kết quả thành/bại được xử lý riêng ở TVF.
        status="PENDING"
        cols={r[1] for r in c.execute("PRAGMA table_info(payments)")}
        fields=["contract_id","transaction_ref","payment_method","amount","payment_status"]
        values=[req.contract_id,ref,req.payment_method,co["total_amount"],status]
        if "method" in cols: fields.append("method");values.append(req.payment_method)
        if "status" in cols: fields.append("status");values.append(status)
        c.execute(f"INSERT INTO payments({','.join(fields)}) VALUES({','.join(['?']*len(fields))})",values)
    return {"status":"PENDING","transaction_ref":ref,"simulate_failure":req.simulate_failure,"message":"Đã tạo giao dịch demo; TVF sẽ xác thực kết quả"}
class VerifyPaymentIn(BaseModel): transaction_ref:str; success:bool=True
@app.post("/api/payments/webhook-verify",summary="TVF: Xác nhận thanh toán idempotent và kích hoạt hội viên",dependencies=[Depends(require_roles("customer","admin"))])
def verify_payment(req:VerifyPaymentIn):
    with connection() as c:
        p=c.execute("SELECT * FROM payments WHERE transaction_ref=?",(req.transaction_ref,)).fetchone()
        if not p: raise HTTPException(404,"Không tìm thấy giao dịch")
        if p["payment_status"]=="SUCCESS": return {"status":"SUCCESS","message":"Idempotent OK","contract":contract_row(c,p["contract_id"])}
        if not req.success:
            cols={r[1] for r in c.execute("PRAGMA table_info(payments)")};updates="payment_status='FAILED'"+(",status='FAILED'" if "status" in cols else "")
            retry_url=f"/?retry_contract_id={p['contract_id']}"
            c.execute(f"UPDATE payments SET {updates} WHERE payment_id=?",(p["payment_id"],)); NOTIFICATION_LOG.append({"task":"TRP","contract_id":p["contract_id"],"retry_link":retry_url})
            survey_id=c.execute("SELECT survey_id FROM contracts WHERE contract_id=?",(p["contract_id"],)).fetchone()[0]
            mark_workflow(c,survey_id,task="TPAY",completed=("TPAY","TVF","TRP"))
            return {"status":"FAILED","retry_link":retry_url,"contract_status":c.execute("SELECT status FROM contracts WHERE contract_id=?",(p["contract_id"],)).fetchone()[0]}
        if p["payment_status"]!="PENDING": raise HTTPException(409,"Chỉ giao dịch đang chờ mới được xác thực")
        cols={r[1] for r in c.execute("PRAGMA table_info(payments)")};updates="payment_status='SUCCESS',paid_at=?"+(",status='SUCCESS'" if "status" in cols else "")
        c.execute(f"UPDATE payments SET {updates} WHERE payment_id=?",(now_utc().isoformat(),p["payment_id"]))
        c.execute("UPDATE contracts SET status='PAID' WHERE contract_id=?",(p["contract_id"],))
        trainer_id=c.execute("SELECT trainer_id FROM contracts WHERE contract_id=?",(p["contract_id"],)).fetchone()[0]
        if trainer_id: c.execute("UPDATE trainers SET active_clients_count=MIN(active_clients_count+1,max_clients_capacity) WHERE trainer_id=?",(trainer_id,))
        survey_id=c.execute("SELECT survey_id FROM contracts WHERE contract_id=?",(p["contract_id"],)).fetchone()[0]
        mark_workflow(c,survey_id,task="TCD",completed=("TPAY","TVF"))
        co=activate_membership_record(c,p["contract_id"])
        mark_workflow(c,survey_id,task="TI",completed=("TCD",))
        issued=issue_invoice_record(c,p["contract_id"])
        mark_workflow(c,survey_id,task="E3",status="COMPLETED",completed=("TI",))
        return {"status":"SUCCESS","message":"Thanh toán thành công; TCD đã kích hoạt thẻ, TI đã xuất hóa đơn","contract":co,"invoice_number":issued["invoice_number"]}
@app.post("/api/payments/retry-link",summary="TRP: Ghi log và trả liên kết thanh toán lại",dependencies=[Depends(require_roles("customer","consultant","admin"))])
def retry_link(contract_id:int):
    with connection() as c:
        row=c.execute("SELECT survey_id,status FROM contracts WHERE contract_id=?",(contract_id,)).fetchone()
        if not row: raise HTTPException(404,"Không tìm thấy hợp đồng")
        if row["status"]!="SIGNED": raise HTTPException(409,"Chỉ gửi link lại cho hợp đồng đã ký")
        mark_workflow(c,row["survey_id"],task="TPAY",completed=("TRP",))
    url=f"/?retry_contract_id={contract_id}"; NOTIFICATION_LOG.append({"task":"TRP","contract_id":contract_id,"retry_link":url,"at":now_utc().isoformat()}); return {"ok":True,"retry_link":url,"message":"Đã ghi log gửi link thanh toán lại"}
@app.post("/api/membership/activate",summary="TCD: Kích hoạt thẻ hội viên và cấp QR token",dependencies=[Depends(require_roles("customer","admin"))])
def activate_membership(contract_id:int):
    with connection() as c:
        row=c.execute("SELECT survey_id FROM contracts WHERE contract_id=?",(contract_id,)).fetchone()
        if not row: raise HTTPException(404,"Không tìm thấy hợp đồng")
        co=activate_membership_record(c,contract_id)
        mark_workflow(c,row["survey_id"],task="TI",completed=("TCD",))
        return co
@app.get("/api/membership/qr/{token}",summary="TCD: Ảnh QR check-in từ token hội viên",dependencies=[Depends(require_roles("customer","pt","admin"))])
def membership_qr(token:str):
    with connection() as c:
        ok=c.execute("SELECT 1 FROM contracts WHERE membership_qr_token=? AND status='PAID'",(token,)).fetchone()
        if not ok: raise HTTPException(404,"QR hội viên không hợp lệ")
    import qrcode
    image=qrcode.make(token); from io import BytesIO
    stream=BytesIO();image.save(stream,format="PNG");stream.seek(0);return StreamingResponse(stream,media_type="image/png",headers={"Cache-Control":"no-store"})
@app.post("/api/invoices/generate",summary="TI: Xuất hóa đơn điện tử demo",dependencies=[Depends(require_roles("customer","admin"))])
def generate_invoice(contract_id:int):
    with connection() as c:
        row=c.execute("SELECT survey_id FROM contracts WHERE contract_id=?",(contract_id,)).fetchone()
        if not row: raise HTTPException(404,"Không tìm thấy hợp đồng")
        result=issue_invoice_record(c,contract_id)
        mark_workflow(c,row["survey_id"],task="E3",status="COMPLETED",completed=("TI",))
        return result
@app.post("/api/notifications/notify-schedule",summary="TN: Giả lập thông báo PT và lịch buổi đầu",dependencies=[Depends(require_roles("customer","admin"))])
def notify_schedule(contract_id:int):
    NOTIFICATION_LOG.append({"task":"TN","contract_id":contract_id,"at":now_utc().isoformat()});return {"ok":True,"message":"Đã ghi log thông báo PT và khách hàng"}
@app.get("/api/pt/schedule",summary="TP: Lịch học viên mới và cảnh báo sức khỏe",dependencies=[Depends(require_roles("pt","admin"))])
def pt_schedule():
    with connection() as c: rows=c.execute("""SELECT wc.survey_id,wc.completed_tasks,co.contract_id,co.contract_code,co.first_session_confirmed,
        cu.full_name,s.predicted_goal,s.medical_alert,tr.full_name trainer_name,wc.current_task,
        CASE WHEN wc.current_task='TP' THEN 'WAITING_PT' ELSE 'CONFIRMED' END schedule_status,
        sl.slot_id,sl.session_date,sl.start_time,sl.end_time,sl.status slot_status,sl.hold_expire_at,sl.pt_note
        FROM workflow_cases wc JOIN health_surveys s USING(survey_id)
        JOIN customers cu ON cu.customer_id=s.customer_id JOIN trainers tr ON tr.trainer_id=wc.trainer_id
        JOIN trainer_slots sl ON sl.slot_id=wc.slot_id
        LEFT JOIN contracts co USING(survey_id)
        WHERE wc.current_task='TP' OR sl.status='CONFIRMED'
        ORDER BY sl.session_date,sl.start_time""").fetchall()
    return [asdict(r) for r in rows]
class CancelIn(BaseModel): contract_id:Optional[int]=None; survey_id:Optional[int]=None; reason:str="Khách hàng yêu cầu hủy"
@app.post("/api/cancellation/process",summary="ES1/ES2: Hủy hợp đồng và giải phóng PT",dependencies=[Depends(require_roles("customer","manager","admin"))])
def cancellation(req:CancelIn):
    with connection() as c:
        if not req.contract_id and not req.survey_id: raise HTTPException(422,"Cần mã hồ sơ hoặc mã hợp đồng")
        contract=c.execute("SELECT survey_id,trainer_slot_id,status FROM contracts WHERE contract_id=?",(req.contract_id,)).fetchone() if req.contract_id else None
        survey_id=contract["survey_id"] if contract else req.survey_id
        if contract and contract["status"]=="PAID": raise HTTPException(409,"Hợp đồng đã thanh toán, không thể hủy bằng luồng demo này")
        # ESP theo BPMN: ES1 giải phóng lịch PT, sau đó ES2 lưu lý do hủy.
        if contract and contract["trainer_slot_id"]: c.execute("UPDATE trainer_slots SET status='OPEN',held_by_survey_id=NULL,hold_expire_at=NULL WHERE slot_id=?",(contract["trainer_slot_id"],))
        case=workflow_case(c,survey_id)
        if case["slot_id"]: c.execute("UPDATE trainer_slots SET status='OPEN',held_by_survey_id=NULL,hold_expire_at=NULL WHERE slot_id=?",(case["slot_id"],))
        if contract: c.execute("UPDATE contracts SET status='CANCELLED' WHERE contract_id=?",(req.contract_id,))
        mark_workflow(c,survey_id,task="ESe",status="CANCELLED",completed=("ES1","ES2"),cancellation_reason=req.reason,slot_id=None,trainer_id=None)
    NOTIFICATION_LOG.append({"task":"ES1","contract_id":req.contract_id,"survey_id":survey_id,"at":now_utc().isoformat(),"detail":"Đã giải phóng lịch PT nếu có"})
    NOTIFICATION_LOG.append({"task":"ES2","contract_id":req.contract_id,"survey_id":survey_id,"reason":req.reason,"at":now_utc().isoformat()})
    return {"ok":True,"message":"Đã giải phóng lịch PT (ES1) và ghi nhận lý do hủy (ES2)"}

@app.post("/api/contracts/{contract_id}/decline",summary="GD no: Không ký, giải phóng PT nếu có và kết thúc E2",dependencies=[Depends(require_roles("customer","admin"))])
def decline_contract(contract_id:int):
    with connection() as c:
        co=c.execute("SELECT survey_id,trainer_slot_id,status FROM contracts WHERE contract_id=?",(contract_id,)).fetchone()
        if not co or co["status"]!="DRAFT": raise HTTPException(409,"Chỉ có thể từ chối hợp đồng chưa ký")
        if co["trainer_slot_id"]:
            c.execute("UPDATE trainer_slots SET status='OPEN',held_by_survey_id=NULL,hold_expire_at=NULL WHERE slot_id=?",(co["trainer_slot_id"],))
            mark_workflow(c,co["survey_id"],task="E2",status="NOT_SIGNED",completed=("TSG","TR","E2"))
        else:
            mark_workflow(c,co["survey_id"],task="E2",status="NOT_SIGNED",completed=("TSG","E2"))
        c.execute("UPDATE contracts SET status='CANCELLED' WHERE contract_id=?",(contract_id,))
    return {"ok":True,"message":"Đã ghi nhận không ký hợp đồng và kết thúc quy trình E2"}
@app.get("/api/admin/overview",summary="Admin: Tổng quan hợp đồng, hội viên, thanh toán và PT",dependencies=[Depends(require_roles("admin"))])
def admin_overview():
    with connection() as c:
        return {"customers":c.execute("SELECT COUNT(*) FROM customers").fetchone()[0],"surveys":c.execute("SELECT COUNT(*) FROM health_surveys").fetchone()[0],"members":c.execute("SELECT COUNT(*) FROM contracts WHERE status='PAID'").fetchone()[0],"pending_reviews":c.execute("SELECT COUNT(*) FROM health_surveys WHERE ai_status='MANUAL_REVIEW_T5'").fetchone()[0],"payments":[asdict(r) for r in c.execute("SELECT * FROM payments ORDER BY payment_id DESC LIMIT 20").fetchall()],"trainers":[asdict(r) for r in c.execute("SELECT * FROM trainers ORDER BY trainer_id").fetchall()],"packages":[{"id":k,**v} for k,v in PACKAGES.items()]}
class PackageAdminIn(BaseModel): monthly_price:int=Field(gt=0); benefits:list[str]
@app.put("/api/admin/packages/{package_name}",summary="Admin: Cấu hình giá và quyền lợi gói tập",dependencies=[Depends(require_roles("admin"))])
def admin_update_package(package_name:str,req:PackageAdminIn):
    if package_name not in PACKAGES: raise HTTPException(404,"Không tìm thấy gói tập")
    PACKAGES[package_name]["monthly_price"]=req.monthly_price;PACKAGES[package_name]["benefits"]=req.benefits
    return {"ok":True,"package":{"id":package_name,**PACKAGES[package_name]}}
class TrainerAdminIn(BaseModel): is_available:bool; tier:str
@app.put("/api/admin/trainers/{trainer_id}",summary="Admin: Cập nhật trạng thái và hạng huấn luyện viên",dependencies=[Depends(require_roles("admin"))])
def admin_update_trainer(trainer_id:int,req:TrainerAdminIn):
    if req.tier not in ("STANDARD","SENIOR"): raise HTTPException(422,"Hạng PT không hợp lệ")
    with connection() as c:
        cur=c.execute("UPDATE trainers SET is_available=?,tier=? WHERE trainer_id=?",(int(req.is_available),req.tier,trainer_id))
        if not cur.rowcount: raise HTTPException(404,"Không tìm thấy huấn luyện viên")
    return {"ok":True}
@app.get("/api/notifications/log",summary="Admin: Nhật ký các Send Task giả lập",dependencies=[Depends(require_roles("admin"))])
def notification_log(): return NOTIFICATION_LOG[-100:]

if __name__=="__main__":
    import uvicorn
    uvicorn.run("main:app",host="127.0.0.1",port=8000,reload=True)
