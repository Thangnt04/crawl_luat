from __future__ import annotations

import argparse
from collections.abc import Iterable
from datetime import datetime, timezone
import json
from pathlib import Path
import shutil
import time
from typing import Any

import chromadb
from chromadb.config import Settings
from sentence_transformers import SentenceTransformer


ENTERPRISE_DATA_DIR = Path(r"D:\vbpl_data_enterprise")
DEFAULT_SOURCE = ENTERPRISE_DATA_DIR / "processed" / "rag_chunks_clean.jsonl"
DEFAULT_PERSIST_DIR = ENTERPRISE_DATA_DIR / "vector_db" / "chroma_e5_base"
DEFAULT_REPORT_PATH = ENTERPRISE_DATA_DIR / "processed" / "vector_ingestion_report.json"
DEFAULT_COLLECTION = "vbpl_enterprise_e5_base"
DEFAULT_MODEL = "intfloat/multilingual-e5-base"
PASSAGE_PREFIX = "passage: "
QUERY_PREFIX = "query: "
SAMPLE_QUERIES = [
    "doanh nghiệp siêu nhỏ chế độ kế toán",
    "đăng ký kinh doanh ngành nghề",
    "doanh nghiệp bán hàng đa cấp",
    "hộ kinh doanh sau đăng ký thành lập",
]
METADATA_FIELDS = [
    "canonical_doc_id",
    "title",
    "document_number",
    "issued_date",
    "article_number",
    "clause_number",
    "point_key",
    "source_url",
    "document_type",
    "effective_date",
    "status",
    "field",
    "topic_labels",
    "topic_names",
    "matched_keywords",
    "retrieval_scope",
    "source",
    "source_level",
    "char_count",
]


def _jsonl_items(path: Path, limit: int = 0) -> Iterable[tuple[int, dict[str, Any]]]:
    emitted = 0
    with path.open("r", encoding="utf-8") as f:
        for line_no, line in enumerate(f, start=1):
            if not line.strip():
                continue
            yield line_no, json.loads(line)
            emitted += 1
            if limit and emitted >= limit:
                break


def _metadata(item: dict[str, Any]) -> dict[str, str | int | float | bool]:
    metadata: dict[str, str | int | float | bool] = {}
    for field in METADATA_FIELDS:
        value = item.get(field)
        if value is None:
            value = ""
        if isinstance(value, (str, int, float, bool)):
            metadata[field] = value
        else:
            metadata[field] = json.dumps(value, ensure_ascii=False)
    return metadata


def _embedding_text(item: dict[str, Any]) -> str:
    title = str(item.get("title") or "").strip()
    text = str(item.get("text") or "").strip()
    if title and title not in text[:300]:
        return f"{PASSAGE_PREFIX}{title}\n{text}"
    return f"{PASSAGE_PREFIX}{text}"


def _load_model(model_name: str, device: str) -> SentenceTransformer:
    return SentenceTransformer(model_name, device=device)


def _client(persist_dir: Path):
    persist_dir.mkdir(parents=True, exist_ok=True)
    return chromadb.PersistentClient(
        path=str(persist_dir),
        settings=Settings(anonymized_telemetry=False),
    )


def _backup_store(persist_dir: Path) -> str:
    if not persist_dir.exists():
        return ""
    ts = datetime.now().strftime("%Y%m%dT%H%M%S")
    backup_dir = persist_dir.with_name(f"{persist_dir.name}_backup_{ts}")
    shutil.move(str(persist_dir), str(backup_dir))
    return str(backup_dir)


def _collection(client, name: str, reset: bool):
    if reset:
        try:
            client.delete_collection(name=name)
        except Exception:
            pass
    return client.get_or_create_collection(
        name=name,
        metadata={"hnsw:space": "cosine"},
        embedding_function=None,
    )


def _embed(model: SentenceTransformer, texts: list[str]) -> list[list[float]]:
    embeddings = model.encode(
        texts,
        batch_size=len(texts),
        convert_to_numpy=True,
        normalize_embeddings=True,
        show_progress_bar=False,
    )
    return embeddings.astype("float32").tolist()


def _query_samples(collection, model: SentenceTransformer, top_k: int) -> dict[str, list[dict[str, Any]]]:
    report: dict[str, list[dict[str, Any]]] = {}
    for query in SAMPLE_QUERIES:
        embedding = _embed(model, [f"{QUERY_PREFIX}{query}"])[0]
        result = collection.query(
            query_embeddings=[embedding],
            n_results=top_k,
            include=["documents", "metadatas", "distances"],
        )
        rows: list[dict[str, Any]] = []
        ids = result.get("ids", [[]])[0]
        docs = result.get("documents", [[]])[0]
        metadatas = result.get("metadatas", [[]])[0]
        distances = result.get("distances", [[]])[0]
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
                    "topic_labels": metadata.get("topic_labels", ""),
                    "article_number": metadata.get("article_number", ""),
                    "clause_number": metadata.get("clause_number", ""),
                    "point_key": metadata.get("point_key", ""),
                    "source_url": metadata.get("source_url", ""),
                    "text_preview": str(docs[idx] or "")[:500],
                }
            )
        report[query] = rows
    return report


