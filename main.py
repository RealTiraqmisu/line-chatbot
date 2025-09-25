"""
LINE Bot ที่ใช้ Google Generative AI (Gemini) สำหรับการตอบกลับข้อความอัตโนมัติ
ระบบนี้ใช้ FastAPI เป็น web framework และเชื่อมต่อกับ LINE Messaging API
โดยใช้ Google ADK (Agent Development Kit) สำหรับการสร้าง AI Agent
"""

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
import os
import asyncio
import time
import sqlite3
import json
import re
import urllib.request
import urllib.error
from dotenv import load_dotenv
from google.adk import Agent  # Google Agent Development Kit
from google.adk.tools.mcp_tool import McpToolset  # Multi-Channel Platform Toolset
from google.adk.tools.mcp_tool.mcp_toolset import StdioConnectionParams, StdioServerParameters
from google.adk.runners import Runner  # ใช้สำหรับรัน Agent
from google.adk.sessions import InMemorySessionService  # จัดการ session ของ Agent
from google.genai.types import Content, Part  # สำหรับสร้าง content ให้ Agent
from pydantic import BaseModel  # สำหรับสร้าง data model
from typing import List, Dict, Any, Optional  # type hints
from mcp.shared.exceptions import McpError  # จัดการ error จาก MCP


# โหลดค่า environment variables จากไฟล์ .env
load_dotenv()


# สร้าง FastAPI application
app = FastAPI(title="LINE Bot with Google Generative AI")


# ตัวแปรสำหรับการเชื่อมต่อกับ LINE API
LINE_CHANNEL_ACCESS_TOKEN = (os.getenv("LINE_CHANNEL_ACCESS_TOKEN"))  # Token สำหรับเข้าถึง LINE API
LINE_CHANNEL_SECRET = (os.getenv("LINE_CHANNEL_SECRET"))  # Secret key สำหรับตรวจสอบความถูกต้องของ webhook
DESTINATION_USER_ID = (os.getenv("DESTINATION_USER_ID"))  # User ID ปลายทางสำหรับส่งข้อความ
GOOGLE_API_KEY = (os.getenv("GOOGLE_API_KEY"))  # API Key สำหรับเข้าถึง Google Generative AI


APP_NAME = "mcp-line-bot"  # ชื่อแอปพลิเคชันสำหรับ MCP


def create_campaign_agent():
    """
    สร้าง Campaign Agent และ Runner สำหรับการทำงานกับ LINE Bot
    
    ฟังก์ชันนี้จะสร้าง Agent ที่ใช้ Gemini model และเชื่อมต่อกับ LINE Bot MCP Server
    เพื่อให้สามารถส่งข้อความไปยัง LINE ได้
    
    Returns:
        Runner: Runner object ที่ใช้สำหรับรัน Agent
        
    Raises:
        RuntimeError: เมื่อไม่มีการตั้งค่า LINE_CHANNEL_ACCESS_TOKEN, DESTINATION_USER_ID หรือ GOOGLE_API_KEY
    """

    if not LINE_CHANNEL_ACCESS_TOKEN or not DESTINATION_USER_ID:
        raise RuntimeError("Missing LINE_CHANNEL_ACCESS_TOKEN or DESTINATION_USER_ID for MCP server")

    if not GOOGLE_API_KEY:
        raise RuntimeError("Missing GOOGLE_API_KEY for Google Generative AI")

    # ตั้งค่า Google API Key สำหรับ Google ADK
    os.environ["GOOGLE_API_KEY"] = GOOGLE_API_KEY

    # กำหนดคำสั่ง npx ให้เหมาะสมกับระบบปฏิบัติการ
    npx_command = "npx.cmd" if os.name == "nt" else "npx"


    # สร้าง MCP Toolset สำหรับเชื่อมต่อกับ LINE Bot Server
    line_bot_server_mcp_toolset = McpToolset(
    connection_params=StdioConnectionParams(
        server_params=StdioServerParameters(
            command=npx_command, 
            args=[
                "-y",
                "@line/line-bot-mcp-server",
            ],
            env={
                "CHANNEL_ACCESS_TOKEN": LINE_CHANNEL_ACCESS_TOKEN,
                # ไม่ต้องกำหนด DESTINATION_USER_ID เพื่อให้ส่งข้อความไปยังผู้ใช้ที่ส่งข้อความมา
                # "DESTINATION_USER_ID": DESTINATION_USER_ID
            },
        ),
        timeout=30.0  # เพิ่ม timeout เป็น 30 วินาที
    )
)
    

    agent = Agent(
        name="campaign_agent",
        model="gemini-2.0-flash",
        instruction="""คุณคือผู้ช่วยทำแคมเปญการตลาดสำหรับ LINE OA

กติกาสำคัญ (สั้น กระชับ):
- ให้พยายามเรียกเครื่องมือ push_text_message / push_flex_message ก่อนเสมอ โดยไม่ต้องระบุ userId (ระบบจะส่งไปยังผู้ใช้ที่ส่งข้อความมาโดยอัตโนมัติ)
- ถ้าเครื่องมือไม่พร้อม/ไม่แน่ใจ/บริบทไม่อนุญาต ให้ส่งออบเจกต์ JSON แบบนี้เท่านั้น:
  ```json
  { "type": "text", "text": "<ข้อความ>" }
  ```
  หรือ Flex:
  ```json
  { "type": "flex", "altText": "<สรุปสั้น>", "contents": { "type": "bubble|carousel", ... } }
  ```
- ห้ามส่งข้อความธรรมดาพร้อมกับ JSON ในคำตอบเดียวกัน
- ใช้ภาษาไทย สุภาพ ขี้เล่น เป็นธรรมชาติ
- สำคัญ: ไม่ต้องกังวลเรื่อง userId เพราะระบบจะจัดการให้อัตโนมัติ

แนวทางใช้งาน:
- สื่อสารทั่วไป/ถามยืนยัน ใช้ push_text_message หรือส่ง type=text
- นำเสนอโปรฯ/สินค้า ใช้ push_flex_message หรือส่ง type=flex (ต้องมี altText และ contents ครบ)
- ถ้าไม่มั่นใจโครงสร้าง Flex ให้ถามยืนยันก่อนด้วย push_text_message
""",
        tools=[line_bot_server_mcp_toolset],

    )
    

    session_service = InMemorySessionService()
    runner = Runner(agent=agent, app_name=APP_NAME, session_service=session_service)
    return runner

