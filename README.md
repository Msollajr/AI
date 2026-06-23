# University Student Support LLM Application

A full-stack, self-hosted LLM application pipeline for **IS 365 - Practical Assignment**. Features a **FastAPI** backend, a **Tailwind CSS SPA** frontend (served by FastAPI, wrapped in Streamlit), and a **local Ollama LLM** integration. Includes Retrieval-Augmented Generation (RAG), semantic caching, conversation memory, confidence scoring, and response evaluation.

---

## System Architecture

```
[Student User] --> [Tailwind SPA] --> [FastAPI Backend] --> [Ollama (llama3.2:1b)]
                      (port 8501 / 8000)       |
                                               ├── FAQ Direct Engine
                                               ├── Knowledge Base RAG (11 docs)
                                               ├── Semantic Cache
                                               ├── Conversation Memory
                                               ├── Confidence Scoring
                                               ├── Accuracy Checks
                                               ├── Structured Response Formatting
                                               └── Logging (app.log, feedback.log)
```

---

## Features

- **Local LLM Serving**: Ollama with `llama3.2:1b` (1.3B parameters).
- **Retrieval-Augmented Generation (RAG)**: 11 knowledge-base markdown documents + FAQ keyword matching to prevent hallucination.
- **FAQ Direct Answers**: Sub-second responses for known questions (bypasses LLM when confidence >= 85%).
- **Semantic Cache**: 30-minute TTL cache for repeated questions (similarity threshold 0.92).
- **Conversation Memory**: 6-turn memory with repeat question detection (SequenceMatcher > 0.85).
- **Confidence Scoring**: Hybrid score based on FAQ match, RAG overlap, and source count.
- **Accuracy Verification**: Hallucination guardrails (refusal indicators, minimum answer length).
- **Structured 5-Section Responses**: Every answer includes Answer, Steps, Useful Links, Sources, and Confidence.
- **Error Handling**:
  - Backend down: Frontend shows network error message.
  - LLM down: Backend returns 503 with clear message.
  - Empty question: Blocked on both frontend (alert) and backend (Pydantic validation).
  - Slow response: Animated loading spinner shown during LLM generation.
- **Response Evaluation (Option E)**: User rating buttons (Good / Average / Poor) logged to `backend/logs/feedback.log`.
- **Dark Mode**: Toggle between light and dark themes.
- **Responsive Design**: Mobile/tablet/desktop with sidebar overlay and adaptive layout.

---

## Setup & Running Instructions

### Prerequisites
- Python 3.10+
- Git
- [Ollama](https://ollama.com) (for local LLM serving)

### Step 1: Install and Run Ollama
```bash
# Pull the lightweight model
ollama pull llama3.2:1b

# Verify it's running
ollama run llama3.2:1b
```

### Step 2: Set Up Python Virtual Environment
```bash
# Create virtual environment
python -m venv venv

# Activate (Windows PowerShell)
.\venv\Scripts\Activate.ps1

# Activate (Windows cmd)
.\venv\Scripts\activate.bat

# Activate (macOS/Linux)
source venv/bin/activate
```

### Step 3: Install Dependencies
```bash
pip install -r requirements.txt
```

### Step 4: Run the FastAPI Backend
```bash
cd backend
python main.py
```
The backend starts on `http://127.0.0.1:8000`.
- Swagger UI: `http://127.0.0.1:8000/docs`
- Health check: `http://127.0.0.1:8000/health`

### Step 5: Access the Frontend
The SPA is served directly by FastAPI at `http://127.0.0.1:8000/`.

For the Streamlit wrapper (port 8501):
```bash
streamlit run frontend/app.py --server.port 8501
```

---

## API Endpoints

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/` | Serves the Tailwind CSS SPA |
| `GET` | `/health` | System health check (LLM status, timestamp) |
| `POST` | `/ask` | Submit a question to the LLM |
| `POST` | `/feedback` | Submit response rating (Good/Average/Poor) |

### POST /ask — Request Body
```json
{
  "question": "How do I register for courses?",
  "use_improved_prompt": true
}
```

### POST /ask — Response Body
```json
{
  "answer": "Answer:\n...\n\nWhat you should do:\n...\n\nUseful Links:\n...\n\nSources:\n...\n\nConfidence:\nHigh (95%)",
  "rag_context_used": true,
  "category": "Course Registration",
  "sources": ["UDSM FAQ - Course Registration"],
  "confidence_label": "High",
  "confidence_score": 0.95,
  "faq_direct": false,
  "timestamp": "2026-06-21T00:53:42.848657"
}
```

---

## Testing

```bash
pytest tests/test_api.py -v
```

The test suite covers:
- Health endpoint verification
- Empty/whitespace/missing question rejection (400/422)
- Response structure (all required fields present)
- FAQ direct answer confidence validation
- 5-section format verification
- Feedback endpoint (all 3 ratings)
- LLM unreachable scenario (503 handling)
- SPA serving verification

---

## Project Structure

```
student-support-llm/
├── backend/
│   ├── main.py              # FastAPI server (4 endpoints)
│   ├── llm_client.py        # LLM client (RAG, cache, memory, confidence)
│   ├── config.py            # Environment configuration
│   ├── faq.json             # FAQ knowledge base
│   ├── logs/
│   │   ├── app.log          # Interaction logs
│   │   └── feedback.log     # User ratings
│   └── __pycache__/
├── frontend/
│   ├── index.html           # Tailwind CSS SPA (responsive, dark mode)
│   └── app.py               # Streamlit wrapper
├── knowledge-base/          # 11 UDSM markdown RAG documents
├── tests/
│   └── test_api.py          # Pytest test suite
├── docs/
│   ├── screenshots/         # Assignment evidence screenshots
│   └── report.md            # Technical report
├── requirements.txt         # Python dependencies
└── README.md                # This file
```

---

## Bonus Features

- **Option B — RAG**: 11 knowledge-base documents + FAQ keyword matching for accurate context retrieval.
- **Option E — Response Evaluation**: User rating buttons with feedback logging.
