from __future__ import annotations

import json
from pathlib import Path


OUTPUT = Path("notebooks/vbpl_enterprise_chroma_colab.ipynb")


def _markdown(source: str) -> dict:
    return {
        "cell_type": "markdown",
        "metadata": {},
        "source": source.strip().splitlines(True),
    }


def _code(source: str) -> dict:
    return {
        "cell_type": "code",
        "execution_count": None,
        "metadata": {},
        "outputs": [],
        "source": source.strip().splitlines(True),
    }


def build_notebook() -> dict:
    cells: list[dict] = []

    cells.append(
        _markdown(
            """
# VBPL Enterprise RAG - Colab Chroma Ingest

Notebook này dùng để test và ingest vector DB trên Google Colab cho chatbot luật doanh nghiệp.

Mục tiêu:
- Dùng `rag_chunks_current.jsonl` làm nguồn embedding chính.
- Chỉ dùng văn bản `Còn hiệu lực` và `Hết hiệu lực một phần` đã được lọc sẵn.
- Ingest vào Chroma bằng model `intfloat/multilingual-e5-base`.
- Test retrieval trước khi xây chatbot với `@cf/google/gemma-4-26b-a4b-it`.

Phạm vi không xử lý trong notebook này:
- Không train LLM.
- Không OCR PDF scan.
- Không crawl thêm dữ liệu.

OCR hiện vẫn là phase riêng. File `rag_ingestion_issues.jsonl` hiện có nhóm `needs_ocr`, nhưng notebook này tập trung làm embedding/vector DB trước.
"""
        )
    )

    cells.append(
        _markdown(
            r"""
## Bước 0 - Chuẩn bị data trên Google Drive

Trên máy Windows của bạn, file nguồn hiện nằm ở:

```text
D:\vbpl_data_enterprise\processed\rag_chunks_current.jsonl
```

Trên Google Drive, tạo thư mục:

```text
MyDrive/vbpl_enterprise_colab/processed
```

Sau đó upload file này vào đúng thư mục trên:

```text
MyDrive/vbpl_enterprise_colab/processed/rag_chunks_current.jsonl
```

Khuyến nghị:
- Không dùng `rag_chunks_clean.jsonl` cho chatbot chính vì file đó còn chứa nhiều văn bản hết hiệu lực toàn bộ.
- Không dùng upload trực tiếp qua `files.upload()` của Colab cho file 1GB; hãy upload bằng giao diện Google Drive web.
- Nếu muốn upload nhẹ hơn, có thể nén gzip và đổi `SOURCE_FILENAME` ở cell cấu hình thành `rag_chunks_current.jsonl.gz`.
"""
        )
    )

    cells.append(
        _code(
            """
from google.colab import drive
drive.mount('/content/drive')
"""
        )
    )

    cells.append(
        _markdown(
            """
## Bước 1 - Cấu hình đường dẫn

Nếu bạn upload data vào folder khác trên Drive, chỉ sửa `DRIVE_ROOT` hoặc `SOURCE_FILENAME` ở cell dưới.
"""
        )
    )

    cells.append(
        _code(
            """
from pathlib import Path

DRIVE_ROOT = Path('/content/drive/MyDrive/vbpl_enterprise_colab')
PROCESSED_DIR = DRIVE_ROOT / 'processed'
VECTOR_DIR = DRIVE_ROOT / 'vector_db'
REPORT_DIR = PROCESSED_DIR

SOURCE_FILENAME = 'rag_chunks_current.jsonl'  # đổi thành rag_chunks_current.jsonl.gz nếu bạn upload gzip
SOURCE_ON_DRIVE = PROCESSED_DIR / SOURCE_FILENAME

LOCAL_WORK_DIR = Path('/content/vbpl_enterprise_work')
LOCAL_SOURCE = LOCAL_WORK_DIR / SOURCE_FILENAME

# False = nhanh hơn: ghi Chroma vào /content, cuối notebook nén/copy về Drive.
# True = an toàn hơn cho full ingest dài: ghi trực tiếp vào Drive, chậm hơn nhưng runtime ngắt thì ít mất progress hơn.
USE_DRIVE_PERSIST = False
LOCAL_PERSIST_DIR = (VECTOR_DIR / 'chroma_e5_current_working') if USE_DRIVE_PERSIST else Path('/content/chroma_e5_current')

COLLECTION_NAME = 'vbpl_enterprise_current_e5_base'
MODEL_NAME = 'intfloat/multilingual-e5-base'

PILOT_LIMIT = 10_000
BATCH_SIZE = 64

print('SOURCE_ON_DRIVE   =', SOURCE_ON_DRIVE)
print('LOCAL_SOURCE      =', LOCAL_SOURCE)
print('USE_DRIVE_PERSIST =', USE_DRIVE_PERSIST)
print('PERSIST_DIR       =', LOCAL_PERSIST_DIR)
print('COLLECTION        =', COLLECTION_NAME)
print('MODEL             =', MODEL_NAME)
"""
        )
    )

    cells.append(
        _code(
            """
assert SOURCE_ON_DRIVE.exists(), f'Không thấy file nguồn: {SOURCE_ON_DRIVE}'
size_gb = SOURCE_ON_DRIVE.stat().st_size / (1024 ** 3)
print(f'OK: thấy file nguồn trên Drive, size = {size_gb:.2f} GB')
PROCESSED_DIR.mkdir(parents=True, exist_ok=True)
VECTOR_DIR.mkdir(parents=True, exist_ok=True)
LOCAL_WORK_DIR.mkdir(parents=True, exist_ok=True)
"""
        )
    )

    cells.append(
        _markdown(
            """
## Bước 2 - Cài thư viện

Chạy cell này một lần sau khi mở runtime Colab.

Cell này pin bộ dependency ổn định cho Colab Python 3.12:
- `numpy==1.26.4` để tránh lỗi Chroma với NumPy 2.
- `transformers==4.41.2` để tránh kéo bản quá mới gây lỗi import với runtime hiện tại.
- Gỡ `peft` vì Colab có thể cài sẵn bản không tương thích, gây lỗi `EncoderDecoderCache`.

Sau khi cài xong lần đầu, cell sẽ tự restart runtime. Sau restart, chạy lại từ Bước 0.
"""
        )
    )

    cells.append(
        _code(
            """
from pathlib import Path
import os
import time

DEPS_MARKER = Path('/content/.vbpl_deps_numpy126_chroma0424_st301_tf4412_nopeft')

if not DEPS_MARKER.exists():
    print('Đang cài dependency ổn định cho Colab...')
    !pip -q install --upgrade --force-reinstall "numpy==1.26.4"
    !pip -q install --upgrade "chromadb==0.4.24" "sentence-transformers==3.0.1" "transformers==4.41.2"
    !pip -q uninstall -y peft
    DEPS_MARKER.write_text('installed', encoding='utf-8')
    print('Đã cài xong. Runtime sẽ restart để tránh lỗi binary NumPy.')
    time.sleep(2)
    os.kill(os.getpid(), 9)
else:
    print('Dependency marker đã tồn tại, bỏ qua cài lại.')
    print('Nếu vẫn lỗi import/numpy, hãy Runtime -> Disconnect and delete runtime, rồi chạy lại notebook từ đầu.')
"""
        )
    )

    cells.append(
        _markdown(
            """
## Bước 3 - Kiểm tra GPU

Vào menu Colab:

```text
Runtime -> Change runtime type -> Hardware accelerator -> T4 GPU
```

Nếu không có GPU, notebook vẫn chạy CPU nhưng sẽ chậm.
"""
        )
    )

    cells.append(
        _code(
            """
import torch

DEVICE = 'cuda' if torch.cuda.is_available() else 'cpu'
print('torch:', torch.__version__)
print('device:', DEVICE)
if DEVICE == 'cuda':
    print('gpu:', torch.cuda.get_device_name(0))
    !nvidia-smi
"""
        )
    )

    cells.append(
        _markdown(
            """
## Bước 4 - Copy data từ Drive vào disk local Colab

Đọc trực tiếp file 1GB từ Drive sẽ chậm. Cell này copy file sang `/content` để ingest nhanh hơn.
"""
        )
    )

    cells.append(
        _code(
            """
import shutil
import time

start = time.time()
need_copy = True
if LOCAL_SOURCE.exists() and LOCAL_SOURCE.stat().st_size == SOURCE_ON_DRIVE.stat().st_size:
    need_copy = False

if need_copy:
    print('Đang copy data từ Drive sang local Colab...')
    shutil.copy2(SOURCE_ON_DRIVE, LOCAL_SOURCE)
else:
    print('Local source đã tồn tại và cùng size, bỏ qua copy.')

elapsed = time.time() - start
print('SOURCE_FILE =', LOCAL_SOURCE)
print(f'Copy/check elapsed = {elapsed:.1f}s')
"""
        )
    )

    cells.append(
        _markdown(
            """
## Bước 5 - Định nghĩa hàm ingest/query Chroma

Cell này là self-contained, không cần copy script Python từ project Windows.
"""
        )
    )

    cells.append(
        _code(
            """
import gzip
import json
import shutil
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import importlib.util
import os
import numpy as np

os.environ['ANONYMIZED_TELEMETRY'] = 'False'

if importlib.util.find_spec('peft') is not None:
    raise RuntimeError(
        'Runtime vẫn còn package peft, package này gây lỗi import với transformers đã pin. '
        'Hãy chạy lại Bước 2 hoặc Runtime -> Disconnect and delete runtime rồi chạy lại từ đầu.'
    )

# Chroma 0.4.24 still references np.float_, which NumPy 2 removed.
# This keeps the notebook usable even if Colab has not restarted after package install.
if not hasattr(np, 'float_'):
    np.float_ = np.float64

import chromadb
from chromadb.config import Settings
from sentence_transformers import SentenceTransformer

PASSAGE_PREFIX = 'passage: '
QUERY_PREFIX = 'query: '

METADATA_FIELDS = [
    'canonical_doc_id',
    'title',
    'document_number',
    'issued_date',
    'article_number',
    'clause_number',
    'point_key',
    'source_url',
    'document_type',
    'effective_date',
    'status',
    'field',
    'topic_labels',
    'topic_names',
    'matched_keywords',
    'retrieval_scope',
    'source',
    'source_level',
    'char_count',
]


def iter_jsonl(path: Path, limit: int = 0):
    emitted = 0
    opener = gzip.open if str(path).endswith('.gz') else open
    mode = 'rt' if str(path).endswith('.gz') else 'r'
    with opener(path, mode, encoding='utf-8-sig') as f:
        for line_no, line in enumerate(f, start=1):
            if not line.strip():
                continue
            yield line_no, json.loads(line)
            emitted += 1
            if limit and emitted >= limit:
                break


def to_chroma_metadata(item: dict[str, Any]) -> dict[str, str | int | float | bool]:
    metadata = {}
    for field in METADATA_FIELDS:
        value = item.get(field)
        if value is None:
            value = ''
        if isinstance(value, (str, int, float, bool)):
            metadata[field] = value
        else:
            metadata[field] = json.dumps(value, ensure_ascii=False)
    return metadata


def embedding_text(item: dict[str, Any]) -> str:
    title = str(item.get('title') or '').strip()
    text = str(item.get('text') or '').strip()
    if title and title not in text[:300]:
        return f'{PASSAGE_PREFIX}{title}\\n{text}'
    return f'{PASSAGE_PREFIX}{text}'


def backup_store(persist_dir: Path) -> str:
    if not persist_dir.exists():
        return ''
    ts = datetime.now().strftime('%Y%m%dT%H%M%S')
    backup_dir = persist_dir.with_name(f'{persist_dir.name}_backup_{ts}')
    shutil.move(str(persist_dir), str(backup_dir))
    return str(backup_dir)


def get_collection(persist_dir: Path, collection_name: str, reset_store: bool = False):
    backup_dir = backup_store(persist_dir) if reset_store else ''
    persist_dir.mkdir(parents=True, exist_ok=True)
    client = chromadb.PersistentClient(
        path=str(persist_dir),
        settings=Settings(anonymized_telemetry=False),
    )
    collection = client.get_or_create_collection(
        name=collection_name,
        metadata={'hnsw:space': 'cosine'},
        embedding_function=None,
    )
    return collection, backup_dir


def embed_texts(model: SentenceTransformer, texts: list[str], batch_size: int):
    embeddings = model.encode(
        texts,
        batch_size=batch_size,
        convert_to_numpy=True,
        normalize_embeddings=True,
        show_progress_bar=False,
    )
    return embeddings.astype('float32').tolist()


def ingest_chunks(
    source_file: Path,
    persist_dir: Path,
    collection_name: str,
    model: SentenceTransformer,
    limit: int = 0,
    batch_size: int = 64,
    reset_store: bool = False,
    report_path: Path | None = None,
):
    start = time.time()
    collection, backup_dir = get_collection(persist_dir, collection_name, reset_store=reset_store)
    stats = {
        'source_rows_seen': 0,
        'ingested': 0,
        'skipped': 0,
        'invalid_json': 0,
        'missing_required': 0,
    }
    batch_ids = []
    batch_documents = []
    batch_metadatas = []
    batch_embedding_texts = []

    def flush():
        if not batch_ids:
            return
        embeddings = embed_texts(model, batch_embedding_texts, batch_size=batch_size)
        collection.upsert(
            ids=list(batch_ids),
            documents=list(batch_documents),
            metadatas=list(batch_metadatas),
            embeddings=embeddings,
        )
        stats['ingested'] += len(batch_ids)
        batch_ids.clear()
        batch_documents.clear()
        batch_metadatas.clear()
        batch_embedding_texts.clear()
        print(
            f\"ingested={stats['ingested']} skipped={stats['skipped']} \"
            f\"collection_count={collection.count()}\",
            flush=True,
        )

    try:
        for line_no, item in iter_jsonl(source_file, limit=limit):
            stats['source_rows_seen'] += 1
            chunk_id = str(item.get('chunk_id') or '').strip()
            text = str(item.get('text') or '').strip()
            canonical_doc_id = str(item.get('canonical_doc_id') or '').strip()
            title = str(item.get('title') or '').strip()
            source_url = str(item.get('source_url') or '').strip()
            if not (chunk_id and text and canonical_doc_id and title and source_url):
                stats['missing_required'] += 1
                stats['skipped'] += 1
                continue
            batch_ids.append(chunk_id)
            batch_documents.append(text)
            batch_metadatas.append(to_chroma_metadata(item))
            batch_embedding_texts.append(embedding_text(item))
            if len(batch_ids) >= batch_size:
                flush()
        flush()
    except json.JSONDecodeError:
        stats['invalid_json'] += 1
        raise

    elapsed_seconds = round(time.time() - start, 3)
    report = {
        'generated_at': datetime.now(timezone.utc).isoformat(),
        'source': str(source_file),
        'persist_dir': str(persist_dir),
        'collection': collection_name,
        'model_name': MODEL_NAME,
        'embedding_dimension': int(model.get_sentence_embedding_dimension() or 0),
        'device': DEVICE,
        'batch_size': batch_size,
        'limit': limit,
        'collection_count': collection.count(),
        'elapsed_seconds': elapsed_seconds,
        'backup_dir': backup_dir,
        'stats': stats,
    }
    if report_path is not None:
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
        print('Report:', report_path)
    print(json.dumps({'collection_count': report['collection_count'], 'elapsed_seconds': elapsed_seconds, 'stats': stats}, ensure_ascii=False, indent=2))
    return report


def open_collection(persist_dir: Path, collection_name: str):
    client = chromadb.PersistentClient(
        path=str(persist_dir),
        settings=Settings(anonymized_telemetry=False),
    )
    return client.get_collection(name=collection_name, embedding_function=None)


def query_chroma(question: str, model: SentenceTransformer, persist_dir: Path, collection_name: str, top_k: int = 10):
    collection = open_collection(persist_dir, collection_name)
    query_embedding = embed_texts(model, [f'{QUERY_PREFIX}{question}'], batch_size=1)[0]
    result = collection.query(
        query_embeddings=[query_embedding],
        n_results=top_k,
        include=['documents', 'metadatas', 'distances'],
    )
    ids = result.get('ids', [[]])[0]
    docs = result.get('documents', [[]])[0]
    metadatas = result.get('metadatas', [[]])[0]
    distances = result.get('distances', [[]])[0]
    rows = []
    for idx, chunk_id in enumerate(ids):
        metadata = metadatas[idx] or {}
        distance = float(distances[idx])
        row = {
            'rank': idx + 1,
            'chunk_id': chunk_id,
            'distance': distance,
            'score': 1.0 - distance,
            'title': metadata.get('title', ''),
            'document_number': metadata.get('document_number', ''),
            'issued_date': metadata.get('issued_date', ''),
            'status': metadata.get('status', ''),
            'retrieval_scope': metadata.get('retrieval_scope', ''),
            'topic_labels': metadata.get('topic_labels', ''),
            'article_number': metadata.get('article_number', ''),
            'clause_number': metadata.get('clause_number', ''),
            'point_key': metadata.get('point_key', ''),
            'source_url': metadata.get('source_url', ''),
            'text': docs[idx] or '',
        }
        rows.append(row)

    for row in rows:
        cite_parts = []
        if row['article_number']:
            cite_parts.append(f\"Điều {row['article_number']}\")
        if row['clause_number']:
            cite_parts.append(f\"Khoản {row['clause_number']}\")
        if row['point_key']:
            cite_parts.append(f\"Điểm {row['point_key']}\")
        cite = ', '.join(cite_parts) if cite_parts else 'Không rõ điều/khoản/điểm'
        preview = str(row['text']).replace('\\n', ' ')[:800]
        print(f\"\\n#{row['rank']} score={row['score']:.4f} distance={row['distance']:.4f}\")
        print(f\"Văn bản: {row['title']}\")
        print(f\"Số hiệu: {row['document_number']} | Ngày ban hành: {row['issued_date']}\")
        print(f\"Tình trạng: {row['status']} | Scope: {row['retrieval_scope']}\")
        print(f\"Topic: {row['topic_labels']}\")
        print(f\"Vị trí: {cite}\")
        print(f\"URL: {row['source_url']}\")
        print(f\"Chunk ID: {row['chunk_id']}\")
        print(f\"Nội dung: {preview}\")
    return rows
"""
        )
    )

    cells.append(
        _markdown(
            """
## Bước 6 - Load embedding model

Lần đầu chạy sẽ download model từ Hugging Face. Model này dùng prefix `passage:` cho văn bản và `query:` cho câu hỏi.
"""
        )
    )

    cells.append(
        _code(
            """
model = SentenceTransformer(MODEL_NAME, device=DEVICE)
print('Embedding dimension:', model.get_sentence_embedding_dimension())
print('Device:', DEVICE)
"""
        )
    )

    cells.append(
        _markdown(
            """
## Bước 7 - Pilot ingest 10,000 chunks

Chạy pilot trước để kiểm tra:
- model load được;
- Chroma ghi được;
- metadata citation không lỗi;
- query trả đúng chủ đề.

Cell này sẽ reset vector store local Colab trước khi ingest pilot.
"""
        )
    )

    cells.append(
        _code(
            """
pilot_report = ingest_chunks(
    source_file=LOCAL_SOURCE,
    persist_dir=LOCAL_PERSIST_DIR,
    collection_name=COLLECTION_NAME,
    model=model,
    limit=PILOT_LIMIT,
    batch_size=BATCH_SIZE,
    reset_store=True,
    report_path=REPORT_DIR / 'vector_ingestion_current_pilot_report.json',
)
"""
        )
    )

    cells.append(
        _markdown(
            """
## Bước 8 - Test retrieval sau pilot

Kết quả đạt yêu cầu khi top results đúng chủ đề, có `Tình trạng: Còn hiệu lực` hoặc `Hết hiệu lực một phần`, và `Scope: current`.
"""
        )
    )

    cells.append(
        _code(
            """
test_queries = [
    'chế độ kế toán doanh nghiệp siêu nhỏ',
    'công ty đại chúng công bố thông tin',
    'phát hành trái phiếu doanh nghiệp',
    'thuế thu nhập doanh nghiệp',
]

for q in test_queries:
    print('\\n' + '=' * 100)
    print('QUERY:', q)
    query_chroma(q, model=model, persist_dir=LOCAL_PERSIST_DIR, collection_name=COLLECTION_NAME, top_k=5)
"""
        )
    )

    cells.append(
        _markdown(
            """
## Bước 8.5 - Dọn DB pilot cũ trước full ingest

Chạy cell này sau khi restart runtime và sau khi đã load model, trước khi chạy Bước 9.

Mục tiêu:
- Không tái dùng vector DB pilot cũ ở `/content/chroma_e5_current`.
- Tạo persist dir mới hoàn toàn cho full ingest, tránh Chroma tái dùng SQLite connection cũ.
- Không xoá data nguồn trên Google Drive.
- Tránh lỗi SQLite `attempt to write a readonly database`.

Sau khi đã pilot ổn, không cần chạy lại Bước 7 và Bước 8 nữa.
"""
        )
    )

    cells.append(
        _code(
            """
import shutil
from datetime import datetime
from pathlib import Path

old_pilot_dir = Path('/content/chroma_e5_current')
if old_pilot_dir.exists():
    print('Remove old pilot dir:', old_pilot_dir)
    shutil.rmtree(old_pilot_dir, ignore_errors=True)

for p in Path('/content').glob('chroma_e5_current_backup_*'):
    print('Remove backup:', p)
    shutil.rmtree(p, ignore_errors=True)

run_id = datetime.now().strftime('%Y%m%d_%H%M%S')
LOCAL_PERSIST_DIR = Path(f'/content/chroma_e5_current_full_{run_id}')
LOCAL_PERSIST_DIR.mkdir(parents=True, exist_ok=False)

write_test = LOCAL_PERSIST_DIR / '.write_test'
write_test.write_text('ok', encoding='utf-8')
write_test.unlink()

print('Full ingest persist dir:', LOCAL_PERSIST_DIR)
print('Writable check: OK')
"""
        )
    )

    cells.append(
        _markdown(
            """
## Bước 9 - Full ingest toàn bộ corpus

Chỉ chạy cell này sau khi pilot retrieval ổn và đã chạy Bước 8.5.

Cách chạy:
1. Giữ `USE_DRIVE_PERSIST = False` ở cell cấu hình.
2. Không chạy lại Bước 7 và Bước 8 nếu pilot đã ổn.
3. Chạy Bước 8.5 để tạo persist dir mới hoàn toàn ở `/content`.
4. Chạy cell full ingest này.
5. Đợi đến khi `collection_count` xấp xỉ `607,679`.

Nếu cell lỗi nhưng runtime vẫn còn sống:
- Chạy lại cell này với `RESET_STORE_FOR_FULL = False` để resume/upsert tiếp.
- Vì id dùng `chunk_id`, upsert lại không tạo duplicate.

Nếu runtime bị ngắt hoàn toàn khi đang dùng `/content` và chưa chạy Bước 11, progress local có thể mất. Khi đó restart, chạy lại các cell đầu, chạy Bước 8.5 rồi chạy lại Bước 9.
"""
        )
    )

    cells.append(
        _code(
            """
RUN_FULL_INGEST = True
RESET_STORE_FOR_FULL = False

if RUN_FULL_INGEST:
    full_report = ingest_chunks(
        source_file=LOCAL_SOURCE,
        persist_dir=LOCAL_PERSIST_DIR,
        collection_name=COLLECTION_NAME,
        model=model,
        limit=0,
        batch_size=BATCH_SIZE,
        reset_store=RESET_STORE_FOR_FULL,
        report_path=REPORT_DIR / 'vector_ingestion_current_report.json',
    )
else:
    print('RUN_FULL_INGEST đang False. Đổi thành True nếu muốn chạy full ingest.')
"""
        )
    )

    cells.append(
        _markdown(
            """
## Bước 10 - Test retrieval sau full ingest

Sau full ingest, chạy lại các query quan trọng. Nếu top results sai chủ đề, cần xem lại corpus/filter/rerank trước khi làm chatbot.
"""
        )
    )

    cells.append(
        _code(
            """
for q in test_queries:
    print('\\n' + '=' * 100)
    print('QUERY:', q)
    query_chroma(q, model=model, persist_dir=LOCAL_PERSIST_DIR, collection_name=COLLECTION_NAME, top_k=10)
"""
        )
    )

    cells.append(
        _markdown(
            """
## Bước 10.5 - Xác nhận collection count

Cell này dùng để tránh nhầm pilot vector DB với full vector DB.

Kỳ vọng full hiện tại: khoảng `607,679` chunks.

Nếu count chỉ là `10,000`, bạn mới chạy pilot, chưa chạy full ingest.
"""
        )
    )

    cells.append(
        _code(
            """
EXPECTED_FULL_COUNT = 607_679
collection = open_collection(LOCAL_PERSIST_DIR, COLLECTION_NAME)
current_count = collection.count()
print('collection_count =', current_count)
if current_count < 100_000:
    print('CẢNH BÁO: đây gần như chắc chắn mới là pilot, chưa phải full vector DB.')
elif current_count < EXPECTED_FULL_COUNT * 0.95:
    print('CẢNH BÁO: count thấp hơn kỳ vọng full; kiểm tra full ingest có bị dừng giữa chừng không.')
else:
    print('OK: collection_count đạt mức full corpus hiện hành.')
"""
        )
    )

    cells.append(
        _markdown(
            """
## Bước 11 - Nén vector DB và lưu lại vào Google Drive

Nếu `USE_DRIVE_PERSIST = False`, vector DB đang nằm ở local Colab `/content/chroma_e5_current`. Bạn cần nén và copy về Drive để không mất khi runtime tắt.

Nếu bạn chạy full bằng Bước 8.5 mới, vector DB thực tế nằm trong thư mục timestamp như `/content/chroma_e5_current_full_...`; cell này vẫn zip đúng từ `LOCAL_PERSIST_DIR`.

Nếu `USE_DRIVE_PERSIST = True`, vector DB đã nằm trực tiếp trong Drive tại:

```text
MyDrive/vbpl_enterprise_colab/vector_db/chroma_e5_current_working
```

Vẫn có thể chạy cell này để tạo file zip dễ download.

Sau khi chạy cell này, file zip sẽ nằm ở:

```text
MyDrive/vbpl_enterprise_colab/vector_db/chroma_e5_current.zip
```
"""
        )
    )

    cells.append(
        _code(
            """
archive_base = Path('/content/chroma_e5_current')
zip_path = Path(str(archive_base) + '.zip')
if zip_path.exists():
    zip_path.unlink()

print('Đang nén vector DB từ:', LOCAL_PERSIST_DIR)
created_zip = shutil.make_archive(str(archive_base), 'zip', root_dir=str(LOCAL_PERSIST_DIR))
created_zip = Path(created_zip)
print('Created:', created_zip, 'size_gb=', round(created_zip.stat().st_size / (1024 ** 3), 3))

VECTOR_DIR.mkdir(parents=True, exist_ok=True)
drive_zip = VECTOR_DIR / 'chroma_e5_current.zip'
print('Đang copy zip về Drive...')
shutil.copy2(created_zip, drive_zip)
print('Saved to:', drive_zip, 'size_gb=', round(drive_zip.stat().st_size / (1024 ** 3), 3))
"""
        )
    )

    cells.append(
        _markdown(
            r"""
## Bước 12 - Dùng vector DB sau khi chạy xong

Nếu muốn query tiếp trên Colab trong cùng runtime, dùng luôn `LOCAL_PERSIST_DIR`.

Nếu muốn dùng vector DB trên máy Windows:

1. Download hoặc sync file này từ Google Drive:

```text
MyDrive/vbpl_enterprise_colab/vector_db/chroma_e5_current.zip
```

2. Đưa về máy Windows, ví dụ:

```text
D:\vbpl_data_enterprise\vector_db\chroma_e5_current.zip
```

3. Giải nén vào:

```text
D:\vbpl_data_enterprise\vector_db\chroma_e5_current
```

4. Test local bằng project hiện tại:

```powershell
.\.venv\Scripts\python.exe scripts\enterprise\query_chroma.py `
  --persist-dir D:\vbpl_data_enterprise\vector_db\chroma_e5_current `
  --collection vbpl_enterprise_current_e5_base `
  --query "chế độ kế toán doanh nghiệp siêu nhỏ" `
  --top-k 10
```

Sau khi query local ổn, bước tiếp theo là làm chatbot:
- lấy câu hỏi user;
- embed bằng `intfloat/multilingual-e5-base` với prefix `query:`;
- retrieve top chunks từ Chroma;
- đưa context vào `@cf/google/gemma-4-26b-a4b-it`;
- bắt model trả lời kèm citation theo `title`, `document_number`, `article_number`, `clause_number`, `point_key`, `source_url`.
"""
        )
    )

    cells.append(
        _markdown(
            r"""
## Ghi chú về OCR

OCR chưa được xử lý trong notebook này.

Hiện tại file issue ở local Windows là:

```text
D:\vbpl_data_enterprise\processed\rag_ingestion_issues.jsonl
```

Số liệu gần nhất:

```text
needs_ocr: 3,368
missing_text: 5
```

Không nên chặn embedding/vector DB vì OCR. Nên làm theo thứ tự:
1. Hoàn tất vector DB cho `rag_chunks_current.jsonl`.
2. Làm chatbot retrieval cơ bản.
3. Sau đó tạo pipeline OCR riêng cho `needs_ocr`.
4. OCR xong thì chunk thêm và upsert bổ sung vào cùng collection hoặc collection phụ.
"""
        )
    )

    return {
        "cells": cells,
        "metadata": {
            "colab": {
                "provenance": [],
                "gpuType": "T4",
            },
            "kernelspec": {
                "display_name": "Python 3",
                "name": "python3",
            },
            "language_info": {
                "name": "python",
            },
        },
        "nbformat": 4,
        "nbformat_minor": 5,
    }


def main() -> int:
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    notebook = build_notebook()
    OUTPUT.write_text(json.dumps(notebook, ensure_ascii=False, indent=2), encoding="utf-8")
    print(OUTPUT.resolve())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
