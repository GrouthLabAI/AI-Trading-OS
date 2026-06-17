# AI Trading OS - RAG (Retrieval-Augmented Generation)
"""
Knowledge base ingestion and retrieval for agent prompts.

Usage:
    # One-time ingestion:
    python -m backend.rag --ingest

    # In agents:
    from backend.rag import retrieve_context
    ctx = retrieve_context("威科夫 SOS 形态")
"""

from __future__ import annotations

import sys
from pathlib import Path

from backend.config import PROJECT_ROOT
from backend.vector_store import get_collection, init_vector_db

KNOWLEDGE_DIR = PROJECT_ROOT / "knowledge"


def ingest_knowledge_base():
    """Ingest all .md files from knowledge/ into ChromaDB."""
    init_vector_db()
    collection = get_collection("knowledge")

    # Clear existing knowledge documents
    try:
        existing = collection.get()
        if existing["ids"]:
            collection.delete(ids=existing["ids"])
    except Exception:
        pass

    files = sorted(KNOWLEDGE_DIR.glob("*.md"))
    if not files:
        print("[RAG] No knowledge files found in", KNOWLEDGE_DIR)
        return

    for f in files:
        doc_id = f.stem
        content = f.read_text(encoding="utf-8")
        title = f.stem
        category = "trading_theory"

        collection.add(
            ids=[doc_id],
            documents=[content],
            metadatas=[{"title": title, "category": category, "source": str(f)}],
        )
        print(f"[RAG] Ingested: {f.name} ({len(content)} chars)")

    print(f"[RAG] Done — {len(files)} documents ingested")


def retrieve_context(query: str, top_k: int = 3) -> str:
    """Search the knowledge base and return concatenated relevant context.

    Args:
        query: Search query (e.g., "威科夫 SOS 形态特征")
        top_k: Number of chunks to retrieve

    Returns:
        Concatenated context string, or empty string if no results.
    """
    try:
        collection = get_collection("knowledge")
        results = collection.query(query_texts=[query], n_results=top_k)

        chunks = []
        for doc, meta, dist in zip(
            results["documents"][0],
            results["metadatas"][0],
            results["distances"][0],
        ):
            title = meta.get("title", "Unknown")
            # Only include if reasonably relevant (distance < 1.5)
            if dist < 1.5:
                chunks.append(f"## {title}\n\n{doc}\n")

        return "\n---\n".join(chunks) if chunks else ""
    except Exception:
        return ""


# ── CLI ─────────────────────────────────────────────────────────────

if __name__ == "__main__":
    if "--ingest" in sys.argv:
        ingest_knowledge_base()
    elif "--query" in sys.argv:
        idx = sys.argv.index("--query")
        q = sys.argv[idx + 1] if idx + 1 < len(sys.argv) else "威科夫"
        ctx = retrieve_context(q)
        print(f"Query: {q}")
        print(f"Context ({len(ctx)} chars):\n{ctx[:500]}...")
    else:
        print("Usage: python -m backend.rag --ingest | --query '<query>'")
