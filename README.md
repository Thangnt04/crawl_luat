# VBPL Crawler phục vụ RAG pháp luật

Project này dùng để crawl văn bản pháp luật từ `vbpl.vn`, làm sạch dữ liệu và xuất ra các file JSONL có thể dùng cho pipeline RAG.

Project hiện có 2 luồng chính:

- Luồng crawl toàn bộ: lấy văn bản pháp luật nói chung, ghi vào `data/` hoặc thư mục do `VBPL_DATA_DIR` chỉ định.
- Luồng crawl doanh nghiệp: giữ các văn bản liên quan tới doanh nghiệp và các mảng pháp lý doanh nghiệp mở rộng như thuế, kế toán, chứng khoán, lao động, hợp đồng, đầu tư; ghi riêng vào `D:\vbpl_data_enterprise`.

Project chưa bao gồm chatbot hoàn chỉnh hoặc OCR đầy đủ. Phần hiện tại có crawler, chuẩn bị corpus sạch cho RAG và script ingest/query Chroma local.

## 1. Cài đặt

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

Nếu PowerShell không cho activate virtualenv, chạy:

```powershell
Set-ExecutionPolicy -Scope CurrentUser RemoteSigned
```

## 2. Cấu hình thư mục dữ liệu

Mặc định crawler thường ghi vào:

```text
C:\Users\thangnt00\Desktop\crawl_luat\data
```

Có thể đổi bằng biến môi trường `VBPL_DATA_DIR`:

```powershell
$env:VBPL_DATA_DIR = "D:\vbpl_data"
python scripts/test_crawl_sample.py --max-docs 200000 --request-delay-seconds 0.2
```

Luồng doanh nghiệp không cần tự set biến này vì launcher đã ép dữ liệu vào:

```text
D:\vbpl_data_enterprise
```

## 3. Cách crawler lấy dữ liệu từ VBPL

Crawler ưu tiên API công khai của frontend VBPL:

- List API: `POST https://vbpl-bientap-gateway.moj.gov.vn/api/qtdc/public/doc/all`
- Detail API: `GET https://vbpl-bientap-gateway.moj.gov.vn/api/qtdc/public/doc/{id}`
- File API: endpoint MinIO presigned URL cho file đính kèm PDF/DOC/DOCX.

Luồng tổng quát:

1. Gọi list API theo từng trang, sort theo `issueDate desc`.
2. Lưu raw list page vào `raw/list_pages/` để debug.
3. Từ mỗi item list, lấy `id` và tạo URL dạng `https://vbpl.vn/van-ban/chi-tiet/{id}`.
4. Với từng URL, gọi detail API để lấy metadata, nội dung HTML/text và danh sách file đính kèm.
5. Nếu API detail lỗi hoặc thiếu dữ liệu, fallback sang HTML bằng `requests + BeautifulSoup`.
6. Parse metadata: số hiệu, loại văn bản, ngày ban hành, ngày hiệu lực, tình trạng, lĩnh vực, cơ quan ban hành, người ký, file đính kèm.
7. Làm sạch nội dung và tách chunk theo điều/khoản/điểm nếu có thể.
8. Ghi 3 file JSONL: `full`, `rag_ready`, `chunks`.

## 4. Luồng crawl thường

Smoke test 1 văn bản:

```powershell
python scripts/test_crawl_one.py --url "https://vbpl.vn/van-ban/chi-tiet/13011"
```

Crawl mẫu 20 văn bản:

```powershell
python scripts/test_crawl_sample.py --max-docs 20 --request-delay-seconds 0.5
```

Crawl toàn bộ theo khả năng API trả về:

```powershell
python scripts/test_crawl_sample.py --max-docs 200000 --request-delay-seconds 0.2 --max-spurious-interrupts 3
```

Crawl incremental sau khi đã có dữ liệu nền:

```powershell
python scripts/test_crawl_sample.py --incremental --max-docs 200000 --request-delay-seconds 0.2 --max-spurious-interrupts 3
```

## 5. Luồng crawl doanh nghiệp lấy dữ liệu như thế nào?

