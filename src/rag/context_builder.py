from rag.retriever import retrieve


def build_context(
    query: str,
    top_k: int = 3,
    source: str | None = None,
) -> str:
    results = retrieve(
        query,
        top_k=top_k,
        source=source,
    )

    if not results:
        return ""

    return "\n\n".join(
        (
            f"[Source {index}: "
            f"{result.get('source') or 'Unknown document'}]\n"
            f"{result['text']}"
        )
        for index, result in enumerate(
            results,
            start=1,
        )
    )