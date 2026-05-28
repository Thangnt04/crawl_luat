# VBPL Crawler (an toàn, phục vụ RAG)

Module này dùng để crawl dữ liệu văn bản pháp luật từ [vbpl.vn](https://vbpl.vn), tập trung vào:
- Khám phá URL văn bản
- Crawl chi tiết từng văn bản
- Parse metadata + nội dung
- Làm sạch text tiếng Việt
- Lưu 2 dạng JSONL: full backup và RAG-ready

Không bao gồm chatbot, embedding, vector DB, OCR.

## 1) Khảo sát website trước khi crawl lớn

Đã khảo sát ở quy mô nhỏ:
- Frontend `vbpl.vn` dùng Next.js, nhiều thành phần render động.
- API công khai frontend đang gọi:
  - `POST https://vbpl-bientap-gateway.moj.gov.vn/api/qtdc/public/doc/all`
  - `GET  https://vbpl-bientap-gateway.moj.gov.vn/api/qtdc/public/doc/{id}`
- Luồng hiện tại ưu tiên API (ổn định hơn), có fallback parse HTML bằng `requests + BeautifulSoup`.

Nếu một nhóm URL không lấy đủ dữ liệu bằng requests:
- TODO: bổ sung Playwright cho nhóm URL đó.

## 2) Cấu trúc thư mục dữ liệu

```text
data/
├── raw/
│   ├── html/
│   ├── files/
│   └── list_pages/
├── processed/
│   ├── legal_documents_full.jsonl
│   └── legal_documents_rag_ready.jsonl
└── logs/
    └── crawler.log
```

## 3) Cài đặt

```bash
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
```

## 3.1) Chuyển dữ liệu sang ổ D (khuyến nghị khi ổ C sắp đầy)

Crawler hỗ trợ biến môi trường `VBPL_DATA_DIR` để đổi vị trí lưu dữ liệu (`raw/processed/logs`).

Thiết lập cho phiên PowerShell hiện tại:

```powershell
$env:VBPL_DATA_DIR = "D:\vbpl_data"
```

Thiết lập vĩnh viễn cho user hiện tại:

```powershell
[Environment]::SetEnvironmentVariable("VBPL_DATA_DIR", "D:\vbpl_data", "User")
```

Nếu đã có dữ liệu ở ổ C và muốn chuyển sang D:

```powershell
New-Item -ItemType Directory -Force -Path "D:\vbpl_data" | Out-Null
Copy-Item -Path ".\data\*" -Destination "D:\vbpl_data" -Recurse -Force
```

Sau khi chuyển xong, chạy lại terminal mới rồi chạy crawler như bình thường.

## 4) Chạy thử 1 văn bản

```bash
python scripts/test_crawl_one.py --url "https://vbpl.vn/van-ban/chi-tiet/615816e0-5417-11f1-ad3f-2d02fabbb459"
```

Kèm tải file đính kèm:

```bash
python scripts/test_crawl_one.py --url "https://vbpl.vn/van-ban/chi-tiet/615816e0-5417-11f1-ad3f-2d02fabbb459" --download-files
```

## 5) Chạy mẫu 5–10 văn bản

Mặc định 5 văn bản:

```bash
python scripts/test_crawl_sample.py --max-docs 5
```

10 văn bản:

```bash
python scripts/test_crawl_sample.py --max-docs 10
```

Fallback theo HTML list page:

```bash
python scripts/test_crawl_sample.py --max-docs 8 --use-html-list
```

## 6) Chạy cào diện rộng (để “cào hết”)

Lưu ý: script hiện chạy tuần tự, có dedupe theo `id/source_url`, có retry/timeout/robots check.

### 6.1 Lần đầu (full)

Chạy số lượng lớn (ví dụ 200000) để đi hết dữ liệu khả dụng từ API:

```bash
python scripts/test_crawl_sample.py --max-docs 200000 --request-delay-seconds 1.0
```

### 6.2 Cập nhật tăng dần (khuyến nghị cho chạy hằng ngày)

Tự động lấy mốc ngày mới nhất từ `legal_documents_full.jsonl`:

```bash
python scripts/test_crawl_sample.py --incremental --max-docs 50000 --request-delay-seconds 1.0
```

Hoặc chỉ định mốc ngày cụ thể:

```bash
python scripts/test_crawl_sample.py --incremental --since-date 2026-05-01 --max-docs 50000 --request-delay-seconds 1.0
```

## 7) Tham số quan trọng

- `--max-docs`: số văn bản tối đa cần crawl trong lần chạy.
- `--incremental`: chỉ crawl văn bản mới hơn mốc ngày.
- `--since-date YYYY-MM-DD`: mốc ngày cho incremental.
- `--request-delay-seconds`: delay giữa request (mặc định hiện tại: `1.0` giây).
- `--download-files`: tải file đính kèm (pdf/doc/docx).

## 8) Dữ liệu đầu ra

- Danh sách trang/API raw: `data/raw/list_pages/*`
- Chi tiết raw: `data/raw/html/*`
  - API mode: `*_api.json`
  - HTML fallback: `*.html`
- File tải về: `data/raw/files/<doc_id>/*`
- Full backup: `data/processed/legal_documents_full.jsonl`
- RAG-ready: `data/processed/legal_documents_rag_ready.jsonl`
- Log: `data/logs/crawler.log`

## 9) Kiểm tra chất lượng file RAG-ready

```bash
python scripts/check_rag_ready.py
```

Script sẽ:
- Đếm số văn bản có `content_clean`
- Đếm số văn bản có `pdf/doc/docx`
- In 500 ký tự đầu của `content_clean`
- Cảnh báo nếu `content_clean` rỗng hoặc quá ngắn

## 10) Lỗi thường gặp

- Lỗi mạng/timeout: đã có retry + delay, nhưng vẫn cần mạng ổn định.
- Bị robots chặn URL: crawler bỏ qua URL đó và ghi log cảnh báo.
- Layout/API thay đổi: kiểm tra `candidate_fields` trong log và raw files để cập nhật parser.
- PDF scan không trích text được: để TODO OCR ở phase sau.
