def split_text(
    text,
    chunk_size=500,
    overlap=50,
):
    if chunk_size <= overlap:
        raise ValueError(
            "chunk_size must be greater than overlap."
        )

    chunks = []
    start = 0

    while start < len(text):
        end = start + chunk_size
        chunk = text[start:end]

        if chunk.strip():
            chunks.append(
                chunk.strip()
            )

        start += (
            chunk_size
            - overlap
        )

    return chunks