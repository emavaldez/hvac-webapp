"""
Hermes API client — talks to the Hermes Gateway API Server.
Uses the OpenAI-compatible /v1/chat/completions endpoint.
Supports file attachments via multipart content.
Supports file download via base64 encoding.
"""
import httpx
import json
import os
import base64
import re
from pathlib import Path
from typing import Tuple, Optional
from config import settings


async def send_message(
    message: str, history: list, timeout: int = 120
) -> Tuple[str, Optional[str]]:
    """
    Send a message to Hermes and get the response.
    Returns (response_text, error_message).
    """
    # Build the messages array for the API
    messages = []
    for h in history:
        messages.append({"role": h["role"], "content": h["content"]})
    messages.append({"role": "user", "content": message})

    headers = {
        "Authorization": f"Bearer {settings.HERMES_API_KEY}",
        "Content-Type": "application/json",
    }
    body = {
        "model": settings.HERMES_MODEL,
        "messages": messages,
        "stream": False,
    }

    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            resp = await client.post(
                f"{settings.HERMES_API_URL}/chat/completions",
                headers=headers,
                json=body,
            )

        if resp.status_code == 401:
            return "", "Error de autenticación con el agente"
        if resp.status_code == 429:
            return "", "El agente está saturado, probá en un momento"
        if resp.status_code >= 500:
            return "", "El agente no está disponible ahora"

        data = resp.json()
        content = data["choices"][0]["message"]["content"]
        return content, None

    except httpx.TimeoutException:
        return "", "El agente tardó demasiado en responder"
    except httpx.ConnectError:
        return "", "No se pudo conectar con el agente"
    except (KeyError, json.JSONDecodeError):
        return "", "Respuesta inválida del agente"


# --- File download via Hermes ---

# Patterns: absolute paths and known extensions
FILE_PATH_RE = re.compile(
    r'(?:^|\s)((?:/[\w\-./]+)\.(?:xlsx|xls|csv|pdf|docx|doc|pptx|ppt|txt|json|yaml|yml|zip|png|jpg|jpeg|gif))',
    re.IGNORECASE,
)


def extract_file_paths(text: str) -> list[str]:
    """Extract file paths from agent response text."""
    return list(dict.fromkeys(FILE_PATH_RE.findall(text)))  # dedup, preserve order


async def start_file_download(file_path: str) -> str:
    """
    Start a file download from the Hermes pod.
    Asks the agent to upload the file via curl to our /api/transfer endpoint.
    Returns the transfer_id immediately (does not wait for the file).
    """
    import uuid

    headers = {
        "Authorization": f"Bearer {settings.HERMES_API_KEY}",
        "Content-Type": "application/json",
    }

    transfer_id = str(uuid.uuid4())[:8]
    webapp_url = os.getenv("WEBAPP_PUBLIC_URL", "https://hvac-webapp-manejamelo-prod.apps.nan.builders")

    # Build the curl command for the agent to execute
    curl_cmd = (
        f'curl -s -X POST '
        f'-F "file=@{file_path}" '
        f'-F "transfer_id={transfer_id}" '
        f'-H "X-Transfer-Key: {transfer_id}" '
        f'"{webapp_url}/api/transfer"'
    )

    prompt = (
        f"Ejecutá este comando en la terminal y pegame el output:\n\n"
        f"{curl_cmd}\n\n"
        f"Pegame SOLO el output del curl."
    )

    body = {
        "model": settings.HERMES_MODEL,
        "messages": [{"role": "user", "content": prompt}],
        "stream": False,
    }

    import asyncio

    async def fire_curl():
        try:
            async with httpx.AsyncClient(timeout=180) as client:
                await client.post(
                    f"{settings.HERMES_API_URL}/chat/completions",
                    headers=headers,
                    json=body,
                )
        except Exception:
            pass

    # Fire and forget — the task runs independently of the request
    asyncio.create_task(fire_curl())

    return transfer_id


async def send_message_with_files(
    message: str,
    history: list,
    files: list,
    timeout: int = 120,
) -> Tuple[str, Optional[str]]:
    """
    Send a message with file attachments to Hermes.
    files: list of dicts with {filename, content (bytes), content_type}
    """
    # Build user message content as multipart (text + images/files)
    user_content = []

    # Add text message
    if message:
        user_content.append({"type": "text", "text": message})

    # Add files as base64
    for f in files:
        b64 = base64.b64encode(f["content"]).decode()
        if f["content_type"].startswith("image/"):
            user_content.append({
                "type": "image_url",
                "image_url": {
                    "url": f"data:{f['content_type']};base64,{b64}"
                }
            })
        else:
            # Non-image files: encode as text with filename info
            user_content.append({
                "type": "text",
                "text": f"[Archivo adjunto: {f['filename']} ({f['content_type']}, {len(f['content'])} bytes)]"
            })

    # Build messages
    messages = []
    for h in history:
        messages.append({"role": h["role"], "content": h["content"]})
    messages.append({"role": "user", "content": user_content})

    headers = {
        "Authorization": f"Bearer {settings.HERMES_API_KEY}",
        "Content-Type": "application/json",
    }
    body = {
        "model": settings.HERMES_MODEL,
        "messages": messages,
        "stream": False,
    }

    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            resp = await client.post(
                f"{settings.HERMES_API_URL}/chat/completions",
                headers=headers,
                json=body,
            )

        if resp.status_code == 401:
            return "", "Error de autenticación con el agente"
        if resp.status_code == 429:
            return "", "El agente está saturado, probá en un momento"
        if resp.status_code >= 500:
            return "", "El agente no está disponible ahora"

        data = resp.json()
        content = data["choices"][0]["message"]["content"]
        return content, None

    except httpx.TimeoutException:
        return "", "El agente tardó demasiado en responder"
    except httpx.ConnectError:
        return "", "No se pudo conectar con el agente"
    except (KeyError, json.JSONDecodeError):
        return "", "Respuesta inválida del agente"
