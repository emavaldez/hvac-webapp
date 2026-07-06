"""
FastAPI app — login + chat proxy for Hermes HVAC agent.
Only exposes: /login, /logout, /chat, /history, /clear
Supports file attachments in chat.
"""
import os
import sys
import time
import json
import shutil
from typing import Optional

# Ensure app dir is in path for imports
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from fastapi import FastAPI, Request, Response, Depends, HTTPException, UploadFile, File, Form
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse, FileResponse
from pydantic import BaseModel
from pathlib import Path

from config import settings
from auth import verify_user, create_token, verify_token
from database import init_db, save_message, get_history, clear_history
from hermes_client import send_message, send_message_with_files

app = FastAPI(title="HVAC Web App")

# Init DB on startup
init_db()

# Serve templates
templates_dir = Path(__file__).parent / "templates"

# Upload directory
UPLOAD_DIR = Path(os.getenv("UPLOAD_DIR", "/data/uploads"))
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)


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


@app.post("/api/chat")
async def chat(
    request: Request,
    user: dict = Depends(require_user),
):
    """Chat endpoint that supports both JSON and multipart (with files)."""
    content_type = request.headers.get("content-type", "")

    if "multipart/form-data" in content_type:
        form = await request.form()
        message = form.get("message", "").strip()
        files = form.getlist("files")

        if not message and not files:
            raise HTTPException(status_code=400, detail="Mensaje vacío")

        # Process uploaded files
        processed_files = []
        attachment_info = []
        for f in files:
            if hasattr(f, "read"):
                content = await f.read()
                if content:
                    processed_files.append({
                        "filename": f.filename,
                        "content": content,
                        "content_type": f.content_type or "application/octet-stream",
                    })
                    attachment_info.append({
                        "filename": f.filename,
                        "size": len(content),
                    })

        # Save user message
        att_json = json.dumps(attachment_info) if attachment_info else "[]"
        save_message(user["username"], "user", message or "(archivo adjunto)", att_json)

        # Get history
        history = get_history(user["username"], limit=20)

        # Send to Hermes
        if processed_files:
            response_text, error = await send_message_with_files(
                message, history, processed_files
            )
        else:
            response_text, error = await send_message(message, history)

        if error:
            raise HTTPException(status_code=502, detail=error)

        # Save assistant response
        save_message(user["username"], "assistant", response_text)

        return {"response": response_text}

    else:
        # JSON-only request (backward compat)
        body = await request.json()
        message = body.get("message", "").strip()
        if not message:
            raise HTTPException(status_code=400, detail="Mensaje vacío")

        save_message(user["username"], "user", message)
        history = get_history(user["username"], limit=20)
        response_text, error = await send_message(message, history)

        if error:
            raise HTTPException(status_code=502, detail=error)

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
