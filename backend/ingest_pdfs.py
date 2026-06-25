"""
ingest_pdfs.py
--------------
PDF → Markdown → ChromaDB ingestion pipeline for the UDSM Student Support AI.

Usage:
    python backend/ingest_pdfs.py               # ingest all new PDFs
    python backend/ingest_pdfs.py --force       # re-index everything from scratch
    python backend/ingest_pdfs.py --pdf "path/to/specific.pdf"

How it works:
  1. Reads every PDF from the source-docs/ folder
  2. Extracts text using pdfplumber (preserves table layout better than PyPDF2)
  3. Cleans and converts the text to a structured Markdown file in knowledge-base/
  4. Rebuilds the ChromaDB vector index to include the new content

Drop your UDSM PDFs into:
    c:\\Users\\lenny silvanus\\Desktop\\AI\\source-docs\\

Supported: Academic regulations, student handbook, fee structures, calendars,
           hostel guides, examination rules, library guides, etc.
"""

import sys
import os
import re
import argparse
import logging
from pathlib import Path

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S"
)
logger = logging.getLogger(__name__)

# Paths
SCRIPT_DIR = Path(__file__).parent          # backend/
ROOT_DIR   = SCRIPT_DIR.parent             # project root
SOURCE_DIR = ROOT_DIR / "source-docs"      # drop PDFs here
KB_DIR     = ROOT_DIR / "knowledge-base"   # markdown output
VS_DIR     = SCRIPT_DIR / "vector_store"   # ChromaDB storage


def check_pdfplumber():
    """Verify pdfplumber is installed — fail clearly if not."""
    try:
        import pdfplumber  # noqa
        return True
    except ImportError:
        logger.error(
            "pdfplumber is not installed.\n"
            "Run this command first:\n"
            "  .\\venv\\Scripts\\Activate.ps1\n"
            "  pip install pdfplumber --prefer-binary\n"
        )
        return False


def extract_text_from_pdf(pdf_path: Path) -> str:
    """Extract text from a PDF preserving paragraph structure."""
    import pdfplumber

    pages_text = []
    try:
        with pdfplumber.open(str(pdf_path)) as pdf:
            logger.info(f"  Pages: {len(pdf.pages)}")
            for i, page in enumerate(pdf.pages, 1):
                text = page.extract_text(x_tolerance=3, y_tolerance=3)
                if text and text.strip():
                    pages_text.append(text.strip())
                    # Extract tables separately and append as markdown
                    tables = page.extract_tables()
                    for table in tables:
                        if table and len(table) > 1:
                            md_table = _table_to_markdown(table)
                            if md_table:
                                pages_text.append(md_table)

    except Exception as e:
        logger.error(f"  Error extracting PDF: {e}")
        return ""

    return "\n\n".join(pages_text)


def _table_to_markdown(table: list) -> str:
    """Convert a pdfplumber table (list of rows) to markdown table syntax."""
    if not table or not table[0]:
        return ""

    # Clean cells
    cleaned = []
    for row in table:
        cleaned_row = [str(cell).strip() if cell else "" for cell in row]
        cleaned.append(cleaned_row)

    # Use first row as header
    header = cleaned[0]
    rows   = cleaned[1:]

    if not any(header):
        return ""

    col_count = len(header)
    md = "| " + " | ".join(header) + " |\n"
    md += "| " + " | ".join(["---"] * col_count) + " |\n"
    for row in rows:
        # Pad row to header length
        padded = row + [""] * (col_count - len(row))
        md += "| " + " | ".join(padded[:col_count]) + " |\n"

    return md


def clean_and_structure(raw_text: str, doc_name: str) -> str:
    """
    Clean raw PDF text and convert to structured Markdown.

    Heuristics used:
    - Short ALL CAPS lines → ## section headers
    - Lines ending with ':' that are short → ### sub-headers
    - Numbered lists kept as-is
    - Bullet points standardised to '-'
    - Remove page numbers, headers/footers, and duplicate blank lines
    """
    lines = raw_text.split("\n")
    output = [f"# {doc_name}\n"]
    prev_blank = False

    for line in lines:
        stripped = line.strip()

        # Skip empty lines (collapse multiple blanks)
        if not stripped:
            if not prev_blank:
                output.append("")
            prev_blank = True
            continue
        prev_blank = False

        # Skip obvious page numbers (standalone digit / "Page N of M")
        if re.match(r'^(page\s*)?\d+(\s*of\s*\d+)?$', stripped, re.IGNORECASE):
            continue

        # Skip very short lines that are likely running headers/footers
        if len(stripped) < 4:
            continue

        # ALL CAPS short line → section header
        if stripped.isupper() and 4 <= len(stripped) <= 80:
            output.append(f"\n## {stripped.title()}")
            continue

        # Short line ending with ':' → sub-header
        if stripped.endswith(":") and len(stripped) <= 60 and not stripped.startswith("-"):
            output.append(f"\n### {stripped}")
            continue

        # Bullet standardisation (•, *, –, —, ▪, ●)
        bullet_match = re.match(r'^[•\*\–\—\▪\●]\s+(.*)', stripped)
        if bullet_match:
            output.append(f"- {bullet_match.group(1)}")
            continue

        output.append(stripped)

    return "\n".join(output)


