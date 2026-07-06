"""
Hermes API client — talks to the Hermes Gateway API Server.
Uses the OpenAI-compatible /v1/chat/completions endpoint.
"""
import httpx
import json
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