Luồng doanh nghiệp chạy qua launcher:

```powershell
python scripts/enterprise/run_enterprise_crawl.py --max-docs 200000 --request-delay-seconds 0.2 --max-spurious-interrupts 3
```

Launcher này làm 2 việc:

1. Set `VBPL_DATA_DIR=D:\vbpl_data_enterprise` để dữ liệu doanh nghiệp tách khỏi luồng crawl thường.
2. Gọi lại pipeline chính với `--focus enterprise`.

Tức là lệnh trên tương đương logic:

```powershell
$env:VBPL_DATA_DIR = "D:\vbpl_data_enterprise"
python scripts/test_crawl_sample.py --focus enterprise --max-docs 200000 --request-delay-seconds 0.2 --max-spurious-interrupts 3
```

Backfill dữ liệu doanh nghiệp còn thiếu bằng taxonomy mở rộng:

```powershell
python scripts/enterprise/backfill_enterprise_topics.py --max-docs 200000 --request-delay-seconds 0.2 --max-spurious-interrupts 3
```

Backfill thử các mảng đang thiếu nhiều:

```powershell
python scripts/enterprise/backfill_enterprise_topics.py --topics "ke_toan_kiem_toan,chung_khoan,thue" --max-docs 5000 --request-delay-seconds 0.2 --max-spurious-interrupts 3
```

Không dùng `--incremental` khi mục tiêu là tìm văn bản cũ bị bỏ sót. Backfill sẽ scan lại list API nhưng vẫn dedupe theo `legal_documents_full.jsonl`.

### 5.1. Lớp lọc 1: lọc sớm trên metadata ở list API

Khi `--focus enterprise`, crawler dùng taxonomy trong `crawler/enterprise_taxonomy.py`. Taxonomy này gồm các nhóm: doanh nghiệp, đầu tư, thương mại, hợp đồng, lao động, thuế, hóa đơn, kế toán/kiểm toán, chứng khoán, ngân hàng/tài chính, cạnh tranh, phá sản, sở hữu trí tuệ, thương mại điện tử, xuất nhập khẩu, logistics, bảo hiểm, M&A, chuyển đổi số và đấu thầu.

Ở list API, crawler match keyword trên metadata ngắn như `title`, `docNum`, `docType`, `agencyName`, `documentMajors`, không chỉ match `title`. Text được normalize trước khi so khớp: lowercase, bỏ dấu tiếng Việt, gom whitespace.

Điểm quan trọng: lớp lọc này là keyword/topic filter, không phải classifier AI và không phải taxonomy chính thức của VBPL.

### 5.2. Lớp lọc 2: kiểm tra lại sau khi parse chi tiết

Sau khi URL vượt qua lớp 1, crawler gọi detail API rồi parse đầy đủ hơn. Trước khi lưu, crawler kiểm tra lại bằng blob gồm:

```text
title + summary + field + document_type + document_number + issuing_agency
```

Nếu blob này không chứa keyword doanh nghiệp, record bị bỏ qua và log là:

```text
Skip non-enterprise record: <url>
```

Trong summary cuối run sẽ có:

```text
Run summary: discovered=..., saved=..., duplicates=..., filtered_out=..., failed=...
```

Nếu match, record được lưu thêm `topic_labels`, `topic_names`, `matched_keywords`, `matched_fields` để phục vụ lọc/rerank khi retrieval.

### 5.3. Hạn chế của cách lọc doanh nghiệp

Cách này thực dụng và chạy nhanh, nhưng có các tradeoff:

- Có thể bỏ sót nếu metadata list/detail không có keyword dù nội dung toàn văn có liên quan.
- Có thể lấy thừa vì keyword rộng như `kinh doanh`, `bảo hiểm`, `vận tải`, `ngân hàng`.
- `topic_labels` giúp lọc/rerank ở bước retrieval, nhưng chưa thay thế được đánh giá pháp lý của con người.
- Chưa dùng embedding/classifier để xác định semantic relevance ở bước crawl.

Nếu muốn corpus doanh nghiệp chính xác hơn, bước cải thiện nên là:

