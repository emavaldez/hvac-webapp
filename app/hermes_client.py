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
    Download a file from the Hermes pod.
    Strategy: ask the agent to start a temp HTTP server, get the pod IP,
    then download the file directly (bypassing the LLM for the actual file transfer).
    Returns (content_bytes, filename, error_message).
    """
    import asyncio

    headers = {
        "Authorization": f"Bearer {settings.HERMES_API_KEY}",
        "Content-Type": "application/json",
    }

    async def ask_hermes(prompt: str) -> Optional[str]:
        body = {
            "model": settings.HERMES_MODEL,
            "messages": [{"role": "user", "content": prompt}],
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
                return None
            data = resp.json()
            return data["choices"][0]["message"]["content"].strip()
        except Exception:
            return None

    # Step 1: Ask Hermes to start a temp HTTP server and return the pod IP
    dir_path = str(Path(file_path).parent)
    filename = Path(file_path).name

    resp1 = await ask_hermes(
        f"Ejecutá estos dos comandos en la terminal y pegame los outputs:\n"
        f"1) cd \"{dir_path}\" && nohup python3 -m http.server 9876 > /dev/null 2>&1 &\n"
        f"2) hostname -i\n"
        f"Pegame SOLO la IP que devuelve hostname -i, nada más."
    )

    if not resp1:
        return None, None, "El agente no respondió"

    # Extract IP from response
    ip_match = re.search(r"\b(\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3})\b", resp1)
    if not ip_match:
        return None, None, "No se pudo obtener la IP del pod"

    pod_ip = ip_match.group(1)

    # Step 2: Download the file directly from the pod's HTTP server
    download_url = f"http://{pod_ip}:9876/{filename}"
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            resp = await client.get(download_url)

        if resp.status_code != 200:
            # Cleanup before returning error
            asyncio.create_task(ask_hermes("Ejecutá: pkill -f 'http.server 9876'"))
            return None, None, f"Error {resp.status_code} al descargar del pod"

        file_bytes = resp.content

        # Step 3: Kill the HTTP server (best effort)
        asyncio.create_task(ask_hermes("Ejecutá: pkill -f 'http.server 9876'"))

        return file_bytes, filename, None

    except Exception as e:
        asyncio.create_task(ask_hermes("Ejecutá: pkill -f 'http.server 9876'"))
        return None, None, f"No se pudo descargar: {str(e)}"


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
