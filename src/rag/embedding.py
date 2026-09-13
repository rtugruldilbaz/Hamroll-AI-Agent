import requests

from config.app_settings import (
    get_embedding_model,
    get_ollama_host,
)


def create_embedding(
    text: str,
) -> list[float]:
    text = str(
        text or ""
    ).strip()

    if not text:
        raise ValueError(
            "Embedding text cannot be empty."
        )

    response = requests.post(
        f"{get_ollama_host()}/api/embeddings",
        json={
            "model": get_embedding_model(),
            "prompt": text,
        },
        timeout=120,
    )

    response.raise_for_status()
    data = response.json()

    embedding = data.get(
        "embedding"
    )

    if (
        not isinstance(
            embedding,
            list,
        )
        or not embedding
    ):
        raise RuntimeError(
            "Ollama returned an invalid embedding response."
        )

    return embedding