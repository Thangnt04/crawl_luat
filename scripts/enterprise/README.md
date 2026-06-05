# Luồng crawl dữ liệu doanh nghiệp

Thư mục này chứa các script riêng cho corpus pháp luật liên quan tới doanh nghiệp. Luồng này tách biệt với luồng crawl toàn bộ để không làm lẫn dữ liệu.

## 1. Dữ liệu được lưu ở đâu?

Tất cả dữ liệu doanh nghiệp được ghi cố định vào:

```text
D:\vbpl_data_enterprise
```

Các thư mục sinh ra:

```text
D:\vbpl_data_enterprise\raw
D:\vbpl_data_enterprise\processed
D:\vbpl_data_enterprise\logs
```

Launcher `run_enterprise_crawl.py` tự set:

```text
VBPL_DATA_DIR=D:\vbpl_data_enterprise
```

Vì vậy không cần tự set `$env:VBPL_DATA_DIR` khi chạy luồng doanh nghiệp.

## 2. Luồng doanh nghiệp lấy dữ liệu như thế nào?

Lệnh chính:

```powershell
python scripts/enterprise/run_enterprise_crawl.py --max-docs 200000 --request-delay-seconds 0.2 --max-spurious-interrupts 3
```

Script này gọi lại pipeline crawl chính với `--focus enterprise`:

```powershell
python scripts/test_crawl_sample.py --focus enterprise ...
```

Cơ chế lọc hiện dùng taxonomy doanh nghiệp mở rộng trong `crawler/enterprise_taxonomy.py`. Taxonomy này gồm các nhóm: doanh nghiệp, đầu tư, thương mại, hợp đồng, lao động, thuế, hóa đơn, kế toán/kiểm toán, chứng khoán, ngân hàng/tài chính, cạnh tranh, phá sản, sở hữu trí tuệ, thương mại điện tử, xuất nhập khẩu, logistics, bảo hiểm, M&A, chuyển đổi số và đấu thầu.

### Lớp 1: lọc sớm trên metadata ở list API

Crawler gọi API list:

```text
POST https://vbpl-bientap-gateway.moj.gov.vn/api/qtdc/public/doc/all
```

Mỗi item list có `id`, `title`, `docNum`, `docType`, `agencyName`, `documentMajors` và một số metadata ngắn. Ở bước này crawler match keyword trên các metadata đó, không chỉ match `title`, để giảm bỏ sót các mảng như kế toán hoặc chứng khoán.

Text được normalize trước khi match: lowercase, bỏ dấu tiếng Việt, gom khoảng trắng. Vì vậy keyword có dấu và không dấu đều được hỗ trợ.

### Lớp 2: lọc lại và gắn topic sau khi parse detail

Với URL đã qua lớp 1, crawler gọi detail API:

```text
GET https://vbpl-bientap-gateway.moj.gov.vn/api/qtdc/public/doc/{id}
```

Sau khi parse xong, crawler kiểm tra lại trên blob:

```text
title + summary + field + document_type + document_number + issuing_agency
```

Nếu blob này không chứa keyword thuộc taxonomy doanh nghiệp, văn bản bị bỏ qua và log có dòng:

```text
Skip non-enterprise record: <url>
```

Nếu match, record được lưu thêm:

```text
topic_labels, topic_names, matched_keywords, matched_fields
```

Summary cuối run có dạng:

```text
Run summary: discovered=..., saved=..., duplicates=..., filtered_out=..., failed=...
```

## 3. Đây có phải bộ lọc chính xác tuyệt đối không?

Không. Đây là keyword/topic filter thực dụng, không phải classifier AI và không phải phân loại chính thức của VBPL.

Ưu điểm:

- Nhanh.
- Dễ hiểu, dễ debug bằng log.
- Giảm đáng kể số URL cần crawl detail.
- Có thể thêm keyword tùy ý bằng `--enterprise-keywords`.
- Có thể backfill theo từng topic bằng `--enterprise-topics`.

Hạn chế:

- Vẫn có thể bỏ sót nếu metadata list/detail không chứa keyword nhưng nội dung toàn văn có liên quan.
- Có thể lấy thừa do keyword rộng như `kinh doanh`, `bảo hiểm`, `vận tải`, `ngân hàng`.
- `topic_labels` giúp lọc/rerank ở bước retrieval, nhưng chưa thay thế được đánh giá pháp lý của con người.