class LineMessage(BaseModel):
    """
    โมเดลสำหรับข้อความจาก LINE
    
    Attributes:
        type: ประเภทของข้อความ (เช่น text, image, video)
        text: เนื้อหาข้อความ (ถ้าเป็นประเภท text)
    """
    type: str
    text: Optional[str] = None

class LineEvent(BaseModel):
    """
    โมเดลสำหรับเหตุการณ์จาก LINE
    
    Attributes:
        type: ประเภทของเหตุการณ์ (เช่น message, follow, unfollow)
        message: ข้อความที่ได้รับ (ถ้าเป็นเหตุการณ์ประเภท message)
        replyToken: โทเค็นสำหรับตอบกลับข้อความ
        source: ข้อมูลแหล่งที่มาของเหตุการณ์ (เช่น user, group)
    """
    type: str
    message: Optional[LineMessage] = None
    replyToken: str
    source: Dict[str, Any]

class LineWebhookRequest(BaseModel):
    """
    โมเดลสำหรับคำขอ webhook จาก LINE
    
    Attributes:
        events: รายการเหตุการณ์ที่เกิดขึ้น
    """
    events: List[LineEvent]





RUNNER = None  # ตัวแปรสำหรับเก็บ Runner ของ Agent


# ค่าคงที่สำหรับการป้องกันการประมวลผลข้อความซ้ำ
DEDUP_TTL_SECONDS = 300  # 5 minutes
DEDUP_CACHE: Dict[str, float] = {}  # แคชสำหรับเก็บข้อมูลการป้องกันการประมวลผลซ้ำ


# พาธของไฟล์ฐานข้อมูล SQLite สำหรับเก็บข้อมูลการป้องกันการประมวลผลซ้ำ
DEDUP_DB_PATH = os.path.join(os.path.dirname(__file__), "dedup_cache.sqlite3")


# พาธของไฟล์ฐานข้อมูล SQLite สำหรับเก็บประวัติการสนทนา
MEMORY_DB_PATH = os.path.join(os.path.dirname(__file__), "memory.sqlite3")

