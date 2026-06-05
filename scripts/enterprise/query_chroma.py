from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

import chromadb
from chromadb.config import Settings
from sentence_transformers import SentenceTransformer


ENTERPRISE_DATA_DIR = Path(r"D:\vbpl_data_enterprise")
DEFAULT_PERSIST_DIR = ENTERPRISE_DATA_DIR / "vector_db" / "chroma_e5_base"
DEFAULT_COLLECTION = "vbpl_enterprise_e5_base"
DEFAULT_MODEL = "intfloat/multilingual-e5-base"
QUERY_PREFIX = "query: "


def _load_model(model_name: str, device: str) -> SentenceTransformer:
    return SentenceTransformer(model_name, device=device)


def _embed_query(model: SentenceTransformer, query: str) -> list[float]:
    embedding = model.encode(
        [f"{QUERY_PREFIX}{query}"],
        convert_to_numpy=True,
        normalize_embeddings=True,
        show_progress_bar=False,
    )
    return embedding.astype("float32").tolist()[0]


def _collection(persist_dir: Path, name: str):
    client = chromadb.PersistentClient(
        path=str(persist_dir),
        settings=Settings(anonymized_telemetry=False),
    )
    return client.get_collection(name=name, embedding_function=None)


def query(args: argparse.Namespace) -> list[dict[str, Any]]:
    persist_dir = Path(args.persist_dir).expanduser().resolve()
    model = _load_model(args.model_name, args.device)
    collection = _collection(persist_dir, args.collection)
    result = collection.query(
        query_embeddings=[_embed_query(model, args.query)],
        n_results=args.top_k,
        include=["documents", "metadatas", "distances"],
    )
    ids = result.get("ids", [[]])[0]
    docs = result.get("documents", [[]])[0]
    metadatas = result.get("metadatas", [[]])[0]
    distances = result.get("distances", [[]])[0]
    rows: list[dict[str, Any]] = []
    for idx, chunk_id in enumerate(ids):
        metadata = metadatas[idx] or {}
        distance = float(distances[idx])
        rows.append(
            {
                "rank": idx + 1,
                "chunk_id": chunk_id,
                "distance": distance,
                "score": 1.0 - distance,
                "canonical_doc_id": metadata.get("canonical_doc_id", ""),
                "title": metadata.get("title", ""),
                "document_number": metadata.get("document_number", ""),
                "issued_date": metadata.get("issued_date", ""),
                "status": metadata.get("status", ""),
                "topic_labels": metadata.get("topic_labels", ""),
                "retrieval_scope": metadata.get("retrieval_scope", ""),
                "article_number": metadata.get("article_number", ""),
                "clause_number": metadata.get("clause_number", ""),
                "point_key": metadata.get("point_key", ""),
                "source_url": metadata.get("source_url", ""),
                "text": docs[idx] or "",
            }
        )
    return rows


def _print_human(rows: list[dict[str, Any]]) -> None:
    for row in rows:
        cite_parts = []
        if row["article_number"]:
            cite_parts.append(f"Điều {row['article_number']}")
        if row["clause_number"]:
            cite_parts.append(f"Khoản {row['clause_number']}")
        if row["point_key"]:
            cite_parts.append(f"Điểm {row['point_key']}")
        cite = ", ".join(cite_parts) if cite_parts else "Không rõ điều/khoản/điểm"
        print(f"\n#{row['rank']} score={row['score']:.4f} distance={row['distance']:.4f}")
        print(f"Văn bản: {row['title']}")
        print(f"Số hiệu: {row['document_number']} | Ngày ban hành: {row['issued_date']}")
        print(f"Tình trạng: {row['status']} | Scope: {row['retrieval_scope']}")
        print(f"Topic: {row['topic_labels']}")
        print(f"Vị trí: {cite}")
        print(f"URL: {row['source_url']}")
        print(f"Chunk ID: {row['chunk_id']}")
        preview = str(row["text"]).replace("\n", " ")
        print(f"Nội dung: {preview[:700]}")


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description="Query local Chroma enterprise legal corpus")
    parser.add_argument("--persist-dir", default=str(DEFAULT_PERSIST_DIR))
    parser.add_argument("--collection", default=DEFAULT_COLLECTION)
    parser.add_argument("--model-name", default=DEFAULT_MODEL)
    parser.add_argument("--device", default="cpu")
    parser.add_argument("--query", required=True)
    parser.add_argument("--top-k", type=int, default=10)
    parser.add_argument("--json", action="store_true", help="Print JSON instead of human-readable output")
    args = parser.parse_args()

    rows = query(args)
    if args.json:
        print(json.dumps(rows, ensure_ascii=False, indent=2))
    else:
        _print_human(rows)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
