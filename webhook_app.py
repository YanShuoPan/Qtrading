# webhook_app.py (verbose)
import os, hmac, hashlib, base64, json, sqlite3, logging
from fastapi import FastAPI, Request, Header, HTTPException

# 可選：讀 .env
try:
    from dotenv import load_dotenv
    load_dotenv()
except Exception:
    pass

# 讓所有 logger（含我們自訂 + uvicorn）都印到主控台
logging.basicConfig(level=logging.DEBUG, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("webhook")

app = FastAPI()

CHANNEL_SECRET = os.environ.get("LINE_CHANNEL_SECRET")
if not CHANNEL_SECRET:
    log.warning("⚠️ LINE_CHANNEL_SECRET 未設定，簽章驗證會失敗。")
else:
    CHANNEL_SECRET = CHANNEL_SECRET.encode("utf-8")

DB_PATH = os.environ.get("DB_PATH", "data/taiex.sqlite")

def ensure_users_table():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS subscribers (
              user_id TEXT PRIMARY KEY,
              display_name TEXT,
              followed_at TEXT,
              active INTEGER DEFAULT 1
            )
        """)
        conn.commit()

def add_or_activate_user(user_id: str):
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute("""
          INSERT INTO subscribers(user_id, display_name, followed_at, active)
          VALUES(?, NULL, datetime('now'), 1)
          ON CONFLICT(user_id) DO UPDATE SET active=1
        """, (user_id,))
        conn.commit()

def deactivate_user(user_id: str):
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute("UPDATE subscribers SET active=0 WHERE user_id=?", (user_id,))
        conn.commit()

def verify_signature(raw_body: bytes, x_line_signature: str) -> bool:
    mac = hmac.new(CHANNEL_SECRET, raw_body, hashlib.sha256).digest()
    expected = base64.b64encode(mac).decode("utf-8")
    return hmac.compare_digest(expected, x_line_signature)

@app.post("/webhook")
async def webhook(
    request: Request,
    x_line_signature: str = Header(alias="X-Line-Signature", default="")
):
    # 讀 headers + body，全部印出（先印，再驗簽方便除錯）
    headers = dict(request.headers)
    raw = await request.body()
    log.debug(f"📥 Headers: {json.dumps({k:v for k,v in headers.items() if k.lower()!='authorization'}, ensure_ascii=False)}")
    log.debug(f"📦 Raw body: {raw.decode('utf-8', errors='ignore')}")

    if not CHANNEL_SECRET:
        raise HTTPException(status_code=500, detail="Server misconfigured: LINE_CHANNEL_SECRET not set")

    # 簽章驗證（失敗直接 400）
    if not verify_signature(raw, x_line_signature):
        log.error("❌ Signature verify failed")
        raise HTTPException(status_code=400, detail="Invalid signature")

    body = json.loads(raw.decode("utf-8"))
    events = body.get("events", [])
    log.info(f"✅ Webhook received {len(events)} event(s)")

    ensure_users_table()

    for i, ev in enumerate(events):
        etype = ev.get("type")
        src = ev.get("source", {})
        uid = src.get("userId")
        msg = ev.get("message", {})
        text = msg.get("text")

        log.info(f"  • [{i}] type={etype}, userId={uid}, text={text}")

        if etype == "follow" and uid:
            add_or_activate_user(uid)
            log.info(f"  → FOLLOW stored: {uid}")

        elif etype == "unfollow" and uid:
            deactivate_user(uid)
            log.info(f"  → UNFOLLOW deactivated: {uid}")

        elif etype == "message" and uid:
            # 收到任何訊息就視為訂閱（可自行加 START/STOP 關鍵字）
            add_or_activate_user(uid)
            log.info(f"  → MESSAGE stored/activated: {uid}")

        else:
            log.debug(f"  → other event payload: {json.dumps(ev, ensure_ascii=False)}")

    return {"ok": True}
