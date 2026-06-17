# AI Trading OS - ChromaDB Vector Store
"""
...

Usage:
    from backend.vector_store import get_collection, add_documents, search

    await add_documents("knowledge", docs, embeddings)
    results = await search("knowledge", "威科夫 SOS 形态", top_k=5)
"""

from __future__ import annotations

import chromadb
from chromadb.config import Settings as ChromaSettings
from typing import Optional

from backend.config import settings

# Singleton client
_client: Optional[chromadb.PersistentClient] = None


def get_client() -> chromadb.PersistentClient:
    """Return the singleton ChromaDB persistent client."""
    global _client
    if _client is None:
        _client = chromadb.PersistentClient(
            path=settings.chroma_persist_dir,
            settings=ChromaSettings(anonymized_telemetry=False),
        )
    return _client


def get_collection(name: str) -> chromadb.Collection:
    """Get or create a named collection."""
    client = get_client()
    return client.get_or_create_collection(name=name)


# ---------------------------------------------------------------------------
# Knowledge collection helpers
# ---------------------------------------------------------------------------

async def add_knowledge_document(
    doc_id: str,
    title: str,
    content: str,
    category: str = "",
) -> None:
    """Add a knowledge base document to the vector store."""
    collection = get_collection("knowledge")
    collection.add(
        ids=[doc_id],
        documents=[content],
        metadatas=[{"title": title, "category": category}],
    )


async def search_knowledge(query: str, top_k: int = 5) -> list[dict]:
    """Search the knowledge base for relevant documents."""
    collection = get_collection("knowledge")
    results = collection.query(query_texts=[query], n_results=top_k)
    return [
        {
            "id": doc_id,
            "content": doc,
            "metadata": meta,
            "distance": dist,
        }
        for doc_id, doc, meta, dist in zip(
            results["ids"][0],
            results["documents"][0],
            results["metadatas"][0],
            results["distances"][0],
        )
    ]


# ---------------------------------------------------------------------------
# Agent memory collection helpers
# ---------------------------------------------------------------------------

async def add_memory(
    memory_id: str,
    agent_name: str,
    content: str,
    memory_type: str = "observation",
) -> None:
    """Store an agent memory entry."""
    collection = get_collection("agent_memory")
    collection.add(
        ids=[memory_id],
        documents=[content],
        metadatas=[{"agent_name": agent_name, "memory_type": memory_type}],
    )


async def search_memory(agent_name: str, query: str, top_k: int = 5) -> list[dict]:
    """Search agent memory for relevant past observations."""
    collection = get_collection("agent_memory")
    results = collection.query(
        query_texts=[query],
        n_results=top_k,
        where={"agent_name": agent_name},
    )
    return [
        {
            "id": doc_id,
            "content": doc,
            "metadata": meta,
            "distance": dist,
        }
        for doc_id, doc, meta, dist in zip(
            results["ids"][0],
            results["documents"][0],
            results["metadatas"][0],
            results["distances"][0],
        )
    ]


# ---------------------------------------------------------------------------
# Initialization
# ---------------------------------------------------------------------------

def init_vector_db():
    """Initialize ChromaDB collections on startup."""
    client = get_client()
    # Pre-create collections so they're ready for use
    client.get_or_create_collection(name="knowledge")
    client.get_or_create_collection(name="agent_memory")
    print(f"✓ ChromaDB initialized: {settings.chroma_persist_dir}")
    print(f"  Collections: knowledge, agent_memory")
