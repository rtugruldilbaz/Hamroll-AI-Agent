import requests

from config.app_settings import get_chat_model, get_ollama_host


def chat_with_tools(messages: list, tools: list) -> dict:
    payload = {
        "model": get_chat_model(),
        "messages": messages,
        "tools": tools,
        "stream": False,
    }

    response = requests.post(
        f"{get_ollama_host()}/api/chat",
        json=payload,
        timeout=120,
    )
    response.raise_for_status()

    data = response.json()

    if not isinstance(data, dict) or not isinstance(data.get("message"), dict):
        raise RuntimeError("Ollama returned an invalid chat response.")

    return data