1. Giữ keyword filter để giảm tải list stage.
2. Sau khi parse detail, dùng topic labels và matched keywords để đánh giá nhiễu.
3. Re-run `prepare_rag_ingestion.py` để tạo clean chunks có topic metadata.
4. Dùng embedding/rerank ở tầng retrieval để giảm nhiễu trước khi chatbot trả lời.

## 6. Output dữ liệu

Với luồng thường, output nằm ở `data/processed/` hoặc thư mục `VBPL_DATA_DIR` bạn tự set.

Với luồng doanh nghiệp, output nằm ở:

```text
D:\vbpl_data_enterprise\processed
```

Các file chính:

- `legal_documents_full.jsonl`: bản đầy đủ nhất, dùng làm backup/checkpoint/dedupe.
- `legal_documents_rag_ready.jsonl`: bản gọn hơn cho RAG, gồm metadata, `content_clean`, file URLs, quality flags.
- `legal_documents_chunks.jsonl`: chunk ban đầu được tách từ crawler, có metadata điều/khoản/điểm nếu parse được.
- `rag_chunks_clean.jsonl`: corpus sạch sau bước chuẩn hóa RAG ingestion, nên dùng làm input embedding chính.
- `rag_ingestion_report.json`: báo cáo thống kê sau khi tạo `rag_chunks_clean`.
- `rag_ingestion_issues.jsonl`: danh sách văn bản thiếu text hoặc cần OCR, nhất là nhóm PDF-only.

## 7. Chuẩn bị dữ liệu cho RAG

Sau khi crawl doanh nghiệp xong, chạy:

```powershell
python scripts/enterprise/prepare_rag_ingestion.py
```

Script này đọc dữ liệu ở `D:\vbpl_data_enterprise\processed`, rồi tạo:

```text
D:\vbpl_data_enterprise\processed\rag_chunks_clean.jsonl
D:\vbpl_data_enterprise\processed\rag_ingestion_report.json
D:\vbpl_data_enterprise\processed\rag_ingestion_issues.jsonl
```

Tác dụng:

- Rechunk các chunk quá dài.
- Loại chunk rỗng/quá ngắn.
- Giữ metadata citation: văn bản, số hiệu, ngày, điều/khoản/điểm, URL nguồn.
- Thử extract text từ một phần PDF-only bằng `pypdf`.
- Đánh dấu tài liệu vẫn cần OCR vào `rag_ingestion_issues.jsonl`.

## 8. Kiểm tra chất lượng

Kiểm tra file RAG-ready gốc:

```powershell
python scripts/check_rag_ready.py
```

Kiểm tra nhanh report RAG ingestion:

```powershell
Get-Content D:\vbpl_data_enterprise\processed\rag_ingestion_report.json -Raw
```

Xem số dòng clean chunks:

```powershell
(Get-Content D:\vbpl_data_enterprise\processed\rag_chunks_clean.jsonl).Count
```

Với file lớn, không nên mở bằng VS Code. Nên dùng PowerShell/Python để đọc mẫu hoặc đếm dòng.

## 9. Vai trò từng file và thư mục chính

### File gốc project

- `.gitignore`: bỏ qua `.venv/`, `data/`, cache Python và file sinh ra lớn.
- `requirements.txt`: danh sách thư viện Python cần cài, gồm crawler, PDF extraction, embedding và Chroma vector DB.
- `config.py`: cấu hình chung, path dữ liệu, path output, logging, API base URL, timeout/retry mặc định.
- `README.md`: tài liệu tổng quan project.

### Package `crawler/`

- `crawler/__init__.py`: export các hàm/class chính của package crawler.
- `crawler/http_client.py`: HTTP client có retry, timeout, delay, robots check và helper GET/POST JSON.
- `crawler/discover_urls.py`: lấy danh sách văn bản từ HTML list hoặc API list; hỗ trợ incremental, skip existing IDs, keyword/topic metadata filter.
- `crawler/enterprise_taxonomy.py`: taxonomy doanh nghiệp mở rộng, normalize tiếng Việt, match keyword và gắn `topic_labels`.
- `crawler/parse_detail.py`: parse detail API/HTML thành metadata và nội dung có cấu trúc.
- `crawler/clean_text.py`: làm sạch text pháp luật, chuẩn hóa whitespace/header/footer cơ bản.
- `crawler/download_files.py`: tải file đính kèm nếu bật `--download-files`.
- `crawler/save_jsonl.py`: build record `full`, `rag_ready`, `chunks`; ghi JSONL; dedupe; retry khi Windows lock file.