def _memory_init():
    """
    สร้างตารางฐานข้อมูลสำหรับเก็บประวัติการสนทนา
    
    ฟังก์ชันนี้จะสร้างตาราง memory และดัชนีสำหรับการค้นหาข้อมูลอย่างมีประสิทธิภาพ
    """
    try:
        conn = sqlite3.connect(MEMORY_DB_PATH)
        with conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS memory (
                    user_id TEXT,
                    role    TEXT,
                    text    TEXT,
                    ts      REAL
                )
                """
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_memory_user_ts ON memory(user_id, ts)"
            )
    except Exception as e:
        print(f"[MEMORY][WARN] init failed: {e}")

def memory_add_message(user_id: str, role: str, text: str) -> None:
    """
    เพิ่มข้อความใหม่ลงในประวัติการสนทนา
    
    Args:
        user_id: ID ของผู้ใช้
        role: บทบาทของผู้ส่งข้อความ (user หรือ bot)
        text: เนื้อหาข้อความ
    """
    try:
        conn = sqlite3.connect(MEMORY_DB_PATH)
        with conn:
            conn.execute(
                "INSERT INTO memory(user_id, role, text, ts) VALUES(?, ?, ?, ?)",
                (user_id, role, text or "", time.time()),
            )
    except Exception as e:
        print(f"[MEMORY][WARN] add failed: {e}")

def memory_get_recent(user_id: str, limit: int = 8):
    """
    ดึงข้อความล่าสุดจากประวัติการสนทนา
    
    Args:
        user_id: ID ของผู้ใช้
        limit: จำนวนข้อความสูงสุดที่ต้องการดึง
        
    Returns:
        list: รายการข้อความล่าสุด เรียงตามเวลา (เก่าไปใหม่)
    """
    try:
        conn = sqlite3.connect(MEMORY_DB_PATH)
        with conn:
            rows = conn.execute(
                "SELECT role, text FROM memory WHERE user_id=? ORDER BY ts DESC LIMIT ?",
                (user_id, limit),
            ).fetchall()
        
        return list(reversed(rows))
    except Exception as e:
        print(f"[MEMORY][WARN] get failed: {e}")
        return []

def build_memory_context(user_id: str, limit: int = 8) -> Optional[str]:
    """
    สร้างข้อความบริบทจากประวัติการสนทนา
    
    Args:
        user_id: ID ของผู้ใช้
        limit: จำนวนข้อความสูงสุดที่ต้องการใช้
        
    Returns:
        str หรือ None: ข้อความบริบทที่สร้างขึ้น หรือ None ถ้าไม่มีข้อมูล
    """
    rows = memory_get_recent(user_id, limit=limit)
    if not rows:
        return None
    lines = []
    for role, text in rows:
        if not text:
            continue
        prefix = "ผู้ใช้" if (role or "").lower() == "user" else "บอท"
        t = str(text).strip()
        if len(t) > 300:
            t = t[:300] + "..."
        lines.append(f"{prefix}: {t}")
    if not lines:
        return None
    return "บริบทก่อนหน้า (สรุปย่อ):\n" + "\n".join(lines)


_memory_init()


# ระยะเวลาในการจำกัดการใช้งานของผู้ใช้ (วินาที)
RUNNING_TTL_SECONDS = 12
# Dictionary เก็บข้อมูลผู้ใช้ที่กำลังใช้งานระบบ โดยมี key เป็น user_id และ value เป็นเวลาที่เริ่มใช้งาน
RUNNING_USERS: Dict[str, float] = {}

def _user_throttled(user_id: str) -> bool:
    """
    ตรวจสอบว่าผู้ใช้ถูกจำกัดการใช้งานหรือไม่ (throttling)
    
    ฟังก์ชันนี้จะตรวจสอบว่าผู้ใช้ได้ส่งคำขอมาก่อนหน้านี้ภายในระยะเวลาที่กำหนดหรือไม่
    และทำการลบผู้ใช้ที่หมดเวลาจำกัดออกจากรายการ
    
    Args:
        user_id: ID ของผู้ใช้ที่ต้องการตรวจสอบ
        
    Returns:
        bool: True ถ้าผู้ใช้ถูกจำกัดการใช้งาน, False ถ้าสามารถใช้งานได้
    """
    now = time.time()
    
    # ลบผู้ใช้ที่หมดเวลาจำกัดออกจากรายการ
    expired = [u for u, ts in RUNNING_USERS.items() if (now - ts) > RUNNING_TTL_SECONDS]
    for u in expired:
        RUNNING_USERS.pop(u, None)
    
    # ตรวจสอบว่าผู้ใช้อยู่ในรายการจำกัดหรือไม่
    if user_id in RUNNING_USERS and (now - RUNNING_USERS[user_id]) <= RUNNING_TTL_SECONDS:
        return True
    
    # บันทึกเวลาล่าสุดที่ผู้ใช้ส่งคำขอ
    RUNNING_USERS[user_id] = now
    return False


def _dedup_seen(key: str) -> bool:
    """
    ตรวจสอบว่าข้อมูลซ้ำหรือไม่ (deduplication)
    
    ฟังก์ชันนี้จะตรวจสอบว่า key ที่ระบุเคยถูกบันทึกไว้ในแคชหรือไม่
    และทำการลบ key ที่หมดอายุออกจากแคช
    
    Args:
        key: คีย์ที่ใช้ในการตรวจสอบความซ้ำซ้อน
        
    Returns:
        bool: True ถ้าพบว่าข้อมูลซ้ำ (เคยเห็นมาก่อน), False ถ้าไม่ซ้ำ
    """
    now = time.time()
    
    # ลบคีย์ที่หมดอายุออกจากแคช
    expired = [k for k, ts in DEDUP_CACHE.items() if (now - ts) > DEDUP_TTL_SECONDS]
    for k in expired:
        try:
            del DEDUP_CACHE[k]
        except KeyError:
            pass
    
    # ตรวจสอบว่าคีย์อยู่ในแคชหรือไม่
    if key in DEDUP_CACHE and (now - DEDUP_CACHE[key]) <= DEDUP_TTL_SECONDS:
        return True
    # บันทึกคีย์ลงในแคชพร้อมเวลาปัจจุบัน
    DEDUP_CACHE[key] = now
    return False


def _dedup_seen_db(key: str) -> bool:
    """
    ตรวจสอบว่าข้อมูลซ้ำหรือไม่โดยใช้ฐานข้อมูล SQLite (deduplication with persistent storage)
    
    ฟังก์ชันนี้จะตรวจสอบว่า key ที่ระบุเคยถูกบันทึกไว้ในฐานข้อมูลหรือไม่
    และทำการลบ key ที่หมดอายุออกจากฐานข้อมูล
    
    Args:
        key: คีย์ที่ใช้ในการตรวจสอบความซ้ำซ้อน
        
    Returns:
        bool: True ถ้าพบว่าข้อมูลซ้ำ (เคยเห็นมาก่อน), False ถ้าไม่ซ้ำ
    """
    try:
        # เชื่อมต่อกับฐานข้อมูล SQLite
        conn = sqlite3.connect(DEDUP_DB_PATH)
        with conn:
            # สร้างตารางถ้ายังไม่มี
            conn.execute("CREATE TABLE IF NOT EXISTS dedup (key TEXT PRIMARY KEY, ts REAL)")
            # ลบข้อมูลที่หมดอายุ
            cutoff = time.time() - DEDUP_TTL_SECONDS
            conn.execute("DELETE FROM dedup WHERE ts < ?", (cutoff,))
            try:
                # พยายามเพิ่มข้อมูลใหม่
                conn.execute("INSERT INTO dedup(key, ts) VALUES(?, ?)", (key, time.time()))
                # ถ้าเพิ่มสำเร็จ แสดงว่าไม่มีข้อมูลซ้ำ
                return False
            except sqlite3.IntegrityError:
                # เกิด IntegrityError เนื่องจากมี key ซ้ำ
                # ตรวจสอบเวลาของข้อมูลที่มีอยู่
                row = conn.execute("SELECT ts FROM dedup WHERE key=?", (key,)).fetchone()
                if row is None:
                    # ไม่พบข้อมูล (อาจถูกลบไปแล้ว) ให้เพิ่มใหม่
                    conn.execute("REPLACE INTO dedup(key, ts) VALUES(?, ?)", (key, time.time()))
                    return False
                if (time.time() - float(row[0])) <= DEDUP_TTL_SECONDS:
                    # ข้อมูลยังไม่หมดอายุ ถือว่าซ้ำ
                    return True
                
                # ข้อมูลหมดอายุแล้ว อัปเดตเวลาและถือว่าไม่ซ้ำ
                conn.execute("REPLACE INTO dedup(key, ts) VALUES(?, ?)", (key, time.time()))
                return False
    except Exception as e:
        # กรณีเกิดข้อผิดพลาดในการใช้ฐานข้อมูล ให้ใช้แคชในหน่วยความจำแทน
        print(f"[DEDUP][WARN] persistent DB failed: {e}")
        return _dedup_seen(key)

def get_runner():
    """
    สร้างหรือเรียกใช้ Runner ที่มีอยู่แล้ว
    
    ฟังก์ชันนี้จะตรวจสอบว่ามี Runner อยู่แล้วหรือไม่ ถ้าไม่มีจะสร้างใหม่
    เพื่อให้ใช้ Runner เดียวกันตลอดอายุของโปรเซส
    
    Returns:
        object: Runner สำหรับใช้งาน
    """
    global RUNNER
    if RUNNER is None:
        RUNNER = create_campaign_agent()
    return RUNNER


@app.post("/webhook")
async def webhook(request: Request):
    """
    เอนด์พอยต์สำหรับรับเหตุการณ์ webhook จาก LINE
    
    ฟังก์ชันนี้จะรับข้อมูล webhook จาก LINE และประมวลผลเหตุการณ์ต่างๆ
    โดยเฉพาะเหตุการณ์ประเภทข้อความ
    
    Args:
        request: ออบเจ็กต์คำขอ FastAPI ที่มีข้อมูล webhook
        
    Returns:
        JSONResponse: การตอบกลับสถานะของการประมวลผล webhook
    """
    # แปลงข้อมูลคำขอเป็น JSON
    try:
        body = await request.json()
    except Exception:
        return JSONResponse({"status": "bad_request", "reason": "invalid_json"}, status_code=400)

    # ดึงรายการเหตุการณ์จากข้อมูล webhook
    events = body.get("events", []) if isinstance(body, dict) else []
    has_accepted = False

    # ประมวลผลแต่ละเหตุการณ์
    for ev in events:
        try:
            # ตรวจสอบว่าเป็นเหตุการณ์ประเภทข้อความหรือไม่
            if ev.get("type") != "message":
                continue
            msg = ev.get("message", {})
            # ตรวจสอบว่าเป็นข้อความประเภทข้อความหรือไม่
            if msg.get("type") != "text":
                continue

            # ดึงข้อมูลที่จำเป็น
            user_id = ((ev.get("source") or {}).get("userId")) or DESTINATION_USER_ID
            text = msg.get("text") or ""
            msg_id = msg.get("id")
            evt_id = ev.get("webhookEventId")
            # สร้างคีย์สำหรับตรวจสอบความซ้ำซ้อน
            dedup_key = evt_id or (f"{user_id}:{msg_id}" if msg_id else f"{user_id}:{hash(text)}")
        
            if _dedup_seen_db(dedup_key):
                print(f"[DEDUP] Skip duplicate event: {dedup_key}")
                continue

            # ตรวจสอบการจำกัดการใช้งานของผู้ใช้
            if _user_throttled(user_id):
                print(f"[THROTTLE] Skip because user {user_id} already processing within {RUNNING_TTL_SECONDS}s window")
                continue

            # ดึง reply token สำหรับตอบกลับข้อความ
            reply_token = ev.get("replyToken")
            if not reply_token:
                print(f"[WARN] No reply token for event: {ev.get('webhookEventId')}")
                continue
                
            # ประมวลผลข้อความด้วย ADK agent
            runner = get_runner()
            asyncio.create_task(process_with_adk_agent(runner, text, user_id, reply_token))
            has_accepted = True
        except Exception as e:
            print(f"[ERROR] Webhook event handling failed: {e}")
            continue

    # ส่งการตอบกลับสถานะ
    if not has_accepted:
        return JSONResponse({"status": "ignored"})
    return JSONResponse({"status": "ok"})

async def process_with_adk_agent(runner, message_text, user_id, reply_token):
    """
    ประมวลผลข้อความผู้ใช้ด้วย ADK agent
    
    ฟังก์ชันนี้จะส่งข้อความของผู้ใช้ไปยัง ADK agent เพื่อประมวลผลและตอบกลับ
    
    Args:
        runner: ออบเจ็กต์ Runner ที่ใช้ในการประมวลผล
        message_text: ข้อความที่ผู้ใช้ส่งมา
        user_id: ID ของผู้ใช้
        reply_token: Token สำหรับตอบกลับข้อความโดยเฉพาะ
    """
    # บันทึกข้อมูลการเริ่มประมวลผล
    print(f"[INFO] ADK start user={user_id} text='{message_text}'")
 
    # สร้างหรือเรียกใช้เซสชัน
    session_id = user_id
    try:
        await runner.session_service.create_session(app_name=APP_NAME, user_id=user_id, session_id=session_id)
    except Exception:
        pass
 
    # ดึงบริบทการสนทนาก่อนหน้า
    try:
        ctx = build_memory_context(user_id, limit=8)
    except Exception:
        ctx = None
 
    # ตรวจสอบว่าผู้ใช้ต้องการข้อมูล Flex Message หรือไม่
    # ตรวจสอบว่าผู้ใช้ต้องการข้อมูล Flex Message หรือไม่
    lt = (message_text or "").lower()
    user_ask_flex = (
        ("flex" in lt)
        or ("เฟล็ก" in message_text)
        or ("เฟลก" in message_text)
        or ("การ์ด" in message_text)
        or ("เมนู" in message_text)
        or ("โปร" in message_text)
        or ("โปรโมชัน" in message_text or "โปรโมชั่น" in message_text)
        or ("คูปอง" in message_text)
    )
    
    if user_ask_flex:
        # กำหนดคำแนะนำสำหรับการสร้าง Flex Message
        flex_instruction = """
