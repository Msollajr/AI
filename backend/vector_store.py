"""
vector_store.py
---------------
Semantic vector store for the UDSM Student Support AI.

Replaces the keyword-overlap RAG engine with ChromaDB-backed cosine similarity
search using the all-MiniLM-L6-v2 sentence-transformers model (80 MB, CPU-only).

Key design decisions:
  - Chunks markdown docs at ## section boundaries first, then by word count
  - 300-word target chunk size with 50-word overlap to preserve context
  - Persists to disk (backend/vector_store/) — only rebuilds when doc count changes
  - Returns same (context, category, sources, score) tuple as the old retrieve_context()
    so generate_response() needs zero changes
"""

import hashlib
import json
import logging
import re
from pathlib import Path
from typing import Optional, List, Tuple

logger = logging.getLogger(__name__)

# Lazy globals — loaded once on first use to avoid slowing down test imports
_embedding_model = None
_chroma_client = None


def _get_embedding_model():
    """Load the sentence-transformers model from local cache (no network required)."""
    global _embedding_model
    if _embedding_model is None:
        logger.info("Loading sentence-transformers embedding model (all-MiniLM-L6-v2)...")
        import os
        from sentence_transformers import SentenceTransformer
        # Use locally cached model — avoids network calls on every load.
        # The model was downloaded on first use and is stored in the HF cache.
        os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")
        os.environ.setdefault("HF_DATASETS_OFFLINE", "1")
        try:
            _embedding_model = SentenceTransformer(
                "all-MiniLM-L6-v2",
                local_files_only=True,
            )
        except Exception:
            # First-time download fallback (no cache yet)
            logger.info("Model not in cache — downloading from HuggingFace (one-time only)...")
            os.environ.pop("TRANSFORMERS_OFFLINE", None)
            _embedding_model = SentenceTransformer("all-MiniLM-L6-v2")
        logger.info("Embedding model loaded successfully.")
    return _embedding_model


def _get_chroma_client(persist_path: str):
    """Return a persistent ChromaDB client."""
    global _chroma_client
    if _chroma_client is None:
        import chromadb
        _chroma_client = chromadb.PersistentClient(path=persist_path)
        logger.info(f"ChromaDB client initialised at: {persist_path}")
    return _chroma_client