### Thư mục `scripts/`

- `scripts/test_crawl_one.py`: crawl thử một văn bản cụ thể để debug parser/detail API.
- `scripts/test_crawl_sample.py`: script crawl chính cho cả full crawl, incremental crawl và enterprise focus.
- `scripts/check_rag_ready.py`: kiểm tra chất lượng file `legal_documents_rag_ready.jsonl`.
- `scripts/test_crawl_enterprise.py`: wrapper ngắn gọi launcher doanh nghiệp.

### Thư mục `scripts/enterprise/`

- `scripts/enterprise/run_enterprise_crawl.py`: launcher doanh nghiệp; ép `VBPL_DATA_DIR=D:\vbpl_data_enterprise`; gọi `test_crawl_sample.py --focus enterprise`.
- `scripts/enterprise/backfill_enterprise_topics.py`: launcher backfill theo taxonomy/topic mở rộng; dùng để bổ sung dữ liệu thiếu mà không xóa corpus cũ.
- `scripts/enterprise/repair_failed_enterprise.py`: repair các URL doanh nghiệp từng fail do lỗi ghi file/permission hoặc thiếu output.
- `scripts/enterprise/prepare_rag_ingestion.py`: tạo corpus sạch `rag_chunks_clean.jsonl` cho embedding/vector DB.
- `scripts/enterprise/ingest_chroma.py`: tạo embedding local bằng `intfloat/multilingual-e5-base` và upsert vào Chroma.
- `scripts/enterprise/query_chroma.py`: query thử Chroma, in kết quả kèm citation.
- `scripts/enterprise/README.md`: hướng dẫn riêng cho luồng doanh nghiệp.

### Thư mục dữ liệu

- `data/`: dữ liệu của luồng crawl thường trong project. Thường rất lớn, không nên commit.
- `data_enterprise/`: dữ liệu doanh nghiệp cũ từng tạo trong project. Luồng mới đang dùng ổ D, không nên dùng folder này làm nguồn chính nữa.
- `D:\vbpl_data_enterprise\raw`: raw list pages, raw detail API/HTML, file đính kèm nếu tải.
- `D:\vbpl_data_enterprise\processed`: JSONL đã xử lý, gồm full/rag/chunks/clean corpus.
- `D:\vbpl_data_enterprise\logs`: log riêng của luồng doanh nghiệp.

### Virtualenv/cache

- `.venv/`: virtual environment đang dùng hiện tại.
- `venv/`: virtual environment cũ/khác nếu có; nên tránh dùng lẫn với `.venv/`.
- `__pycache__/`: cache Python, có thể xóa khi cần, không ảnh hưởng logic.

## 10. Bước tiếp theo sau khi đã có `rag_chunks_clean.jsonl`

Bước tiếp theo là xây pipeline embedding/vector DB:

1. Đọc từng dòng `rag_chunks_clean.jsonl`.
2. Tạo embedding cho field `text`.
3. Lưu vector kèm metadata citation.
4. Test retrieval bằng các câu hỏi doanh nghiệp mẫu.
5. Sau đó mới gắn LLM để tạo chatbot hỏi đáp luật có trích dẫn nguồn.

Không cần train LLM trên Google Colab cho RAG cơ bản. Nếu máy local chậm, Colab có thể dùng để tính embedding hoặc OCR PDF scan nhanh hơn; đó là xử lý batch dữ liệu, không phải train model.

Lệnh pilot Chroma:

```powershell
python scripts/enterprise/ingest_chroma.py --limit 10000 --batch-size 64 --reset --reset-store
python scripts/enterprise/query_chroma.py --query "doanh nghiệp siêu nhỏ chế độ kế toán" --top-k 10
```
