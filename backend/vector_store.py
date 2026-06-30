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
import pickle
import numpy as np
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
        self._bm25 = None
        self._bm25_data = None

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
        self._load_bm25()

    def _load_bm25(self):
        """Load the BM25 index from disk if it exists."""
        if self._bm25 is not None:
            return
        bm25_path = Path(self._persist_path) / "bm25_index.pkl"
        if bm25_path.exists():
            try:
                with open(bm25_path, "rb") as f:
                    self._bm25, self._bm25_data = pickle.load(f)
                logger.info("BM25 index loaded successfully.")
            except Exception as e:
                logger.error(f"Failed to load BM25 index: {e}")

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

        # Build and save BM25 Index
        logger.info("Building BM25 keyword index...")
        try:
            from rank_bm25 import BM25Okapi
            tokenized_corpus = [doc.lower().split() for doc in all_texts]
            self._bm25 = BM25Okapi(tokenized_corpus)
            self._bm25_data = (all_ids, all_texts, all_metas)
            
            bm25_path = Path(self._persist_path) / "bm25_index.pkl"
            with open(bm25_path, "wb") as f:
                pickle.dump((self._bm25, self._bm25_data), f)
            logger.info("BM25 keyword index built and saved.")
        except Exception as e:
            logger.error(f"Failed to build BM25 index: {e}")

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
        Fuses Semantic (Chroma) and Keyword (BM25) search using RRF.
        
        Returns:
            (context_text, category, sources, score)
        """
        self._load()

        if self._collection.count() == 0:
            logger.warning("Vector store is empty — no context retrieved.")
            return None, None, [], 0.0

        try:
            # 1. Semantic Search
            question_embedding = self._model.encode([question]).tolist()
            chroma_results = self._collection.query(
                query_embeddings=question_embedding,
                n_results=min(top_k * 2, self._collection.count()),
                include=["documents", "metadatas", "distances"],
            )

            chroma_ids = chroma_results["ids"][0] if chroma_results["ids"] else []
            chroma_distances = chroma_results["distances"][0] if chroma_results.get("distances") else []
            chroma_ranks = {cid: rank for rank, cid in enumerate(chroma_ids, 1)}

            # 2. Keyword Search (BM25)
            bm25_ranks = {}
            if self._bm25 and self._bm25_data:
                all_ids, all_texts, all_metas = self._bm25_data
                tokenized_query = question.lower().split()
                if tokenized_query:
                    doc_scores = self._bm25.get_scores(tokenized_query)
                    top_indices = np.argsort(doc_scores)[::-1][:top_k * 2]
                    for rank, idx in enumerate(top_indices, 1):
                        if doc_scores[idx] > 0:
                            bm25_ranks[all_ids[idx]] = rank

            # 3. Reciprocal Rank Fusion (RRF)
            k_rrf = 60
            fused_scores = {}
            all_retrieved_ids = set(chroma_ranks.keys()).union(set(bm25_ranks.keys()))
            
            for cid in all_retrieved_ids:
                rrf_score = 0.0
                if cid in chroma_ranks:
                    rrf_score += 1.0 / (k_rrf + chroma_ranks[cid])
                if cid in bm25_ranks:
                    rrf_score += 1.0 / (k_rrf + bm25_ranks[cid])
                fused_scores[cid] = rrf_score
                
            sorted_fused_ids = sorted(fused_scores.keys(), key=lambda x: fused_scores[x], reverse=True)[:top_k]
            
            if not sorted_fused_ids:
                return None, None, [], 0.0
                
            # 4. Reconstruct response
            all_ids, all_texts, all_metas = self._bm25_data if self._bm25_data else ([], [], [])
            id_to_idx = {cid: idx for idx, cid in enumerate(all_ids)}
            
            context_parts: List[str] = []
            sources: List[str] = []
            seen_docs = set()
            
            for cid in sorted_fused_ids:
                if cid in id_to_idx:
                    idx = id_to_idx[cid]
                    doc_text = all_texts[idx]
                    meta = all_metas[idx]
                    
                    doc_name = meta.get("doc", "Unknown")
                    section = meta.get("section", "")
                    header = f"[{doc_name} — {section}]" if section else f"[{doc_name}]"
                    context_parts.append(f"{header}\n{doc_text}")
                    if doc_name not in seen_docs:
                        sources.append(doc_name)
                        seen_docs.add(doc_name)

            top_meta = all_metas[id_to_idx[sorted_fused_ids[0]]] if sorted_fused_ids and sorted_fused_ids[0] in id_to_idx else {}
            category = top_meta.get("doc")

            # Semantic score approximation
            top_distance = chroma_distances[0] if chroma_distances else 1.0
            score = max(0.0, min(1.0, 1.0 - (top_distance / 2.0)))

            context_text = "\n\n".join(context_parts)
            logger.info(
                f"Hybrid retrieval: top_score={score:.3f}, "
                f"sources={sources[:3]}, chunks={len(context_parts)}"
            )

            return context_text, category, sources, score

        except Exception as e:
            logger.error(f"Vector retrieval failed: {e}", exc_info=True)
            return None, None, [], 0.0
