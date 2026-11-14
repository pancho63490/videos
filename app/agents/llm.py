"""Cliente mínimo del modelo de IA (API de mensajes de Anthropic).

Variables de entorno:
  ANTHROPIC_API_KEY   clave de la API (obligatoria para que trabajen los agentes)
  ANTHROPIC_MODEL     modelo a usar (opcional)
"""
import json
import os
from dataclasses import dataclass, field
from typing import Optional

import httpx

API_URL = "https://api.anthropic.com/v1/messages"
API_VERSION = "2023-06-01"
DEFAULT_MODEL = "claude-sonnet-5-5"
WEB_SEARCH_TOOL = "web_search_20250305"
MAX_CONTINUATIONS = 6


class LLMError(Exception):
    """Error al llamar al modelo de IA."""


@dataclass
class LLMResult:
    text: str = ""
    urls: set = field(default_factory=set)  # enlaces que la búsqueda web devolvió de verdad
    searches: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    stop_reason: str = ""


def is_configured() -> bool:
    return bool(os.getenv("ANTHROPIC_API_KEY"))


def model_name() -> str:
    return os.getenv("ANTHROPIC_MODEL") or DEFAULT_MODEL


def _post(payload: dict) -> dict:
    """Hace la llamada HTTP. Separada para poder sustituirla en las pruebas."""
    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        raise LLMError("Falta la variable de entorno ANTHROPIC_API_KEY.")
    try:
        response = httpx.post(
            API_URL,
            headers={
                "x-api-key": api_key,
                "anthropic-version": API_VERSION,
                "content-type": "application/json",
            },
            json=payload,
            timeout=httpx.Timeout(600.0, connect=20.0),
        )
    except httpx.HTTPError as exc:
        raise LLMError(f"No se pudo conectar con el modelo de IA: {exc}") from exc
    if response.status_code >= 400:
        try:
            detail = response.json().get("error", {}).get("message", response.text)
        except ValueError:
            detail = response.text
        raise LLMError(f"El modelo de IA respondió {response.status_code}: {str(detail)[:500]}")
    return response.json()


def complete(system: str, user: str, max_tokens: int = 4096, web_searches: int = 0) -> LLMResult:
    """Envía una instrucción y devuelve el texto de la respuesta.

    Con web_searches > 0 el modelo puede buscar en la web; los enlaces que la
    búsqueda devolvió quedan en `urls` para comprobar las fuentes citadas.
    """
    payload = {
        "model": model_name(),
        "max_tokens": max_tokens,
        "system": system,
        "messages": [{"role": "user", "content": user}],
    }
    if web_searches > 0:
        payload["tools"] = [{"type": WEB_SEARCH_TOOL, "name": "web_search", "max_uses": web_searches}]

    result = LLMResult()
    texts = []
    for _ in range(MAX_CONTINUATIONS):
        data = _post(payload)
        content = data.get("content") or []
        for block in content:
            kind = block.get("type")
            if kind == "text":
                texts.append(block.get("text", ""))
            elif kind == "web_search_tool_result":
                items = block.get("content")
                if isinstance(items, list):
                    for item in items:
                        if isinstance(item, dict) and item.get("url"):
                            result.urls.add(item["url"])
        usage = data.get("usage") or {}
        result.input_tokens += int(usage.get("input_tokens") or 0)
        result.output_tokens += int(usage.get("output_tokens") or 0)
        result.searches += int((usage.get("server_tool_use") or {}).get("web_search_requests") or 0)
        result.stop_reason = data.get("stop_reason") or ""
        if result.stop_reason != "pause_turn":
            break
        # El turno quedó en pausa: se reenvía tal cual para que el modelo continúe.
        payload["messages"] = payload["messages"] + [{"role": "assistant", "content": content}]

    result.text = "".join(texts)
    return result


def extract_json(text: str, required_key: str) -> Optional[dict]:
    """Encuentra en el texto el primer objeto JSON que contenga la clave pedida."""
    decoder = json.JSONDecoder()
    start = text.find("{")
    while start != -1:
        try:
            value, _ = decoder.raw_decode(text[start:])
        except ValueError:
            value = None
        if isinstance(value, dict) and required_key in value:
            return value
        start = text.find("{", start + 1)
    return None
