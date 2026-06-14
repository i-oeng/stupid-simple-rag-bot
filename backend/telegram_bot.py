import os
import tempfile
from pathlib import Path
from typing import Any, Dict, Optional

import httpx
from telegram import Document, Update
from telegram.constants import ParseMode
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes, MessageHandler, filters

BACKEND_URL = os.getenv("BACKEND_URL", "http://127.0.0.1:8000").rstrip("/")
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")

HELP_TEXT = """
Local Document Assistant

Send me a PDF and I will process it locally through the backend.

Commands:
/start - show this help
/status - check backend health
/search <query> - search processed documents
/ask <question> - ask Qwen over retrieved document chunks
/validate [document_id] - run validation checks
/case [document_id] - create a review case from a processed document
/summary [document_id] - summarize with Qwen/Ollama
/report [document_id] - download the Markdown report
/documents - list recent processed documents

If you omit document_id, I use your latest processed document.
""".strip()


def _last_doc(context: ContextTypes.DEFAULT_TYPE) -> Optional[str]:
    return context.user_data.get("last_document_id")


def _set_last_doc(context: ContextTypes.DEFAULT_TYPE, document_id: str) -> None:
    context.user_data["last_document_id"] = document_id


def _format_validation(validation: Dict[str, Any]) -> str:
    checks = validation.get("checks", [])
    lines = [
        f"Type: {validation.get('document_type', 'unknown')}",
        f"Risk: {validation.get('risk_level', 'unknown')}",
        "",
        "Checks:",
    ]
    for check in checks:
        lines.append(f"- {check.get('name')}: {check.get('status')}")
    missing = validation.get("missing_items") or []
    if missing:
        lines.extend(["", "Missing:", ", ".join(missing)])
    return "\n".join(lines)


def _doc_id_from_args(context: ContextTypes.DEFAULT_TYPE) -> Optional[str]:
    if context.args:
        return context.args[0].strip()
    return _last_doc(context)


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.effective_message.reply_text(HELP_TEXT)


