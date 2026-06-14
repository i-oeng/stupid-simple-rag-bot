import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

import document_processor as dp


def make_processor(tmp_path, monkeypatch):
    monkeypatch.setattr(dp, "chromadb", None)
    monkeypatch.setattr(dp, "TextEmbedding", None)
    return dp.LocalDocumentProcessor(tmp_path / "storage")


def test_chunk_text_preserves_lines_and_method_metadata(tmp_path, monkeypatch):
    processor = make_processor(tmp_path, monkeypatch)
    text = "Account Number\n7842-1193-005\nAmount Due\n$147.83"

    chunks = processor._chunk_text("doc-1", "bill.pdf", 1, text, extraction_method="ocr_fallback")

    assert chunks
    assert "Account Number\n7842-1193-005" in chunks[0]["text"]
    assert chunks[0]["extraction_method"] == "ocr_fallback"


def test_validation_reports_extraction_methods(tmp_path, monkeypatch):
    processor = make_processor(tmp_path, monkeypatch)
    chunks = [
        {"text": "Invoice Date 06/10/2026 Amount Due $147.83", "extraction_method": "native"},
        {"text": "OCR fallback text", "extraction_method": "ocr_fallback"},
    ]

    validation = processor.validate_payload(chunks, qr_codes=[], tables=[], visual_markers=[])

    assert validation["extraction_methods"] == {"native": 1, "ocr_fallback": 1}
    assert "ocr_available" in validation
    assert any(check["name"] == "ocr" for check in validation["checks"])


def test_ocr_fallback_is_used_when_native_text_is_weak(tmp_path, monkeypatch):
    processor = make_processor(tmp_path, monkeypatch)
    processor.tesseract_path = "tesseract"
    monkeypatch.setattr(dp, "pytesseract", object())
    monkeypatch.setattr(processor, "_ocr_page", lambda page: ("Account Number\n7842-1193-005", "mock_ocr"))

    class WeakPage:
        def get_text(self, mode):
            return ""

    text, method, note = processor._extract_page_text(WeakPage())

    assert text == "Account Number\n7842-1193-005"
    assert method == "ocr_fallback"
    assert "mock_ocr" in note
