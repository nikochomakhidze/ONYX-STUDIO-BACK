import os
from dotenv import load_dotenv
load_dotenv()
import hashlib
import re
import sqlite3
from datetime import datetime, timedelta

import httpx
import jwt
from fastapi import FastAPI, HTTPException, Depends
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from pydantic import BaseModel
import anthropic

app = FastAPI(title="ONYX STUDIO API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── CONFIG ──
DB_PATH = os.getenv("DB_PATH", "onyx.db")
JWT_SECRET = os.getenv("JWT_SECRET", "onyx-studio-change-this-secret")
JWT_EXPIRE_DAYS = 30
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
FACEBOOK_APP_ID = os.getenv("FACEBOOK_APP_ID", "")
FACEBOOK_APP_SECRET = os.getenv("FACEBOOK_APP_SECRET", "")
FRONTEND_URL = os.getenv("FRONTEND_URL", "http://localhost:8080")
BACKEND_URL = os.getenv("BACKEND_URL", "http://localhost:8000")
ADMIN_EMAIL = os.getenv("ADMIN_EMAIL", "nika92152@gmail.com")

security = HTTPBearer(auto_error=False)


# ── DATABASE ──
def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = get_db()
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            email TEXT UNIQUE NOT NULL,
            password_hash TEXT,
            name TEXT NOT NULL,
            plan TEXT DEFAULT 'სტუმარი',
            role TEXT DEFAULT 'user',
            provider TEXT DEFAULT 'email',
            facebook_id TEXT,
            avatar TEXT,
            created_at TEXT DEFAULT (datetime('now'))
        );

        CREATE TABLE IF NOT EXISTS clients (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name_ka TEXT NOT NULL,
            name_en TEXT NOT NULL,
            url TEXT NOT NULL,
            status TEXT DEFAULT 'live',
            plan_ka TEXT NOT NULL,
            plan_en TEXT NOT NULL,
            icon TEXT DEFAULT '🌐',
            visits INTEGER DEFAULT 0,
            revenue INTEGER DEFAULT 0
        );

        CREATE TABLE IF NOT EXISTS chat_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            role TEXT NOT NULL,
            content TEXT NOT NULL,
            created_at TEXT DEFAULT (datetime('now'))
        );
    """)

    existing = conn.execute("SELECT COUNT(*) FROM clients").fetchone()[0]
    if existing == 0:
        conn.executemany(
            "INSERT INTO clients (name_ka, name_en, url, status, plan_ka, plan_en, icon, visits, revenue) VALUES (?,?,?,?,?,?,?,?,?)",
            [
                ("რესტორანი სვანეთი", "Restaurant Svaneti", "https://www.restoranisvaneti.com.ge", "live", "ბიზნეს", "Business", "🍽️", 1240, 250),
                ("ელვაპლუსი", "Elvaplus", "https://elvaplus-express-teal.vercel.app", "live", "პრემიუმ", "Premium", "⚡", 680, 400),
                ("ჩემი სახლი", "Chemi Sakhli", "https://chemi.up.railway.app", "live", "სტარტი", "Starter", "🏠", 180, 100),
            ]
        )
    conn.commit()
    conn.close()


init_db()


# ── HELPERS ──
def hash_pw(pw: str) -> str:
    return hashlib.sha256(pw.encode()).hexdigest()


def validate_password(pw: str):
    if len(pw) < 6:
        raise HTTPException(status_code=400, detail="პაროლი მინიმუმ 6 სიმბოლო უნდა იყოს")
    if not re.search(r'[A-Z]', pw):
        raise HTTPException(status_code=400, detail="პაროლი უნდა შეიცავდეს მინიმუმ 1 დიდ ასოს (A-Z)")
    if not re.search(r'[0-9]', pw):
        raise HTTPException(status_code=400, detail="პაროლი უნდა შეიცავდეს მინიმუმ 1 ციფრს (0-9)")


def make_token(user_id: int, email: str, role: str = "user") -> str:
    payload = {
        "user_id": user_id,
        "email": email,
        "role": role,
        "exp": datetime.utcnow() + timedelta(days=JWT_EXPIRE_DAYS),
    }
    return jwt.encode(payload, JWT_SECRET, algorithm="HS256")


def get_current_user(credentials: HTTPAuthorizationCredentials = Depends(security)):
    if not credentials:
        raise HTTPException(status_code=401, detail="შესვლა საჭიროა")
    try:
        return jwt.decode(credentials.credentials, JWT_SECRET, algorithms=["HS256"])
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="სესია ამოიწურა, შედი ხელახლა")
    except jwt.InvalidTokenError:
        raise HTTPException(status_code=401, detail="არასწორი ტოკენი")


def require_admin(payload: dict = Depends(get_current_user)):
    if payload.get("role") != "admin":
        raise HTTPException(status_code=403, detail="მხოლოდ ადმინისთვის")
    return payload


# ── SCHEMAS ──
class RegisterRequest(BaseModel):
    email: str
    password: str
    confirm_password: str


class LoginRequest(BaseModel):
    email: str
    password: str


class ChatRequest(BaseModel):
    message: str
    lang: str = "ka"


class UpdateUserPlan(BaseModel):
    plan: str


# ── AUTH ──
@app.post("/auth/register")
def register(req: RegisterRequest):
    if req.password != req.confirm_password:
        raise HTTPException(status_code=400, detail="პაროლები არ ემთხვევა")
    validate_password(req.password)

    email = req.email.strip().lower()
    name = email.split("@")[0]

    conn = get_db()
    try:
        existing = conn.execute("SELECT id FROM users WHERE email = ?", (email,)).fetchone()
        if existing:
            raise HTTPException(status_code=400, detail="ეს ელ-ფოსტა უკვე რეგისტრირებულია")

        role = "admin" if email == ADMIN_EMAIL.lower() else "user"
        cursor = conn.execute(
            "INSERT INTO users (email, password_hash, name, role) VALUES (?, ?, ?, ?)",
            (email, hash_pw(req.password), name, role)
        )
        conn.commit()
        user_id = cursor.lastrowid
        token = make_token(user_id, email, role)
        return {"token": token, "user": {"id": user_id, "email": email, "name": name, "plan": "სტუმარი", "role": role}}
    finally:
        conn.close()


@app.post("/auth/login")
def login(req: LoginRequest):
    email = req.email.strip().lower()
    conn = get_db()
    try:
        user = conn.execute("SELECT * FROM users WHERE email = ?", (email,)).fetchone()
        if not user or user["password_hash"] != hash_pw(req.password):
            raise HTTPException(status_code=401, detail="არასწორი ელ-ფოსტა ან პაროლი")

        token = make_token(user["id"], user["email"], user["role"])
        return {"token": token, "user": {"id": user["id"], "email": user["email"], "name": user["name"], "plan": user["plan"], "role": user["role"]}}
    finally:
        conn.close()


@app.get("/auth/me")
def get_me(payload: dict = Depends(get_current_user)):
    conn = get_db()
    try:
        user = conn.execute(
            "SELECT id, email, name, plan, role, provider, avatar, created_at FROM users WHERE id = ?",
            (payload["user_id"],)
        ).fetchone()
        if not user:
            raise HTTPException(status_code=404, detail="მომხმარებელი ვერ მოიძებნა")
        return dict(user)
    finally:
        conn.close()


# ── FACEBOOK OAUTH ──
@app.get("/auth/facebook")
def facebook_login():
    if not FACEBOOK_APP_ID:
        raise HTTPException(status_code=503, detail="Facebook auth not configured")
    redirect_uri = f"{BACKEND_URL}/auth/facebook/callback"
    url = (
        f"https://www.facebook.com/v18.0/dialog/oauth"
        f"?client_id={FACEBOOK_APP_ID}"
        f"&redirect_uri={redirect_uri}"
        f"&scope=email,public_profile"
    )
    return RedirectResponse(url)


@app.get("/auth/facebook/callback")
async def facebook_callback(code: str = None, error: str = None):
    if error or not code:
        return RedirectResponse(f"{FRONTEND_URL}/#auth-error=facebook_denied")
    redirect_uri = f"{BACKEND_URL}/auth/facebook/callback"
    async with httpx.AsyncClient() as client:
        token_resp = await client.get(
            "https://graph.facebook.com/v18.0/oauth/access_token",
            params={"client_id": FACEBOOK_APP_ID, "client_secret": FACEBOOK_APP_SECRET, "redirect_uri": redirect_uri, "code": code}
        )
        token_data = token_resp.json()
        if "error" in token_data:
            return RedirectResponse(f"{FRONTEND_URL}/#auth-error=token_failed")
        user_resp = await client.get(
            "https://graph.facebook.com/me",
            params={"fields": "id,name,email,picture", "access_token": token_data["access_token"]}
        )
        fb = user_resp.json()

    fb_id = fb.get("id")
    name = fb.get("name", "Facebook User")
    email = fb.get("email", f"fb_{fb_id}@facebook.com")
    avatar = fb.get("picture", {}).get("data", {}).get("url", "")

    conn = get_db()
    try:
        user = conn.execute("SELECT * FROM users WHERE facebook_id = ? OR email = ?", (fb_id, email)).fetchone()
        if user:
            conn.execute("UPDATE users SET facebook_id=?, name=?, avatar=?, provider='facebook' WHERE id=?", (fb_id, name, avatar, user["id"]))
            user_id, role = user["id"], user["role"]
        else:
            role = "admin" if email.lower() == ADMIN_EMAIL.lower() else "user"
            cur = conn.execute(
                "INSERT INTO users (email, name, provider, facebook_id, avatar, role) VALUES (?,?,'facebook',?,?,?)",
                (email, name, fb_id, avatar, role)
            )
            user_id = cur.lastrowid
        conn.commit()
        token = make_token(user_id, email, role)
        return RedirectResponse(f"{FRONTEND_URL}/#token={token}")
    finally:
        conn.close()


# ── STATS ──
@app.get("/stats")
def get_stats(payload: dict = Depends(get_current_user)):
    conn = get_db()
    try:
        clients_count = conn.execute("SELECT COUNT(*) FROM clients").fetchone()[0]
        total_visits = conn.execute("SELECT SUM(visits) FROM clients").fetchone()[0] or 0
        total_revenue = conn.execute("SELECT SUM(revenue) FROM clients").fetchone()[0] or 0
        return {"total_sites": clients_count, "total_visits": total_visits, "total_revenue": total_revenue}
    finally:
        conn.close()


# ── CLIENTS ──
@app.get("/clients")
def get_clients(payload: dict = Depends(get_current_user)):
    conn = get_db()
    try:
        return [dict(c) for c in conn.execute("SELECT * FROM clients").fetchall()]
    finally:
        conn.close()


# ── ADMIN ──
@app.get("/admin/users")
def admin_get_users(payload: dict = Depends(require_admin)):
    conn = get_db()
    try:
        users = conn.execute(
            "SELECT id, email, name, plan, role, provider, created_at FROM users ORDER BY id DESC"
        ).fetchall()
        return [dict(u) for u in users]
    finally:
        conn.close()


@app.patch("/admin/users/{user_id}/plan")
def admin_update_plan(user_id: int, body: UpdateUserPlan, payload: dict = Depends(require_admin)):
    conn = get_db()
    try:
        conn.execute("UPDATE users SET plan = ? WHERE id = ?", (body.plan, user_id))
        conn.commit()
        return {"ok": True}
    finally:
        conn.close()


@app.delete("/admin/users/{user_id}")
def admin_delete_user(user_id: int, payload: dict = Depends(require_admin)):
    conn = get_db()
    try:
        conn.execute("DELETE FROM users WHERE id = ?", (user_id,))
        conn.commit()
        return {"ok": True}
    finally:
        conn.close()


@app.get("/admin/stats")
def admin_stats(payload: dict = Depends(require_admin)):
    conn = get_db()
    try:
        total_users = conn.execute("SELECT COUNT(*) FROM users").fetchone()[0]
        total_sites = conn.execute("SELECT COUNT(*) FROM clients").fetchone()[0]
        total_revenue = conn.execute("SELECT SUM(revenue) FROM clients").fetchone()[0] or 0
        recent = conn.execute(
            "SELECT email, name, plan, created_at FROM users ORDER BY id DESC LIMIT 5"
        ).fetchall()
        return {
            "total_users": total_users,
            "total_sites": total_sites,
            "total_revenue": total_revenue,
            "recent_users": [dict(r) for r in recent]
        }
    finally:
        conn.close()


# ── AI CHAT ──
SYSTEM_KA = """შენ ხარ ONYX STUDIO-ს AI ასისტენტი — ქართული ვებ სააგენტოს.
პაკეტები: სტარტი 100₾/თვე (1 გვერდი), ბიზნეს 250₾/თვე (5 გვერდი, SEO, AI Bot), პრემიუმ 400₾/თვე (უსაზღვრო, მაღაზია).
კონტაქტი: WhatsApp: +995 597 840 303
პასუხები — ქართულად, მოკლედ, მეგობრულად."""

SYSTEM_EN = """You are ONYX STUDIO's AI assistant — a Georgian web agency.
Plans: Starter ₾100/mo (1 page), Business ₾250/mo (5 pages, SEO, AI Bot), Premium ₾400/mo (unlimited, store).
Contact: WhatsApp: +995 597 840 303
Reply in English, briefly and friendly."""


@app.post("/chat")
def chat(req: ChatRequest, payload: dict = Depends(get_current_user)):
    if not ANTHROPIC_API_KEY:
        raise HTTPException(status_code=503, detail="AI not configured")
    conn = get_db()
    user_id = payload["user_id"]
    history = list(reversed(conn.execute(
        "SELECT role, content FROM chat_history WHERE user_id = ? ORDER BY id DESC LIMIT 10",
        (user_id,)
    ).fetchall()))
    messages = [{"role": r["role"], "content": r["content"]} for r in history]
    messages.append({"role": "user", "content": req.message})
    try:
        ai = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
        resp = ai.messages.create(
            model="claude-haiku-4-5-20251001", max_tokens=512,
            system=SYSTEM_KA if req.lang == "ka" else SYSTEM_EN,
            messages=messages,
        )
        reply = resp.content[0].text
        conn.execute("INSERT INTO chat_history (user_id, role, content) VALUES (?,?,?)", (user_id, "user", req.message))
        conn.execute("INSERT INTO chat_history (user_id, role, content) VALUES (?,?,?)", (user_id, "assistant", reply))
        conn.commit()
        conn.close()
        return {"reply": reply}
    except Exception as e:
        conn.close()
        raise HTTPException(status_code=502, detail=str(e))


@app.get("/")
def root():
    return {"status": "ONYX STUDIO API", "version": "3.0"}