class VectorStore:
    """
    Semantic knowledge-base index backed by ChromaDB + sentence-transformers.

    Usage:
        vs = VectorStore()
        vs.build(Path("knowledge-base/"))          # index all .md files
        ctx, cat, srcs, score = vs.retrieve("how do I pay fees?")
    """

    COLLECTION_NAME = "udsm_knowledge_base"
    CHUNK_TARGET_WORDS = 300
    CHUNK_OVERLAP_WORDS = 50
    TOP_K = 5
    # File used to persist the content hash of the last successful index build
    _HASH_FILE_NAME = "content_hash.json"

    def __init__(self):
        from config import VECTOR_STORE_PATH
        self._persist_path = str(VECTOR_STORE_PATH)
        self._model = None
        self._client = None
        self._collection = None

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _load(self):
        """Ensure embedding model and ChromaDB collection are ready."""
        if self._collection is not None:
            return
        self._model = _get_embedding_model()
        self._client = _get_chroma_client(self._persist_path)
        self._collection = self._client.get_or_create_collection(
            name=self.COLLECTION_NAME,
            metadata={"hnsw:space": "cosine"}
        )

    # ------------------------------------------------------------------
    # Content-hash helpers — detect doc changes automatically
    # ------------------------------------------------------------------

    def _compute_content_hash(self, md_files: List[Path]) -> str:
        """Return a SHA-256 digest covering the path and content of every .md file."""
        h = hashlib.sha256()
        for f in sorted(md_files):          # sorted for determinism
            h.update(str(f).encode())
            h.update(f.read_bytes())
        return h.hexdigest()

    def _load_saved_hash(self) -> Optional[str]:
        """Read the hash stored from the last successful build, or None."""
        hash_path = Path(self._persist_path) / self._HASH_FILE_NAME
        try:
            if hash_path.exists():
                return json.loads(hash_path.read_text(encoding="utf-8")).get("hash")
        except Exception:
            pass
        return None

    def _save_hash(self, digest: str) -> None:
        """Persist the current content hash to disk."""
        hash_path = Path(self._persist_path) / self._HASH_FILE_NAME
        hash_path.write_text(json.dumps({"hash": digest}), encoding="utf-8")

    def _chunk_markdown(self, doc_name: str, content: str) -> List[dict]:
        """
        Split a markdown document into semantically meaningful chunks.

        Strategy:
          1. Split on ## headers (section boundaries)
          2. If a section exceeds CHUNK_TARGET_WORDS, slide a window through it
             with CHUNK_OVERLAP_WORDS overlap to preserve context across boundaries.

        Returns list of dicts: {text, doc, section}
        """
        chunks = []
        # Split on ## headings, keeping the heading attached to its section body
        sections = re.split(r'\n(?=## )', content)

        for section in sections:
            lines = section.strip().split('\n')
            if not lines:
                continue
            # Extract section title from the first heading line
            heading_match = re.match(r'^#{1,3}\s+(.*)', lines[0])
            section_title = heading_match.group(1).strip() if heading_match else doc_name

            words = section.split()
            if len(words) <= self.CHUNK_TARGET_WORDS:
                # Short section: one chunk
                chunks.append({
                    "text": section.strip(),
                    "doc": doc_name,
                    "section": section_title,
                })
            else:
                # Long section: sliding window
                step = self.CHUNK_TARGET_WORDS - self.CHUNK_OVERLAP_WORDS
                for i in range(0, len(words), step):
                    window = words[i: i + self.CHUNK_TARGET_WORDS]
                    if len(window) < 30:   # skip tiny tail fragments
                        continue
                    chunks.append({
                        "text": " ".join(window),
                        "doc": doc_name,
                        "section": section_title,
                    })

        return chunks

    def _make_chunk_id(self, doc_name: str, section: str, idx: int) -> str:
        """Deterministic chunk ID — ensures upsert is idempotent."""
        safe = re.sub(r'[^a-z0-9]', '_', (doc_name + "_" + section).lower())
        return f"{safe}_{idx}"

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def is_built(self) -> bool:
        """Return True if the collection already contains indexed documents."""
        try:
            self._load()
            return self._collection.count() > 0
        except Exception:
            return False

    def build(self, kb_path: Path, force: bool = False) -> int:
        """
        Index all .md files found in kb_path into ChromaDB.

        Auto-detects changes: if any .md file has been added, removed, or modified
        since the last build the collection is rebuilt automatically.
        Pass force=True to force a full rebuild regardless.

        Returns total number of chunks in the collection after building.
        """
        self._load()

        md_files = sorted(kb_path.rglob("*.md"))   # recursive — includes scraped/ subdir
        if not md_files:
            logger.warning(f"No .md files found in knowledge base path: {kb_path}")
            return 0

        # Compute current content hash and compare with the saved one
        current_hash = self._compute_content_hash(md_files)
        saved_hash = self._load_saved_hash()
        existing_count = self._collection.count()

        if existing_count > 0 and not force and current_hash == saved_hash:
            logger.info(
                f"Vector store up-to-date ({existing_count} chunks, hash unchanged). "
                "Skipping re-index."
            )
            return existing_count

        if existing_count > 0 and current_hash != saved_hash:
            logger.info(
                "Knowledge-base documents have changed — rebuilding vector index..."
            )
        elif force:
            logger.info("Force rebuild requested — rebuilding vector index...")

        logger.info(f"Building vector index from {len(md_files)} documents...")

        all_ids: List[str] = []
        all_texts: List[str] = []
        all_metas: List[dict] = []

        for md_file in md_files:
            try:
                content = md_file.read_text(encoding="utf-8")
                doc_name = md_file.stem.replace("-", " ").title()
                chunks = self._chunk_markdown(doc_name, content)

                for idx, chunk in enumerate(chunks):
                    chunk_id = self._make_chunk_id(chunk["doc"], chunk["section"], idx)
                    all_ids.append(chunk_id)
                    all_texts.append(chunk["text"])
                    all_metas.append({
                        "doc": chunk["doc"],
                        "section": chunk["section"],
                        "source_file": md_file.name,
                    })

                logger.info(f"  Chunked '{doc_name}' → {len(chunks)} chunks")
            except Exception as e:
                logger.error(f"  Error processing {md_file.name}: {e}")

        if not all_texts:
            logger.warning("No text chunks generated — vector store is empty.")
            return 0

        # Embed all chunks in a single efficient batch
        logger.info(f"Embedding {len(all_texts)} chunks (may take ~30s on first run)...")
        embeddings = self._model.encode(
            all_texts,
            batch_size=32,
            show_progress_bar=False
        ).tolist()

        # Upsert into ChromaDB — safe to call multiple times
        self._collection.upsert(
            ids=all_ids,
            documents=all_texts,
            embeddings=embeddings,
            metadatas=all_metas,
        )

        total = self._collection.count()
        # Persist the hash so subsequent runs can detect changes automatically
        self._save_hash(current_hash)
        logger.info(f"Vector store built successfully. Total chunks indexed: {total}")
        return total

    def retrieve(
        self,
        question: str,
        top_k: int = TOP_K
    ) -> Tuple[Optional[str], Optional[str], List[str], float]:
        """
        Embed the question and return the top-k most semantically similar chunks.

        Returns:
            (context_text, category, sources, score)
            - context_text : combined text of top chunks, ready to inject into prompt
            - category     : inferred from the top-matching document name
            - sources      : deduplicated list of source document names
            - score        : 0.0 – 1.0 relevance score (converted from cosine distance)
        """
        self._load()

        if self._collection.count() == 0:
            logger.warning("Vector store is empty — no context retrieved.")
            return None, None, [], 0.0

        try:
            question_embedding = self._model.encode([question]).tolist()

            results = self._collection.query(
                query_embeddings=question_embedding,
                n_results=min(top_k, self._collection.count()),
                include=["documents", "metadatas", "distances"],
            )

            documents: List[str] = results["documents"][0]
            metadatas: List[dict] = results["metadatas"][0]
            distances: List[float] = results["distances"][0]

            if not documents:
                return None, None, [], 0.0

            # Build context string with source attribution headers
            context_parts: List[str] = []
            sources: List[str] = []
            seen_docs = set()

            for doc_text, meta, dist in zip(documents, metadatas, distances):
                doc_name = meta.get("doc", "Unknown")
                section = meta.get("section", "")
                header = f"[{doc_name} — {section}]" if section else f"[{doc_name}]"
                context_parts.append(f"{header}\n{doc_text}")
                if doc_name not in seen_docs:
                    sources.append(doc_name)
                    seen_docs.add(doc_name)

            # Primary category = top result's document
            category = metadatas[0].get("doc") if metadatas else None

            # ChromaDB cosine distance: 0 = identical, 2 = opposite
            # Convert to similarity in [0, 1]: similarity = 1 - (distance / 2)
            top_distance = distances[0] if distances else 1.0
            score = max(0.0, min(1.0, 1.0 - (top_distance / 2.0)))

            context_text = "\n\n".join(context_parts)
            logger.info(
                f"Vector retrieval: top_score={score:.3f}, "
                f"sources={sources[:3]}, chunks={len(documents)}"
            )

            return context_text, category, sources, score

        except Exception as e:
            logger.error(f"Vector retrieval failed: {e}", exc_info=True)
            return None, None, [], 0.0