## 4. Chạy crawl doanh nghiệp

Full crawl:

```powershell
python scripts/enterprise/run_enterprise_crawl.py --max-docs 200000 --request-delay-seconds 0.2 --max-spurious-interrupts 3
```

Backfill dữ liệu thiếu bằng taxonomy mở rộng:

```powershell
python scripts/enterprise/backfill_enterprise_topics.py --max-docs 200000 --request-delay-seconds 0.2 --max-spurious-interrupts 3
```

Backfill thử các topic đang thiếu nhiều:

```powershell
python scripts/enterprise/backfill_enterprise_topics.py --topics "ke_toan_kiem_toan,chung_khoan,thue" --max-docs 5000 --request-delay-seconds 0.2 --max-spurious-interrupts 3
```

Backfill không nên dùng `--incremental` nếu mục tiêu là tìm văn bản cũ bị bỏ sót. Script sẽ scan lại list API nhưng vẫn skip/dedupe các `canonical_doc_id` đã có trong `legal_documents_full.jsonl`.

Incremental crawl sau khi đã có dữ liệu nền:

```powershell
python scripts/enterprise/run_enterprise_crawl.py --incremental --max-docs 200000 --request-delay-seconds 0.2 --max-spurious-interrupts 3
```

Thêm keyword tùy chỉnh:

```powershell
python scripts/enterprise/run_enterprise_crawl.py --max-docs 5000 --enterprise-keywords "chứng khoán,bảo hiểm,thuế doanh nghiệp"
```

Lưu ý: keyword tùy chỉnh được cộng thêm vào keyword mặc định, không thay thế keyword mặc định.

Chọn topic trực tiếp trên launcher thường:

```powershell
python scripts/enterprise/run_enterprise_crawl.py --enterprise-topics "chung_khoan" --max-docs 5000 --request-delay-seconds 0.2
```

## 5. Output chính

Sau khi crawl, kiểm tra thư mục:

```text
D:\vbpl_data_enterprise\processed
```

Các file chính:

- `legal_documents_full.jsonl`: record đầy đủ, dùng làm backup/checkpoint/dedupe.
- `legal_documents_rag_ready.jsonl`: record gọn hơn cho RAG, có metadata, `content_clean`, file URLs, quality flags, `topic_labels`, `matched_keywords`.
- `legal_documents_chunks.jsonl`: chunk gốc do crawler tách từ nội dung văn bản, có metadata citation và topic nếu record mới có.

Log:

```text
D:\vbpl_data_enterprise\logs\crawler.log
```

Xem summary mới nhất:

```powershell
Get-Content D:\vbpl_data_enterprise\logs\crawler.log | Select-String "Run summary" | Select-Object -Last 1
```

## 6. Repair lỗi ghi file doanh nghiệp

Nếu log có lỗi `Permission denied` hoặc văn bản bị fail trong lúc ghi JSONL, dùng:

```powershell
python scripts/enterprise/repair_failed_enterprise.py
```

Hoặc repair một URL cụ thể:

```powershell
python scripts/enterprise/repair_failed_enterprise.py --url "https://vbpl.vn/van-ban/chi-tiet/128613"
```

Script này chỉ bổ sung output còn thiếu cho URL lỗi, không crawl lại toàn bộ.

## 7. Chuẩn bị corpus sạch cho RAG

Smoke test:

```powershell
python scripts/enterprise/prepare_rag_ingestion.py --max-docs 200 --max-pdf-docs 5
```

Full run:

```powershell
python scripts/enterprise/prepare_rag_ingestion.py
```

Sau mỗi đợt backfill, chạy lại lệnh này để tái tạo `rag_chunks_clean.jsonl`. Script sẽ tự suy luận `topic_labels` cho cả record cũ chưa có nhãn topic.

Nếu muốn giới hạn xử lý PDF để tránh chạy quá lâu:

```powershell
python scripts/enterprise/prepare_rag_ingestion.py --max-pdf-docs 100 --pdf-timeout-seconds 5 --max-pdf-bytes 20000000 --max-pdf-pages 80 --pdf-url-limit 1
```

Output RAG ingestion:

