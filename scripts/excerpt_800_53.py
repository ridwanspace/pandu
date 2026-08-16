"""Produce the demo excerpt of NIST SP 800-53r5 (see docs/corpus.md).

The full publication is 492 pages; parsing it with Docling's layout models
costs tens of CPU-minutes. This slices out the 56 pages the golden dataset
actually references — front matter, chapters 1-2, chapter-3 opening with
AC-1/AC-2, the AU family, and the IR family — using pypdfium2 (already
installed via the `parsing` extra).

Usage (from the repo root, after scripts/fetch_corpus.sh):

    uv run --project backend python scripts/excerpt_800_53.py
    # then upload backend/evals/corpus/nist-sp-800-53r5-excerpt.pdf under the
    # canonical name, e.g.:
    #   curl -H "X-API-Key: $KEY" \
    #     -F "file=@backend/evals/corpus/nist-sp-800-53r5-excerpt.pdf;filename=nist-sp-800-53r5.pdf;type=application/pdf" \
    #     http://localhost:8000/api/v1/documents
"""

from __future__ import annotations

from pathlib import Path

import pypdfium2 as pdfium

# 0-based page indices in the official rev. 5 PDF (2020-09, incl. updates).
PAGE_RANGES = (
    (0, 3),  # title, abstract
    (27, 49),  # chapters 1-2, chapter-3 opening, AC-1..AC-2
    (91, 109),  # 3.3 Audit and Accountability (AU-1..AU-16)
    (175, 188),  # 3.8 Incident Response
)


def main() -> None:
    corpus = Path(__file__).resolve().parents[1] / "backend" / "evals" / "corpus"
    source = corpus / "nist-sp-800-53r5.pdf"
    dest = corpus / "nist-sp-800-53r5-excerpt.pdf"

    src = pdfium.PdfDocument(source)
    pages = [i for start, stop in PAGE_RANGES for i in range(start, stop)]
    out = pdfium.PdfDocument.new()
    out.import_pages(src, pages)
    out.save(dest)
    print(f"{dest.name}: {len(pages)} pages, {dest.stat().st_size} bytes")


if __name__ == "__main__":
    main()
