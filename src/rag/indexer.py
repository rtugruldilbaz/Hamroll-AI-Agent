from pathlib import Path

from rag.chunker import split_text
from rag.document_loader import load_document
from rag.embedding import create_embedding
from rag.vector_store import VectorStore


def index_document(
    document_path: str,
) -> int:
    path = Path(
        document_path
    )

    text = load_document(
        str(path)
    )

    if not text.strip():
        raise ValueError(
            "No readable text was extracted from the document."
        )

    chunks = split_text(
        text,
        chunk_size=500,
        overlap=50,
    )

    if not chunks:
        raise ValueError(
            "The document contains no content to index."
        )

    indexed_chunks = []

    for chunk in chunks:
        indexed_chunks.append(
            (
                chunk,
                create_embedding(
                    chunk
                ),
            )
        )

    VectorStore().replace_source(
        path.name,
        indexed_chunks,
    )

    return len(chunks)


def index_pdf(
    pdf_path: str,
) -> int:
    return index_document(
        pdf_path
    )