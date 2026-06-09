import hashlib
import json
import re
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional

import fitz
import numpy as np
import zxingcpp

try:
    import chromadb
    from fastembed import TextEmbedding
except Exception:
    chromadb = None
    TextEmbedding = None

try:
    import pdfplumber
except Exception:
    pdfplumber = None


DATE_RE = re.compile(r"\b(?:\d{1,2}[./-]\d{1,2}[./-]\d{2,4}|\d{4}[./-]\d{1,2}[./-]\d{1,2})\b")
AMOUNT_RE = re.compile(r"(?i)(?:\$|usd|eur|kzt|₸)?\s?\d{1,3}(?:[ ,.]\d{3})*(?:[.,]\d{2})?\s?(?:\$|usd|eur|kzt|₸)?")
UTILITY_TERMS = {"utility", "electric", "water", "gas", "meter", "account", "billing", "invoice", "amount due", "tariff"}
CONTRACT_TERMS = {"contract", "agreement", "party", "parties", "signature", "terms", "effective date", "obligation"}


@dataclass
class ProcessedDocument:
    document_id: str
    filename: str
    file_hash: str
    pages: int
    chunks: List[Dict[str, Any]]
    qr_codes: List[Dict[str, Any]]
    tables: List[Dict[str, Any]]
    report_path: Path
    reused_existing: bool = False

    def to_dict(self) -> Dict[str, Any]:
        return {
            "document_id": self.document_id,
            "filename": self.filename,
            "file_hash": self.file_hash,
            "pages": self.pages,
            "chunks": self.chunks,
            "qr_codes": self.qr_codes,
            "tables": self.tables,
            "report_path": str(self.report_path),
            "reused_existing": self.reused_existing,
            "summary": {
                "chunk_count": len(self.chunks),
                "qr_count": len(self.qr_codes),
                "table_count": len(self.tables),
                "has_text": any(chunk["text"].strip() for chunk in self.chunks),
            },
        }