def ingest(args: argparse.Namespace) -> dict[str, Any]:
    source = Path(args.source).expanduser().resolve()
    persist_dir = Path(args.persist_dir).expanduser().resolve()
    report_path = Path(args.report_path).expanduser().resolve()
    if not source.exists():
        raise FileNotFoundError(f"Source JSONL not found: {source}")

    start = time.time()
    model = _load_model(args.model_name, args.device)
    embedding_dimension = int(model.get_sentence_embedding_dimension() or 0)
    backup_dir = _backup_store(persist_dir) if args.reset_store else ""
    client = _client(persist_dir)
    collection = _collection(client, args.collection, reset=args.reset)

    stats = {
        "source_rows_seen": 0,
        "ingested": 0,
        "skipped": 0,
        "invalid_json": 0,
        "missing_required": 0,
    }
    batch_ids: list[str] = []
    batch_documents: list[str] = []
    batch_metadatas: list[dict[str, str | int | float | bool]] = []
    batch_embedding_texts: list[str] = []

    def flush() -> None:
        if not batch_ids:
            return
        embeddings = _embed(model, batch_embedding_texts)
        collection.upsert(
            ids=list(batch_ids),
            documents=list(batch_documents),
            metadatas=list(batch_metadatas),
            embeddings=embeddings,
        )
        stats["ingested"] += len(batch_ids)
        batch_ids.clear()
        batch_documents.clear()
        batch_metadatas.clear()
        batch_embedding_texts.clear()
        print(
            f"ingested={stats['ingested']} skipped={stats['skipped']} "
            f"collection_count={collection.count()}",
            flush=True,
        )

    try:
        for line_no, item in _jsonl_items(source, limit=args.limit):
            stats["source_rows_seen"] += 1
            chunk_id = str(item.get("chunk_id") or "").strip()
            text = str(item.get("text") or "").strip()
            canonical_doc_id = str(item.get("canonical_doc_id") or "").strip()
            title = str(item.get("title") or "").strip()
            source_url = str(item.get("source_url") or "").strip()
            if not (chunk_id and text and canonical_doc_id and title and source_url):
                stats["missing_required"] += 1
                stats["skipped"] += 1
                continue

            batch_ids.append(chunk_id)
            batch_documents.append(text)
            batch_metadatas.append(_metadata(item))
            batch_embedding_texts.append(_embedding_text(item))
            if len(batch_ids) >= args.batch_size:
                flush()
        flush()
    except json.JSONDecodeError:
        stats["invalid_json"] += 1
        raise

    collection_count = collection.count()
    sample_results = {} if args.skip_sample_queries else _query_samples(collection, model, args.top_k)
    elapsed_seconds = round(time.time() - start, 3)
    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source": str(source),
        "persist_dir": str(persist_dir),
        "collection": args.collection,
        "model_name": args.model_name,
        "embedding_dimension": embedding_dimension,
        "device": args.device,
        "batch_size": args.batch_size,
        "limit": args.limit,
        "collection_count": collection_count,
        "elapsed_seconds": elapsed_seconds,
        "backup_dir": backup_dir,
        "stats": stats,
        "sample_queries": sample_results,
    }
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description="Ingest enterprise RAG chunks into local Chroma")
    parser.add_argument("--source", default=str(DEFAULT_SOURCE))
    parser.add_argument("--persist-dir", default=str(DEFAULT_PERSIST_DIR))
    parser.add_argument("--collection", default=DEFAULT_COLLECTION)
    parser.add_argument("--model-name", default=DEFAULT_MODEL)
    parser.add_argument("--device", default="cpu")
    parser.add_argument("--batch-size", type=int, default=64)
    parser.add_argument("--limit", type=int, default=0, help="0 means all chunks")
    parser.add_argument("--reset", action="store_true", help="Delete and recreate the collection before ingest")
    parser.add_argument(
        "--reset-store",
        action="store_true",
        help="Move the whole Chroma persist directory to a timestamped backup before ingest",
    )
    parser.add_argument("--report-path", default=str(DEFAULT_REPORT_PATH))
    parser.add_argument("--top-k", type=int, default=5)
    parser.add_argument("--skip-sample-queries", action="store_true")
    args = parser.parse_args()

    if args.batch_size <= 0:
        raise ValueError("--batch-size must be positive")
    report = ingest(args)
    print(json.dumps({k: report[k] for k in ["collection_count", "elapsed_seconds", "stats"]}, ensure_ascii=False, indent=2))
    print(f"Report: {args.report_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
