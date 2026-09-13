from rag.embedding import create_embedding
from rag.similarity import cosine_similarity
from rag.vector_store import VectorStore


def retrieve(
    query: str,
    top_k: int = 3,
    source: str | None = None,
) -> list[dict]:
    query_embedding = create_embedding(query)
    documents = VectorStore().get_all(source=source)

    results = []

    for document in documents:
        results.append(
            {
                "id": document["id"],
                "text": document["text"],
                "source": document["source"],
                "score": cosine_similarity(
                    query_embedding,
                    document["embedding"],
                ),
            }
        )

    results.sort(
        key=lambda item: item["score"],
        reverse=True,
    )

    return results[:top_k]