คุณต้องตอบกลับเป็น JSON message object สำหรับ LINE Messaging API เท่านั้น
โครงสร้างต้องเป็นดังนี้:
{
    "message": {
        "type": "flex",
        "altText": "ข้อความทางเลือก",
        "contents": {
            // Flex Message Container object
        }
    }
}

ห้ามตอบเป็นข้อความปกติเด็ดขาด ต้องเป็น JSON เท่านั้น
"""
        # เตรียมข้อความสำหรับส่งไปยัง agent พร้อมบริบทและคำแนะนำ
        prepared_text = f"{ctx}\n\nคำถามล่าสุด: {message_text}\n{flex_instruction}" if ctx else f"{message_text}\n{flex_instruction}"
    else:
        # สำหรับข้อความทั่วไป ให้ใช้ MCP tool
        mcp_instruction = "\nกรุณาใช้ MCP tool ในการตอบกลับข้อความ"
        prepared_text = f"{ctx}\n\nคำถามล่าสุด: {message_text}{mcp_instruction}" if ctx else f"{message_text}{mcp_instruction}"
 
    # บันทึกข้อความของผู้ใช้ลงในประวัติการสนทนา
    try:
        memory_add_message(user_id, "user", message_text)
    except Exception:
        pass
 
    # ตัวแปรสำหรับเก็บผลลัพธ์
    final_text = None
    tool_done = False
    resource_exhausted = False
 
    # ส่งข้อความไปยัง agent เพื่อประมวลผล
    agen = runner.run_async(
        user_id=user_id,
        session_id=session_id,
        new_message=Content(parts=[Part(text=prepared_text)], role="user"),
    )
    try:
        # รับผลลัพธ์จาก agent แบบ streaming
        async for event in agen:
            evtype = getattr(event, "event_type", "")
            if evtype == "tool_response":
                tool_done = True
                break
            try:
                if event.is_final_response() and event.content:
                    final_text = event.content.parts[0].text if event.content.parts else None
            except Exception:
                pass
    except McpError as e:
        # จัดการข้อผิดพลาดจาก MCP
        print(f"[TOOL ERROR] MCP: {e}")
    except Exception as e:
        # จัดการข้อผิดพลาดทั่วไป
        print(f"[ERROR] Agent stream: {e}")

        se = str(e)
        if "RESOURCE_EXHAUSTED" in se or "429" in se:
            resource_exhausted = True
    finally:
        # ปิด agent stream
        try:
            await agen.aclose()
        except Exception:
            pass

    # ถ้า tool ทำงานสำเร็จ
    if tool_done:
        print("[OK] Tool executed via MCP.")

        # บันทึกการตอบกลับลงในประวัติการสนทนา
        try:
            memory_add_message(user_id, "assistant", "(ส่งข้อความผ่าน MCP สำเร็จ)")
        except Exception:
            pass
        return

    # แสดงข้อความที่ได้จาก LLM เพื่อการดีบัก
    print(f"[DEBUG] final_text from LLM: {repr(final_text)}")
    
    # ถ้ามีข้อความตอบกลับจาก LLM
    if final_text:
        # พยายามแปลงข้อความเป็น message object
        msg_obj = _try_parse_message_obj(final_text)
        if msg_obj:
            print(f"[DEBUG] Parsed msg_obj: {msg_obj}")
            
            # ตรวจสอบโครงสร้าง JSON ว่าถูกต้องหรือไม่
            if msg_obj.get("type") == "flex" and "contents" in msg_obj and "altText" in msg_obj:
                print("[DEBUG] Valid Flex message structure")
                # ส่ง Flex message ไปยังผู้ใช้โดยใช้ reply token
                ok = _fallback_push_line_message(user_id, msg_obj, reply_token)
                print("[FALLBACK PARSED OK]" if ok else "[FALLBACK PARSED FAIL]")
                if ok:
                    # บันทึกการตอบกลับลงในประวัติการสนทนา
                    try:
                        memory_add_message(user_id, "assistant", "(ส่ง Flex message สำเร็จ)")
                    except Exception:
                        pass
                    return
            elif msg_obj.get("type") == "text" and "text" in msg_obj:
                # ตรวจสอบว่าเป็นข้อความธรรมดาที่มีโครงสร้างถูกต้อง
                print("[DEBUG] Valid Text message structure")
                ok = _fallback_push_line_message(user_id, msg_obj, reply_token)
                print("[FALLBACK PARSED OK]" if ok else "[FALLBACK PARSED FAIL]")
                if ok:
                    # บันทึกการตอบกลับลงในประวัติการสนทนา
                    try:
                        memory_add_message(user_id, "assistant", msg_obj.get("text", "(ส่งข้อความสำเร็จ)"))
                    except Exception:
                        pass
                    return
            else:
                # โครงสร้างข้อความไม่ถูกต้อง
                print("[DEBUG] Invalid message structure:", msg_obj)
        else:
            # ไม่สามารถแปลงข้อความเป็น JSON ได้
            print("[DEBUG] Failed to parse final_text as JSON message object:", final_text[:200])
 
    # กรณีทรัพยากรหมด (resource exhausted) แต่ผู้ใช้ต้องการ Flex message
    if resource_exhausted:
        # ตรวจสอบว่าผู้ใช้ต้องการ Flex message หรือไม่จากคำสำคัญในข้อความ
        lt = (message_text or "").lower()
        wants_flex = (
            ("flex" in lt)
            or ("เฟล็ก" in message_text)
            or ("เฟลก" in message_text)
            or ("การ์ด" in message_text)
            or ("เมนู" in message_text)
            or ("โปร" in message_text)
            or ("โปรโมชัน" in message_text or "โปรโมชั่น" in message_text)
            or ("คูปอง" in message_text)
        )
        if wants_flex:
            # ส่ง Flex message ตัวอย่างเมื่อทรัพยากรหมด
            ok = _send_demo_flex(user_id, reply_token)
            print("[FALLBACK DEMO FLEX OK]" if ok else "[FALLBACK DEMO FLEX FAIL]")
            if ok:
                try:
                    memory_add_message(user_id, "assistant", "(ส่ง Flex ตัวอย่างแบบสำรอง เนื่องจากโควต้าหมด)")
                except Exception:
                    pass
                return

    # กรณี user ขอ Flex แต่ไม่ได้รับ JSON message จาก LLM ให้ส่ง Flex demo ทันที
    lt = (message_text or "").lower()
    user_ask_flex = (
        ("flex" in lt)
        or ("เฟล็ก" in message_text)
        or ("เฟลก" in message_text)
        or ("การ์ด" in message_text)
        or ("เมนู" in message_text)
        or ("โปร" in message_text)
        or ("โปรโมชัน" in message_text or "โปรโมชั่น" in message_text)
        or ("คูปอง" in message_text)
    )
    if user_ask_flex and final_text and not msg_obj:
        # ส่ง Flex demo ทันทีเมื่อผู้ใช้ขอ Flex แต่ไม่ได้รับ JSON message
        print("[FALLBACK DEMO FLEX] ส่ง Flex demo ทันที (user ขอ Flex แต่ไม่ได้รับ JSON message)")
        ok = _send_demo_flex(user_id)
        if ok:
            try:
                memory_add_message(user_id, "assistant", "(ส่ง Flex demo ทันที เนื่องจากขอ Flex แต่ไม่ได้รับ JSON message)")
            except Exception:
                pass
            return

    # ถ้ายังไม่สำเร็จ ให้ fallback ส่งข้อความสุดท้ายที่มี หรือส่งข้อความแจ้งเตือนสั้น ๆ เป็นข้อความธรรมดา
    text_to_send = final_text or "ขออภัย เกิดข้อผิดพลาดในการส่งข้อความ ลองใหม่อีกครั้งนะครับ/ค่ะ"
    ok = _fallback_push_line_text(user_id, text_to_send)
    print("[FALLBACK OK]" if ok else "[FALLBACK FAIL]", (text_to_send or "")[:80])

    # บันทึกฝั่งผู้ช่วย (กรณี fallback)
    try:
        memory_add_message(user_id, "assistant", text_to_send)
    except Exception:
        pass
    return
 
def _try_parse_message_obj(text: str) -> Optional[Dict[str, Any]]:
    """
    พยายามแปลงข้อความเป็นวัตถุ JSON ที่มีโครงสร้างถูกต้องสำหรับการส่งข้อความ
    
    Args:
        text (str): ข้อความที่อาจเป็น JSON หรือมี code fence ครอบ JSON
        
    Returns:
        Optional[Dict[str, Any]]: วัตถุข้อความที่แปลงแล้ว หรือ None ถ้าแปลงไม่สำเร็จ
    """
    # แสดงข้อความดิบเพื่อการดีบัก
    print(f"[DEBUG] Raw text to parse: {repr(text[:100])}...")
    
    # ค้นหา JSON ในข้อความ
    json_start = None
    
    # ค้นหา code block ที่มี JSON
    json_block_match = re.search(r'```(?:json)?\s*\n(.*?)\n\s*```', text, re.DOTALL)
    if json_block_match:
        try:
            raw = json_block_match.group(1).strip()
            print(f"[DEBUG] Found JSON in code block: {repr(raw[:100])}...")
            obj = json.loads(raw)
            if isinstance(obj, dict):
                # รองรับทั้งรูปแบบ {"type": "text", "text": "..."} และ {"message": {"type": "text", "text": "..."}}
                if "message" in obj and isinstance(obj["message"], dict):
                    msg = obj["message"]
                    print(f"[DEBUG] Using nested message format: {msg}")
                    return msg
                elif "type" in obj:
                    # กรณีที่เป็น message object โดยตรง
                    print(f"[DEBUG] Using direct message format: {obj}")
                    return obj
        except Exception as e:
            print(f"[DEBUG] JSON parse error in code block: {e}")
    
    # ค้นหา JSON โดยตรงในข้อความ (ไม่มี code block)
    try:
        # ค้นหาเครื่องหมาย { แรกในข้อความ
        json_start = text.find('{')
        if json_start >= 0:
            # ตัดข้อความตั้งแต่ { ไปจนจบ
            potential_json = text[json_start:]
            print(f"[DEBUG] Found potential JSON starting at position {json_start}: {repr(potential_json[:100])}...")
            obj = json.loads(potential_json)
            if isinstance(obj, dict):
                # รองรับทั้งรูปแบบ {"type": "text", "text": "..."} และ {"message": {"type": "text", "text": "..."}}
                if "message" in obj and isinstance(obj["message"], dict):
                    msg = obj["message"]
                    print(f"[DEBUG] Using nested message format: {msg}")
                    return msg
                elif "type" in obj:
                    # กรณีที่เป็น message object โดยตรง
                    print(f"[DEBUG] Using direct message format: {obj}")
                    return obj
    except Exception as e:
        print(f"[DEBUG] JSON parse error in direct text: {e}")
    
    # ถ้าไม่พบ JSON ที่ถูกต้อง
    print("[DEBUG] Failed to parse final_text as JSON message object:", text[:100])
    return None


def _fallback_push_line_message(user_id: str, message: Dict[str, Any], reply_token: Optional[str] = None) -> bool:
    """
    ส่งข้อความตามโครงสร้างที่เอเจนต์อาจส่งมาเป็น JSON ข้อความ (แทนที่จะเรียกเครื่องมือจริง)
    รองรับ:
    - ข้อความธรรดา: {"type":"text", "text":"..."}
    - Flex: {"altText":"...", "contents":{...}}
    
    Args:
        user_id (str): ID ของผู้ใช้ที่จะส่งข้อความไปหา
        message (Dict[str, Any]): โครงสร้างข้อความที่จะส่ง
        reply_token (Optional[str]): Token สำหรับตอบกลับข้อความโดยเฉพาะ ถ้ามีจะใช้ reply แทน push
        
    Returns:
        bool: True ถ้าส่งสำเร็จ, False ถ้าล้มเหลว
    """
    try:
        token = LINE_CHANNEL_ACCESS_TOKEN
        if not token or not user_id:
            print("[FALLBACK][ERROR] Missing token or user_id")
            return False

        payload_message: Optional[Dict[str, Any]] = None

        # ตรวจสอบประเภทข้อความและสร้าง payload ตามประเภท
        mtype = (message.get("type") or "").lower()
        if mtype == "text" and isinstance(message.get("text"), str):
            # สร้าง payload สำหรับข้อความธรรมดา
            payload_message = {
                "type": "text",
                "text": (message.get("text") or "")[:5000],  # จำกัดความยาวข้อความไม่เกิน 5000 ตัวอักษร
            }
        elif "contents" in message and "altText" in message:
            # สร้าง payload สำหรับ Flex message
            payload_message = {
                "type": "flex",
                "altText": str(message.get("altText") or "ข้อความสำคัญ")[0:400],  # จำกัดความยาว altText ไม่เกิน 400 ตัวอักษร
                "contents": message.get("contents"),
            }
        else:
            return False

        # ส่งข้อความไปยัง LINE Messaging API
        if reply_token:
            # ใช้ reply message ถ้ามี reply token
            url = "https://api.line.me/v2/bot/message/reply"
            payload = {
                "replyToken": reply_token,
                "messages": [payload_message],
            }
        else:
            # ใช้ push message ถ้าไม่มี reply token (fallback)
            url = "https://api.line.me/v2/bot/message/push"
            payload = {
                "to": user_id,
                "messages": [payload_message],
            }
        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            url,
            data=data,
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {token}",
            },
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            code = getattr(resp, "status", resp.getcode())
            print(f"[FALLBACK][MSG] HTTP {code}")
            return 200 <= int(code) < 300
    except urllib.error.HTTPError as e:
        # จัดการกรณีเกิด HTTP error
        body = e.read().decode("utf-8", errors="ignore") if hasattr(e, "read") else str(e)
        print(f"[FALLBACK][MSG][HTTPError] {e.code}: {body}")
        return False
    except Exception as e:
        # จัดการกรณีเกิดข้อผิดพลาดอื่นๆ
        print(f"[FALLBACK][MSG][ERROR] {e}")
        return False

def _fallback_push_line_text(user_id: str, text: str) -> bool:
    """
    ส่งข้อความ TEXT โดยตรงไปยัง LINE Messaging API (fallback กรณี Agent ไม่เรียกเครื่องมือ)
    
    Args:
        user_id (str): ID ของผู้ใช้ที่จะส่งข้อความไปหา
        text (str): ข้อความที่จะส่ง
        
    Returns:
        bool: True ถ้าส่งสำเร็จ, False ถ้าล้มเหลว
    """
    try:
        token = LINE_CHANNEL_ACCESS_TOKEN
        if not token or not user_id:
            print("[FALLBACK][ERROR] Missing token or user_id")
            return False
        
        # ส่งข้อความไปยัง LINE Messaging API
        url = "https://api.line.me/v2/bot/message/push"
        payload = {
            "to": user_id,
            "messages": [
                {"type": "text", "text": (text or "")[:5000]}  # จำกัดความยาวข้อความไม่เกิน 5000 ตัวอักษร
            ]
        }
        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            url,
            data=data,
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {token}",
            },
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            code = getattr(resp, "status", resp.getcode())
            print(f"[FALLBACK] HTTP {code}")
            return 200 <= int(code) < 300
    except urllib.error.HTTPError as e:
        # จัดการกรณีเกิด HTTP error
        body = e.read().decode("utf-8", errors="ignore") if hasattr(e, "read") else str(e)
        print(f"[FALLBACK][HTTPError] {e.code}: {body}")
        return False
    except Exception as e:
        # จัดการกรณีเกิดข้อผิดพลาดอื่นๆ
        print(f"[FALLBACK][ERROR] {e}")
        return False


def _send_demo_flex(user_id: str, reply_token: Optional[str] = None) -> bool:
    """
    ส่ง Flex ตัวอย่างแบบง่าย โดยไม่เรียก LLM (ใช้ตอนโควต้าหมดหรือเป็นคำสั่งเดโม่)
    
    Args:
        user_id (str): ID ของผู้ใช้ที่จะส่ง Flex message ไปหา
        reply_token (Optional[str]): Token สำหรับตอบกลับข้อความโดยเฉพาะ ถ้ามีจะใช้ reply แทน push
        
    Returns:
        bool: True ถ้าส่งสำเร็จ, False ถ้าล้มเหลว
    """
    # สร้าง Flex message ตัวอย่างแบบง่าย
    demo_contents: Dict[str, Any] = {
        "type": "bubble",
        "body": {
            "type": "box",
            "layout": "vertical",
            "contents": [
                {"type": "text", "text": "ตัวอย่างโปรโมชัน", "weight": "bold", "size": "lg"},
                {"type": "text", "text": "ส่วนลดพิเศษ 20% สำหรับลูกค้าใหม่", "wrap": True, "size": "sm", "color": "#555555"},
                {"type": "separator", "margin": "md"},
                {"type": "button", "style": "primary", "margin": "md", "action": {"type": "uri", "label": "ดูรายละเอียด", "uri": "https://example.com/"}},
            ],
        },
    }
    msg = {
        "altText": "ตัวอย่างโปรโมชัน - ดูรายละเอียด",
        "contents": demo_contents,
    }
    # ส่ง Flex message ตัวอย่าง
    return _fallback_push_line_message(user_id, msg, reply_token)


if __name__ == "__main__":
    # เริ่มต้นเซิร์ฟเวอร์ FastAPI ด้วย uvicorn
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)