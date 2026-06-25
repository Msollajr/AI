# source-docs — Drop Your UDSM PDF Documents Here

Place any UDSM PDF documents in this folder, then run the ingestion script to automatically convert them into the knowledge base and re-index the AI.

## How to Add New Documents

1. Copy your PDF files into this `source-docs/` folder
2. Open a terminal in the project root and run:

```bash
# Activate the virtual environment first
.\venv\Scripts\Activate.ps1          # Windows PowerShell
# or
source venv/bin/activate             # Linux / macOS

# Run the ingestion script
python backend/ingest_pdfs.py
```

The script will:
- Convert each PDF to a structured Markdown file in `knowledge-base/`
- Automatically rebuild the ChromaDB vector index
- Print how many chunks were indexed

## Useful Options

```bash
# Ingest a specific PDF only
python backend/ingest_pdfs.py --pdf "source-docs/my-document.pdf"

# Force full re-index (use after editing existing markdown files)
python backend/ingest_pdfs.py --force

# Only convert PDFs to markdown, skip vector store rebuild
python backend/ingest_pdfs.py --skip-vectorize
```

## Recommended Documents to Add

| Document | Why It Helps |
|---|---|
| UDSM Academic Calendar 2025/2026 (official) | Real dates and deadlines |
| UDSM Fee Structure (official gazette) | Accurate fee amounts |
| UDSM Undergraduate Regulations | Full regulation text |
| UDSM Postgraduate Regulations | Master's and PhD rules |
| College/Faculty Handbooks | Programme-specific info |
| HESLB Loan Guide | Loan application details |
| Library Services Brochure | Database access, hours |
| Student Handbook | Code of conduct, services |
| Hostel Rules Booklet | Full hostel regulations |

## Notes
- **Scanned PDFs** (image-only, no selectable text) cannot be processed automatically.
  Use an OCR tool first (e.g., Adobe Acrobat, Microsoft Office Lens) to make the text selectable.
- After adding new docs, restart the backend server so the new chunks are loaded into memory.
- The `knowledge-base/` folder contains the Markdown versions of all documents.
  You can also edit those Markdown files directly and run `python backend/ingest_pdfs.py --force` to re-index.