- `D:\vbpl_data_enterprise\processed\rag_chunks_clean.jsonl`: nguồn chính để embedding.
- `D:\vbpl_data_enterprise\processed\rag_ingestion_report.json`: thống kê chất lượng corpus.
- `D:\vbpl_data_enterprise\processed\rag_ingestion_issues.jsonl`: các văn bản thiếu text hoặc cần OCR.

## 8. Nên dùng file nào cho chatbot?

Nên dùng:

```text
D:\vbpl_data_enterprise\processed\rag_chunks_clean.jsonl
```

Không nên embedding trực tiếp từ `legal_documents_full.jsonl` vì file này quá lớn và chứa nhiều trường chỉ phục vụ backup/debug.

Không nên embedding trực tiếp từ `legal_documents_chunks.jsonl` nếu chưa qua `prepare_rag_ingestion.py`, vì có thể còn chunk quá dài/quá ngắn hoặc PDF-only chưa được đánh dấu rõ.

## 9. Bước tiếp theo

Sau khi có `rag_chunks_clean.jsonl`:

1. Tạo embedding cho từng dòng/chunk.
2. Ghi vào vector DB.
3. Lưu metadata citation: `canonical_doc_id`, `title`, `document_number`, `issued_date`, `article_number`, `clause_number`, `point_key`, `source_url`.
4. Test retrieval bằng câu hỏi mẫu.
5. Xử lý dần nhóm `needs_ocr` trong `rag_ingestion_issues.jsonl`.

Không cần train LLM trên Google Colab cho bước RAG cơ bản. Việc cần làm trước là crawl đủ dữ liệu, tạo clean chunks, embedding và kiểm tra retrieval. Colab chỉ hữu ích nếu máy local quá chậm khi tính embedding hoặc OCR PDF scan; đó là tính toán batch, không phải train model.

## 10. Ingest vào Chroma vector DB

Vector DB local được lưu tại:

```text
D:\vbpl_data_enterprise\vector_db\chroma_e5_base
```

Model embedding mặc định:

```text
intfloat/multilingual-e5-base
```

Môi trường này dùng CPU, không dùng GPU.

### 10.1. Cài dependency

```powershell
pip install -r requirements.txt
```

Các version đã được pin để tránh lỗi native DLL trên Windows:

- `chromadb==0.4.24`
- `onnxruntime==1.16.3`
- `numpy==1.26.4`
- `sentence-transformers==3.0.1`
- `transformers==4.44.2`
- `torch==2.3.1`

### 10.2. Pilot ingest 10,000 chunks

Chạy pilot trước để kiểm tra model, Chroma và retrieval:

```powershell
python scripts/enterprise/ingest_chroma.py --limit 10000 --batch-size 64 --reset --reset-store
```

Kỳ vọng:

```text
collection_count=10000
```

Report được ghi tại:

```text
D:\vbpl_data_enterprise\processed\vector_ingestion_report.json
```

### 10.3. Test retrieval

```powershell
python scripts/enterprise/query_chroma.py --query "doanh nghiệp siêu nhỏ chế độ kế toán" --top-k 10
```

Các query nên test:

```text
doanh nghiệp siêu nhỏ chế độ kế toán
đăng ký kinh doanh ngành nghề
doanh nghiệp bán hàng đa cấp
hộ kinh doanh sau đăng ký thành lập
```

Kết quả tốt cần có:

- `title`
- `document_number`
- `source_url`
- vị trí điều/khoản/điểm nếu metadata có sẵn
- đoạn nội dung liên quan trực tiếp tới câu hỏi

### 10.4. Full ingest

Khi pilot ổn, chạy toàn bộ corpus:

```powershell
python scripts/enterprise/ingest_chroma.py --batch-size 64
```

Script dùng `upsert` theo `chunk_id`, nên nếu đang có 10,000 chunks từ pilot thì full ingest sẽ cập nhật/ghi tiếp phần còn lại. Không cần xóa pilot trước khi chạy full, trừ khi muốn làm lại từ đầu với `--reset`.

Nếu từng tạo Chroma bằng version khác và gặp lỗi schema SQLite, dùng thêm `--reset-store`. Tùy chọn này không xóa thẳng thư mục cũ mà đổi tên sang backup timestamp.