def pdf_to_markdown(pdf_path: Path) -> Path:
    """
    Convert a PDF file to a Markdown file in knowledge-base/.

    Returns the path of the created .md file.
    """
    logger.info(f"Processing: {pdf_path.name}")

    # Build a clean document name from the filename
    doc_name = pdf_path.stem
    doc_name = re.sub(r'[_\-]+', ' ', doc_name)          # underscores/hyphens → spaces
    doc_name = re.sub(r'\s+', ' ', doc_name).strip()
    doc_name = doc_name.title()                            # Title Case

    # Extract text
    raw_text = extract_text_from_pdf(pdf_path)
    if not raw_text.strip():
        logger.warning(f"  No text extracted from {pdf_path.name} (scanned/image PDF?)")
        return None

    logger.info(f"  Extracted {len(raw_text)} characters")

    # Structure into Markdown
    markdown = clean_and_structure(raw_text, doc_name)

    # Write to knowledge-base/
    md_filename = pdf_path.stem.lower().replace(" ", "-") + ".md"
    md_path = KB_DIR / md_filename
    md_path.write_text(markdown, encoding="utf-8")
    logger.info(f"  Saved → {md_path.name} ({md_path.stat().st_size:,} bytes)")
    return md_path


def rebuild_vector_store(force: bool = False):
    """Rebuild the ChromaDB vector index from all markdown files."""
    logger.info("Rebuilding vector store index...")

    # Add backend to path so vector_store.py can import config
    if str(SCRIPT_DIR) not in sys.path:
        sys.path.insert(0, str(SCRIPT_DIR))

    # Change to backend dir so config.py relative paths resolve correctly
    original_dir = os.getcwd()
    os.chdir(str(SCRIPT_DIR))

    try:
        from vector_store import VectorStore
        vs = VectorStore()
        total = vs.build(KB_DIR, force=force)
        logger.info(f"Vector store rebuilt — {total} chunks indexed.")
        return total
    finally:
        os.chdir(original_dir)


def main():
    parser = argparse.ArgumentParser(
        description="Ingest UDSM PDF documents into the knowledge base and vector store."
    )
    parser.add_argument(
        "--pdf", type=str, default=None,
        help="Path to a specific PDF file to ingest (default: all PDFs in source-docs/)"
    )
    parser.add_argument(
        "--force", action="store_true",
        help="Force rebuild of vector store even if already indexed"
    )
    parser.add_argument(
        "--skip-vectorize", action="store_true",
        help="Only convert PDFs to markdown, skip vector store rebuild"
    )
    args = parser.parse_args()

    # Ensure pdfplumber is available
    if not check_pdfplumber():
        sys.exit(1)

    # Ensure directories exist
    SOURCE_DIR.mkdir(exist_ok=True)
    KB_DIR.mkdir(exist_ok=True)

    # Determine which PDFs to process
    if args.pdf:
        pdf_files = [Path(args.pdf)]
        if not pdf_files[0].exists():
            logger.error(f"File not found: {args.pdf}")
            sys.exit(1)
    else:
        pdf_files = sorted(SOURCE_DIR.glob("*.pdf"))
        if not pdf_files:
            logger.warning(f"No PDF files found in {SOURCE_DIR}")
            logger.info("Drop your UDSM PDF documents into the source-docs/ folder and run this script again.")
            sys.exit(0)

    logger.info(f"Found {len(pdf_files)} PDF(s) to process")
    converted = []

    for pdf_path in pdf_files:
        md_path = pdf_to_markdown(pdf_path)
        if md_path:
            converted.append(md_path)

    logger.info(f"\nConverted {len(converted)}/{len(pdf_files)} PDFs to Markdown")

    if converted and not args.skip_vectorize:
        total = rebuild_vector_store(force=True)
        logger.info(f"\n✅ Done! {total} chunks in vector store, {len(converted)} new documents added.")
    elif args.skip_vectorize:
        logger.info("\nSkipped vector store rebuild (--skip-vectorize flag). Run without the flag to index.")
    else:
        logger.warning("\nNo documents were successfully converted.")


if __name__ == "__main__":
    main()
