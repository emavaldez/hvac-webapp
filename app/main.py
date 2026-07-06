"""
FastAPI app — login + chat proxy for Hermes HVAC agent.
Only exposes: /login, /logout, /chat, /history, /clear
"""
import os
import sys
import time
from typing import Optional

# Ensure app dir is in path for imports
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from fastapi import FastAPI, Request, Response, Depends, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from pydantic import BaseModel
from pathlib import Path

from config import settings
from auth import verify_user, create_token, verify_token
from database import init_db, save_message, get_history, clear_history
from hermes_client import send_message

app = FastAPI(title="HVAC Web App")

# Init DB on startup
init_db()

# Serve templates
templates_dir = Path(__file__).parent / "templates"


def get_current_user(request: Request) -> Optional[dict]:
    """Extract user from JWT cookie."""
    token = request.cookies.get("session")
    if not token:
        return None
    return verify_token(token)


def require_user(request: Request) -> dict:
    """Dependency: require authenticated user."""
    user = get_current_user(request)
    if not user:
        raise HTTPException(status_code=401, detail="Not authenticated")
    return user


# --- Pages ---

@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    user = get_current_user(request)
    if not user:
        return RedirectResponse("/login", status_code=302)
    html = (templates_dir / "chat.html").read_text()
    # Inject user name
    html = html.replace("{{USER_NAME}}", user["name"])
    return HTMLResponse(html)


@app.get("/login", response_class=HTMLResponse)
async def login_page(request: Request):
    user = get_current_user(request)
    if user:
        return RedirectResponse("/", status_code=302)
    return HTMLResponse((templates_dir / "login.html").read_text())


# --- API ---

class LoginRequest(BaseModel):
    username: str
    password: str


@app.post("/api/login")
async def login(req: LoginRequest, response: Response):
    user = verify_user(req.username, req.password)
    if not user:
        raise HTTPException(status_code=401, detail="Usuario o contraseña incorrectos")

    token = create_token(user)
    resp = JSONResponse({"ok": True, "name": user["name"]})
    resp.set_cookie(
        key="session",
        value=token,
        httponly=True,
        secure=True,
        samesite="lax",
        max_age=settings.JWT_EXPIRE_HOURS * 3600,
        path="/",
    )
    return resp


@app.post("/api/logout")
async def logout(response: Response):
    resp = JSONResponse({"ok": True})
    resp.delete_cookie("session", path="/")
    return resp


class ChatRequest(BaseModel):
    message: str


@app.post("/api/chat")
async def chat(req: ChatRequest, user: dict = Depends(require_user)):
    if not req.message.strip():
        raise HTTPException(status_code=400, detail="Mensaje vacío")

    # Save user message
    save_message(user["username"], "user", req.message)

    # Get history for context
    history = get_history(user["username"], limit=20)

    # Send to Hermes
    response_text, error = await send_message(req.message, history)

    if error:
        # Don't save error as assistant message
        raise HTTPException(status_code=502, detail=error)

    # Save assistant response
    save_message(user["username"], "assistant", response_text)

    return {"response": response_text}


@app.get("/api/history")
async def history(user: dict = Depends(require_user)):
    messages = get_history(user["username"], limit=50)
    return {"messages": messages}


@app.post("/api/clear")
async def clear(user: dict = Depends(require_user)):
    clear_history(user["username"])
    return {"ok": True}


@app.get("/api/health")
async def health():
    return {"status": "ok"}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=settings.APP_PORT)
