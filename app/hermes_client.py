"""
Hermes API client — talks to the Hermes Gateway API Server.
Uses the OpenAI-compatible /v1/chat/completions endpoint.
Supports file attachments via multipart content.
Supports file download via base64 encoding.
"""
import httpx
import json
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


async def download_file_from_hermes(
    file_path: str, timeout: int = 120
) -> Tuple[Optional[bytes], Optional[str], Optional[str]]:
    """
    Ask Hermes to read a file and return it base64-encoded.
    Uses the agent's terminal tool to run base64 command directly.
    Returns (content_bytes, filename, error_message).
    """
    headers = {
        "Authorization": f"Bearer {settings.HERMES_API_KEY}",
        "Content-Type": "application/json",
    }
    body = {
        "model": settings.HERMES_MODEL,
        "messages": [
            {
                "role": "user",
                "content": (
                    f"Necesito que leas el archivo binario {file_path} y me devuelvas su contenido "
                    f"codificado en base64. Usá la herramienta terminal para ejecutar este comando "
                    f"y pegame el output completo:\n\n"
                    f"base64 \"{file_path}\"\n\n"
                    f"Si el archivo no existe, decime 'FILE_NOT_FOUND'. "
                    f"Pegame SOLO el output del comando base64, sin texto adicional."
                ),
            }
        ],
        "stream": False,
    }

    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            resp = await client.post(
                f"{settings.HERMES_API_URL}/chat/completions",
                headers=headers,
                json=body,
            )

        if resp.status_code != 200:
            return None, None, f"Error {resp.status_code} del agente"

        data = resp.json()
        content = data["choices"][0]["message"]["content"].strip()

        if "FILE_NOT_FOUND" in content:
            return None, None, "Archivo no encontrado en el agente"

        # Strip markdown code fences if present
        if content.startswith("```"):
            content = re.sub(r"^```\w*\n?", "", content)
            content = re.sub(r"\n?```$", "", content)
            content = content.strip()

        # Remove any leading/trailing non-base64 text
        # base64 only contains A-Za-z0-9+/=
        lines = content.split("\n")
        b64_lines = [l.strip() for l in lines if re.match(r"^[A-Za-z0-9+/=\s]+$", l.strip())]
        if b64_lines:
            content = "".join(b64_lines)

        # Decode base64
        file_bytes = base64.b64decode(content)
        filename = Path(file_path).name
        return file_bytes, filename, None

    except Exception as e:
        return None, None, f"No se pudo descargar el archivo: {str(e)}"


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