async def status(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    async with httpx.AsyncClient(timeout=20) as client:
        response = await client.get(f"{BACKEND_URL}/health")
        response.raise_for_status()
        data = response.json()
    await update.effective_message.reply_text(
        "Backend status:\n"
        f"- status: {data.get('status')}\n"
        f"- embeddings: {data.get('embeddings_enabled')}\n"
        f"- tables: {data.get('tables_enabled')}\n"
        f"- ocr: {data.get('ocr_available')}\n"
        f"- model: {data.get('ollama_model')}\n"
        f"- cases: {data.get('case_count', 0)}"
    )


async def documents(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    async with httpx.AsyncClient(timeout=30) as client:
        response = await client.get(f"{BACKEND_URL}/documents")
        response.raise_for_status()
        docs = response.json().get("documents", [])

    if not docs:
        await update.effective_message.reply_text("No processed documents yet. Send me a PDF first.")
        return

    lines = ["Recent documents:"]
    for item in docs[-10:]:
        lines.append(f"- {item.get('filename')}\n  id: `{item.get('document_id')}`")
    await update.effective_message.reply_text("\n".join(lines), parse_mode=ParseMode.MARKDOWN)


async def handle_pdf(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message = update.effective_message
    document: Optional[Document] = message.document
    if document is None or document.mime_type != "application/pdf":
        await message.reply_text("Please send a PDF document.")
        return

    status_message = await message.reply_text("Processing PDF locally...")
    telegram_file = await document.get_file()

    with tempfile.TemporaryDirectory() as tmpdir:
        local_path = Path(tmpdir) / (document.file_name or "document.pdf")
        await telegram_file.download_to_drive(custom_path=local_path)

        async with httpx.AsyncClient(timeout=300) as client:
            with local_path.open("rb") as handle:
                files = {"files": (local_path.name, handle, "application/pdf")}
                response = await client.post(f"{BACKEND_URL}/process", files=files)
            response.raise_for_status()
            payload = response.json()

    docs = payload.get("documents", [])
    if not docs:
        await status_message.edit_text("No document result returned by backend.")
        return

    doc = docs[0]
    document_id = doc.get("document_id")
    if document_id:
        _set_last_doc(context, document_id)

    summary = doc.get("summary", {})
    validation = doc.get("validation", {})
    reply = (
        "Processed PDF\n"
        f"File: {doc.get('filename')}\n"
        f"ID: `{document_id}`\n"
        f"Pages: {doc.get('pages')}\n"
        f"Chunks: {summary.get('chunk_count')}\n"
        f"QR codes: {summary.get('qr_count')}\n"
        f"Visual markers: {summary.get('visual_marker_count')}\n"
        f"Tables: {summary.get('table_count')}\n"
        f"Risk: {validation.get('risk_level', 'unknown')}\n\n"
        "Use /case, /summary, /validate, /report, /search, or /ask next."
    )
    await status_message.edit_text(reply, parse_mode=ParseMode.MARKDOWN)


async def search(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = " ".join(context.args).strip()
    if not query:
        await update.effective_message.reply_text("Usage: /search <query>")
        return

    async with httpx.AsyncClient(timeout=60) as client:
        response = await client.get(f"{BACKEND_URL}/search", params={"q": query, "limit": 5})
        response.raise_for_status()
        results = response.json().get("results", [])

    if not results:
        await update.effective_message.reply_text("No matching chunks found.")
        return

    lines = [f"Search results for: {query}"]
    for item in results[:5]:
        meta = item.get("metadata") or {}
        text = (item.get("text") or "").replace("\n", " ")[:450]
        lines.append(f"\nPage {meta.get('page', '?')} - {meta.get('filename', 'unknown')}\n{text}")
    await update.effective_message.reply_text("\n".join(lines))


async def ask(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    question = " ".join(context.args).strip()
    if not question:
        await update.effective_message.reply_text("Usage: /ask <question>")
        return

    thinking = await update.effective_message.reply_text("Asking Qwen over retrieved chunks...")
    async with httpx.AsyncClient(timeout=180) as client:
        response = await client.post(f"{BACKEND_URL}/ask", json={"question": question, "limit": 5})
        response.raise_for_status()
        data = response.json()
    await thinking.edit_text(data.get("answer") or "No answer returned.")


async def validate(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    document_id = _doc_id_from_args(context)
    if not document_id:
        await update.effective_message.reply_text("Usage: /validate <document_id>, or send a PDF first.")
        return

    async with httpx.AsyncClient(timeout=60) as client:
        response = await client.get(f"{BACKEND_URL}/validate/{document_id}")
        response.raise_for_status()
        validation = response.json()
    await update.effective_message.reply_text(_format_validation(validation))


async def create_case(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    document_id = _doc_id_from_args(context)
    if not document_id:
        await update.effective_message.reply_text("Usage: /case <document_id>, or send a PDF first.")
        return

    async with httpx.AsyncClient(timeout=90) as client:
        response = await client.post(
            f"{BACKEND_URL}/cases/from-document/{document_id}",
            json={"client_info": {}, "metadata": {"owner": "Telegram intake", "department": "Review"}, "review_settings": {}, "actor": "telegram"},
        )
        response.raise_for_status()
        item = response.json()

    await update.effective_message.reply_text(
        "Review case created\n"
        f"Case ID: `{item.get('case_id')}`\n"
        f"Status: {item.get('status')}\n"
        f"Type: {item.get('case_summary', {}).get('document_type', 'unknown')}\n"
        f"Risk: {item.get('review_checklist', {}).get('risk_level', 'unknown')}",
        parse_mode=ParseMode.MARKDOWN,
    )


async def summary(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    document_id = _doc_id_from_args(context)
    if not document_id:
        await update.effective_message.reply_text("Usage: /summary <document_id>, or send a PDF first.")
        return

    thinking = await update.effective_message.reply_text("Summarizing with Qwen...")
    async with httpx.AsyncClient(timeout=180) as client:
        response = await client.post(f"{BACKEND_URL}/summarize/{document_id}", json={"max_chunks": 8})
        response.raise_for_status()
        data = response.json()
    await thinking.edit_text(data.get("summary") or "No summary returned.")


async def report(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    document_id = _doc_id_from_args(context)
    if not document_id:
        await update.effective_message.reply_text("Usage: /report <document_id>, or send a PDF first.")
        return

    async with httpx.AsyncClient(timeout=60) as client:
        response = await client.get(f"{BACKEND_URL}/documents/{document_id}/report")
        response.raise_for_status()
        content = response.content

    with tempfile.NamedTemporaryFile(delete=False, suffix=".md") as tmp:
        tmp.write(content)
        tmp_path = Path(tmp.name)

    try:
        await update.effective_message.reply_document(document=tmp_path.open("rb"), filename=f"report_{document_id}.md")
    finally:
        tmp_path.unlink(missing_ok=True)


async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    if isinstance(update, Update) and update.effective_message:
        await update.effective_message.reply_text(f"Error: {context.error}")


def main() -> None:
    if not TELEGRAM_BOT_TOKEN:
        raise RuntimeError("Set TELEGRAM_BOT_TOKEN before starting the bot.")

    application = ApplicationBuilder().token(TELEGRAM_BOT_TOKEN).build()
    application.add_handler(CommandHandler(["start", "help"], start))
    application.add_handler(CommandHandler("status", status))
    application.add_handler(CommandHandler("documents", documents))
    application.add_handler(CommandHandler("search", search))
    application.add_handler(CommandHandler("ask", ask))
    application.add_handler(CommandHandler("validate", validate))
    application.add_handler(CommandHandler("case", create_case))
    application.add_handler(CommandHandler("summary", summary))
    application.add_handler(CommandHandler("report", report))
    application.add_handler(MessageHandler(filters.Document.PDF, handle_pdf))
    application.add_error_handler(error_handler)
    application.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
