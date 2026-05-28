from __future__ import annotations

import json
from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from config import RAG_READY_JSONL_OUTPUT


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    path = RAG_READY_JSONL_OUTPUT
    if not path.exists():
        print(f"[ERROR] File not found: {path}")
        return

    total = 0
    has_content_clean = 0
    has_pdf = 0
    has_doc = 0
    has_docx = 0
    preview_printed = False

    with path.open("r", encoding="utf-8") as f:
        for idx, line in enumerate(f, start=1):
            line = line.strip()
            if not line:
                continue
            total += 1
            doc = json.loads(line)
            content_clean = str(doc.get("content_clean") or "").strip()
            if content_clean:
                has_content_clean += 1
            if doc.get("pdf_urls"):
                has_pdf += 1
            if doc.get("doc_urls"):
                has_doc += 1
            if doc.get("docx_urls"):
                has_docx += 1

            if not preview_printed and content_clean:
                print("\n=== Preview content_clean (500 chars) ===")
                print(content_clean[:500])
                preview_printed = True

            if len(content_clean) == 0:
                print(f"[WARN] Empty content_clean at line {idx}, id={doc.get('id', '')}")
            elif len(content_clean) < 200:
                print(
                    f"[WARN] content_clean too short ({len(content_clean)} chars) "
                    f"at line {idx}, id={doc.get('id', '')}"
                )

    print("\n=== RAG Ready Stats ===")
    print(f"total_documents: {total}")
    print(f"documents_with_content_clean: {has_content_clean}")
    print(f"documents_with_pdf_urls: {has_pdf}")
    print(f"documents_with_doc_urls: {has_doc}")
    print(f"documents_with_docx_urls: {has_docx}")


if __name__ == "__main__":
    main()