class LocalDocumentProcessor:
    def __init__(self, storage_dir: Path):
        self.storage_dir = storage_dir
        self.report_dir = storage_dir / "reports"
        self.vector_dir = storage_dir / "vector"
        self.metadata_path = storage_dir / "documents.json"
        self.report_dir.mkdir(parents=True, exist_ok=True)
        self.vector_dir.mkdir(parents=True, exist_ok=True)

        self.embedding_model = None
        self.collection = None
        if chromadb is not None and TextEmbedding is not None:
            self.embedding_model = TextEmbedding(model_name="BAAI/bge-small-en-v1.5")
            client = chromadb.PersistentClient(path=str(self.vector_dir))
            self.collection = client.get_or_create_collection("documents")

    @property
    def embeddings_enabled(self) -> bool:
        return self.embedding_model is not None and self.collection is not None

    @property
    def tables_enabled(self) -> bool:
        return pdfplumber is not None

    def process_pdf(self, pdf_path: Path) -> ProcessedDocument:
        file_hash = self._hash_file(pdf_path)
        existing = self._find_by_hash(file_hash)
        if existing:
            existing["reused_existing"] = True
            return self._document_from_record(existing)

        document_id = uuid.uuid4().hex
        doc = fitz.open(str(pdf_path))
        chunks: List[Dict[str, Any]] = []
        qr_codes: List[Dict[str, Any]] = []
        page_count = 0

        try:
            page_count = len(doc)
            for page_index, page in enumerate(doc):
                page_number = page_index + 1
                text = page.get_text("text").strip()
                if text:
                    chunks.extend(self._chunk_text(document_id, pdf_path.name, page_number, text))
                qr_codes.extend(self._detect_qr_codes(page, page_number))
        finally:
            doc.close()

        tables = self._extract_tables(pdf_path, document_id)

        if self.embeddings_enabled and chunks:
            self._index_chunks(chunks)

        validation = self.validate_payload(chunks, qr_codes, tables)
        report_path = self._write_report(document_id, pdf_path.name, file_hash, page_count, chunks, qr_codes, tables, validation)
        record = ProcessedDocument(
            document_id=document_id,
            filename=pdf_path.name,
            file_hash=file_hash,
            pages=page_count,
            chunks=chunks,
            qr_codes=qr_codes,
            tables=tables,
            report_path=report_path,
        ).to_dict()
        record["validation"] = validation
        self._save_record(record)
        return self._document_from_record(record)

    def get_document(self, document_id: str) -> Optional[Dict[str, Any]]:
        return self._load_records().get(document_id)

    def list_documents(self) -> List[Dict[str, Any]]:
        return list(self._load_records().values())

    def search(self, query: str, limit: int = 5) -> Dict[str, Any]:
        if not self.embeddings_enabled:
            return {"query": query, "results": [], "error": "Embeddings are not available. Install requirements first."}

        query_vector = list(self.embedding_model.embed([query]))[0].tolist()
        result = self.collection.query(query_embeddings=[query_vector], n_results=limit)
        hits = []
        ids = result.get("ids", [[]])[0]
        docs = result.get("documents", [[]])[0]
        metas = result.get("metadatas", [[]])[0]
        distances = result.get("distances", [[]])[0]

        for idx, doc_text in enumerate(docs):
            hits.append({
                "id": ids[idx] if idx < len(ids) else None,
                "text": doc_text,
                "metadata": metas[idx] if idx < len(metas) else {},
                "distance": distances[idx] if idx < len(distances) else None,
            })
        return {"query": query, "results": hits}

    def validate_document(self, document_id: str) -> Dict[str, Any]:
        record = self.get_document(document_id)
        if not record:
            return {"document_id": document_id, "error": "Document not found"}
        return self.validate_payload(record.get("chunks", []), record.get("qr_codes", []), record.get("tables", []))

    def validate_payload(self, chunks: List[Dict[str, Any]], qr_codes: List[Dict[str, Any]], tables: List[Dict[str, Any]]) -> Dict[str, Any]:
        text = "\n".join(chunk.get("text", "") for chunk in chunks).lower()
        dates = sorted(set(DATE_RE.findall(text)))[:20]
        amounts = sorted(set(match.strip() for match in AMOUNT_RE.findall(text) if any(char.isdigit() for char in match)))[:20]
        utility_score = sum(1 for term in UTILITY_TERMS if term in text)
        contract_score = sum(1 for term in CONTRACT_TERMS if term in text)
        document_type = "unknown"
        if utility_score >= 2 and utility_score >= contract_score:
            document_type = "utility_or_invoice"
        elif contract_score >= 2:
            document_type = "contract_or_agreement"

        checks = [
            {"name": "text_extracted", "status": "pass" if chunks else "fail", "evidence": f"{len(chunks)} text chunks"},
            {"name": "qr_codes", "status": "pass" if qr_codes else "missing", "evidence": f"{len(qr_codes)} QR code(s)"},
            {"name": "dates", "status": "pass" if dates else "missing", "evidence": dates[:5]},
            {"name": "amounts", "status": "pass" if amounts else "missing", "evidence": amounts[:5]},
            {"name": "tables", "status": "pass" if tables else "missing", "evidence": f"{len(tables)} table(s)"},
        ]

        missing = [check["name"] for check in checks if check["status"] in {"missing", "fail"}]
        risk_level = "low"
        if "text_extracted" in missing:
            risk_level = "high"
        elif len(missing) >= 3:
            risk_level = "medium"

        return {
            "document_type": document_type,
            "risk_level": risk_level,
            "checks": checks,
            "extracted_fields": {
                "dates": dates,
                "amounts": amounts,
                "qr_codes": [item.get("text") for item in qr_codes],
            },
            "missing_items": missing,
            "disclaimer": "AI-assisted document review only. Not legal certification.",
        }

    def _hash_file(self, path: Path) -> str:
        digest = hashlib.sha256()
        with path.open("rb") as handle:
            for block in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(block)
        return digest.hexdigest()

    def _find_by_hash(self, file_hash: str) -> Optional[Dict[str, Any]]:
        for record in self._load_records().values():
            if record.get("file_hash") == file_hash:
                return record
        return None

    def _chunk_text(self, document_id: str, filename: str, page_number: int, text: str) -> List[Dict[str, Any]]:
        words = text.split()
        chunks = []
        chunk_size = 220
        overlap = 40
        start = 0
        index = 0

        while start < len(words):
            end = min(start + chunk_size, len(words))
            chunk_text = " ".join(words[start:end])
            chunk_id = f"{document_id}-p{page_number}-c{index}"
            chunks.append({"id": chunk_id, "document_id": document_id, "filename": filename, "page": page_number, "chunk_index": index, "text": chunk_text})
            if end == len(words):
                break
            start = max(end - overlap, start + 1)
            index += 1
        return chunks

    def _detect_qr_codes(self, page: fitz.Page, page_number: int) -> List[Dict[str, Any]]:
        zoom = 2.0
        pix = page.get_pixmap(matrix=fitz.Matrix(zoom, zoom), alpha=False)
        image = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.height, pix.width, pix.n)
        results = []
        for code in zxingcpp.read_barcodes(image):
            if "QR" not in str(code.format):
                continue
            position = code.position
            points = [(position.top_left.x, position.top_left.y), (position.top_right.x, position.top_right.y), (position.bottom_right.x, position.bottom_right.y), (position.bottom_left.x, position.bottom_left.y)]
            xs = [point[0] for point in points]
            ys = [point[1] for point in points]
            results.append({"page": page_number, "text": code.text, "bbox": {"x": min(xs) / zoom, "y": min(ys) / zoom, "width": (max(xs) - min(xs)) / zoom, "height": (max(ys) - min(ys)) / zoom}})
        return results

    def _extract_tables(self, pdf_path: Path, document_id: str) -> List[Dict[str, Any]]:
        if pdfplumber is None:
            return []
        tables = []
        try:
            with pdfplumber.open(str(pdf_path)) as pdf:
                for page_index, page in enumerate(pdf.pages):
                    for table_index, table in enumerate(page.extract_tables() or []):
                        cleaned = [[cell if cell is not None else "" for cell in row] for row in table if row]
                        if cleaned:
                            tables.append({"document_id": document_id, "page": page_index + 1, "table_index": table_index, "rows": cleaned})
        except Exception as exc:
            tables.append({"document_id": document_id, "page": None, "table_index": None, "error": str(exc), "rows": []})
        return tables

    def _index_chunks(self, chunks: List[Dict[str, Any]]) -> None:
        texts = [chunk["text"] for chunk in chunks]
        vectors = [vector.tolist() for vector in self.embedding_model.embed(texts)]
        metadatas = [{"document_id": chunk["document_id"], "filename": chunk["filename"], "page": chunk["page"], "chunk_index": chunk["chunk_index"]} for chunk in chunks]
        self.collection.upsert(ids=[chunk["id"] for chunk in chunks], documents=texts, embeddings=vectors, metadatas=metadatas)

    def _write_report(self, document_id: str, filename: str, file_hash: str, pages: int, chunks: List[Dict[str, Any]], qr_codes: List[Dict[str, Any]], tables: List[Dict[str, Any]], validation: Dict[str, Any]) -> Path:
        report_path = self.report_dir / f"{document_id}.md"
        lines = [
            f"# Document Processing Report: {filename}",
            "",
            f"Document ID: `{document_id}`",
            f"SHA-256: `{file_hash}`",
            f"Pages: {pages}",
            f"Text chunks indexed: {len(chunks)}",
            f"QR codes detected: {len(qr_codes)}",
            f"Tables extracted: {len(tables)}",
            f"Validation risk: {validation.get('risk_level')}",
            "",
            "## QR Codes",
        ]
        lines.extend([f"- Page {item['page']}: {item['text']}" for item in qr_codes] or ["- None detected"])
        lines.extend(["", "## Validation Checks"])
        for check in validation.get("checks", []):
            lines.append(f"- {check['name']}: {check['status']} ({check['evidence']})")
        lines.extend(["", "## Disclaimer", validation.get("disclaimer", "AI-assisted review only.")])
        report_path.write_text("\n".join(lines), encoding="utf-8")
        return report_path

    def _load_records(self) -> Dict[str, Dict[str, Any]]:
        if not self.metadata_path.exists():
            return {}
        try:
            return json.loads(self.metadata_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return {}

    def _save_record(self, record: Dict[str, Any]) -> None:
        records = self._load_records()
        records[record["document_id"]] = record
        self.metadata_path.write_text(json.dumps(records, indent=2, ensure_ascii=False), encoding="utf-8")

    def _document_from_record(self, record: Dict[str, Any]) -> ProcessedDocument:
        return ProcessedDocument(
            document_id=record["document_id"],
            filename=record["filename"],
            file_hash=record["file_hash"],
            pages=record.get("pages", 0),
            chunks=record.get("chunks", []),
            qr_codes=record.get("qr_codes", []),
            tables=record.get("tables", []),
            report_path=Path(record["report_path"]),
            reused_existing=record.get("reused_existing", False),
        )