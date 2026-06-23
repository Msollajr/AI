# IS 365 - Practical Assignment Report

## Full-Stack Pipeline for Deploying a Self-Hosted LLM Application

**Course:** IS 365 - Practical Assignment
**Project Name:** University Student Support LLM Application

---

## 1. Introduction

Modern artificial intelligence deployment extends far beyond writing an LLM inference script. In production environments, an AI system is an orchestration of multiple connected layers: virtual environments, local model servers, robust API backends, web frontends, automated test suites, structured logging, and thorough error handling.

This report documents the design, implementation, and deployment of a self-hosted **University Student Support Assistant**. By running a local Small Language Model (SLM) on an offline server, this architecture demonstrates how organizations can leverage generative AI while maintaining absolute data ownership, zero API latency costs, and complete privacy.

---

## 2. System Use Case

The primary use case is to assist students with standard administrative inquiries across eight core areas:

- **Course Registration**: Timelines, portal navigation, adding/dropping classes.
- **Examination Rules**: Attendance rules, prohibited items, grading standards, and supplementary exams.
- **Library Services**: Opening hours, lending limits, OPAC search, online databases, and overdue fines.
- **ICT Support**: Campus Wi-Fi configuration, email login, and password resetting procedures.
- **Hostel Application**: On-campus accommodation allocation priority, portal application processes, and fees.
- **Fee Payment**: Payment channels, installment structures, and registration blocks for outstanding balances.
- **Academic Calendar**: Lecture weeks, mid-semester breaks, study leave, and exam periods.
- **Student Conduct**: Behavior codes, prohibited substances, dress codes, and disciplinary hearings.

To prevent the LLM from hallucinating administrative policies, we implemented a **Retrieval-Augmented Generation (RAG)** pipeline using a knowledge base of 11 official UDSM markdown documents alongside a keyword-matched FAQ database.

---

## 3. Tools and Technologies Used

| Component | Tool / Library Selected | Justification |
| :--- | :--- | :--- |
| **Operating System** | Windows | Host environment. |
| **Language & Environment** | Python 3.13 & venv | Clean package isolation and standard python scripting. |
| **Backend API Framework** | FastAPI | High performance, async endpoints, built-in validation, automatic OpenAPI (Swagger UI) documentation. |
| **Web Server** | Uvicorn | Lightning-fast ASGI web server implementation. |
| **Local LLM Server** | Ollama | Industry-standard local model serving tool with simple REST APIs. |
| **Model** | `llama3.2:1b` | Lightweight 1-billion parameter model suitable for low-latency local execution. |
| **Frontend** | Tailwind CSS SPA + Streamlit wrapper | Production-quality SPA served directly by FastAPI; Streamlit wraps it for the 8501 port requirement. |
| **API Testing Suite** | Pytest & TestClient | Unit test execution and mocking network connections. |

---

## 4. System Architecture

The application runs as a modular, three-tier local architecture:

```
                  ┌──────────────────────┐
                  │     Student User     │
                  └──────────────────────┘
                              │
                      User Input / Chat
                              ▼
                  ┌──────────────────────┐
                  │   Tailwind CSS SPA   │  (index.html served by FastAPI)
                  │   Streamlit Wrapper  │  (app.py on port 8501)
                  └──────────────────────┘
                        │            ▲
                 POST  /ask        JSON
                    Request       Response
                        ▼            │
                  ┌─────────────────────────────────────────┐
                  │           FastAPI Backend               │
                  │  ┌─────────┐  ┌──────────┐  ┌────────┐ │
                  │  │FAQ      │  │Semantic  │  │Convers-│ │
                  │  │Direct   │  │Cache     │  │ation   │ │
                  │  │Answer   │  │(30min    │  │Memory  │ │
                  │  │Engine   │  │TTL)      │  │(6turn) │ │
                  │  └─────────┘  └──────────┘  └────────┘ │
                  │  ┌─────────┐  ┌──────────┐              │
                  │  │Accuracy │  │Confidence│              │
                  │  │Check    │  │Scoring   │              │
                  │  └─────────┘  └──────────┘              │
                  └─────────────────────────────────────────┘
                     │        ▲           │
          Lookup FAQ  │        │ Context   │ Log interaction
          KB Docs     ▼        │ Loaded    │ & ratings
                  ┌──────────────┐    ┌─────────────────┐
                  │  faq.json    │    │  logs/app.log   │
                  │  knowledge-  │    │  logs/feed.log  │
                  │  base/*.md   │    └─────────────────┘
                  └──────────────┘
                        │            ▲
                 POST  /api/generate │
                   with context      │
                        ▼            │
                  ┌──────────────────────┐
                  │   Ollama Local LLM   │  (llama3.2:1b)
                  └──────────────────────┘
```

### Data Flow

1. **Student** submits a question via the SPA chat interface.
2. **FastAPI Backend** receives the question and checks:
   - **Semantic Cache** — returns cached answer if the same question was asked within 30 minutes.
   - **FAQ Direct Engine** — returns an exact FAQ answer without invoking the LLM if keyword confidence is >= 85%.
   - **Knowledge Base RAG** — retrieves relevant sections from 11 markdown documents using keyword overlap scoring.
   - **Conversation Memory** — checks for repeated or context-dependent questions across the last 6 turns.
3. The backend builds an **expert prompt** with system instructions, retrieved context, and conversation history, then sends it to Ollama.
4. **Ollama** processes the prompt and returns a generated response.
5. The backend runs an **accuracy check** (hallucination guardrails, minimum length), calculates a **confidence score** (based on FAQ score, RAG score, and source count), and optionally checks the UDSM website for time-sensitive updates.
6. The backend wraps the response in a **5-section structured format** (Answer, Steps, Useful Links, Sources, Confidence) and logs the interaction.
7. The **frontend** displays the formatted response with color-coded confidence badges, source citations, and feedback buttons.

---

## 5. Implementation Steps

### Task 1: Environment Setup

1. Created the virtual environment: `python -m venv venv`
2. Activated the environment and installed requirements: `pip install -r requirements.txt`

### Task 2: Local LLM Setup

1. Installed **Ollama** and ran the service.
2. Pulled the model: `ollama pull llama3.2:1b`
3. Verified the REST API was listening on `http://localhost:11434/api/generate`.

### Task 3: Backend Development

1. **`backend/config.py`**: Environment configuration for host, port, Ollama URL, model name, and file paths.
2. **`backend/llm_client.py`**: Core LLM client with:
   - `ConversationMemory` (max 6 turns, repeat question detection via SequenceMatcher)
   - `SemanticCache` (30-min TTL, similarity threshold 0.92, max 100 entries)
   - `FAQDirectAnswer` engine (returns FAQ without LLM when confidence >= 0.85)
   - `retrieve_context()`: searches FAQ + full-text KB index, returns context + sources
   - `construct_expert_prompt()`: builds a comprehensive prompt with the 5-section format requirement
   - `generate_response()`: end-to-end pipeline (cache → FAQ → RAG → prompt → LLM → accuracy → confidence → format)
   - `_calculate_confidence()`: hybrid scoring (FAQ score, RAG score, source count)
   - `_accuracy_check()`: hallucination detection (min length, refusal indicators)
   - `_check_web_for_updates()`: time-sensitive keyword detection, UDSM website fetch
   - `_format_structured_response()`: wraps answer in the 5-section format
   - `_extract_steps()`: extracts actionable steps from answer text using action-verb detection
3. **`backend/main.py`**: FastAPI application with three endpoints:
   - `GET /` — serves the Tailwind SPA
   - `GET /health` — checks LLM connectivity
   - `POST /ask` — accepts questions, returns structured responses with sources, confidence, and metadata
   - `POST /feedback` — logs user ratings (Good/Average/Poor)
4. **`backend/faq.json`**: FAQ database with keyword-linked answers for 8 university service categories.
5. **`knowledge-base/`**: 11 official UDSM markdown documents (Academic Regulations, Fee Structure, Hostel Guidelines, etc.) used for RAG context retrieval.

### Task 4: Frontend Development

1. **`frontend/index.html`**: Full Tailwind CSS SPA with:
   - Chat interface with message bubbles, loading spinners, and welcome splash
   - Color-coded confidence badges (High/Medium/Low)
   - Source citations display
   - 5-section response rendering (Answer, Steps, Links, Sources, Confidence)
   - Feedback buttons (Good/Average/Poor)
   - Dark mode toggle
   - Citations sidebar panel
   - Dashboard tab with mock student info cards
   - Fully responsive (mobile/tablet/desktop) with mobile sidebar overlay
2. **`frontend/app.py`**: Streamlit wrapper that embeds the SPA in a full-viewport iframe (46 lines).

### Task 5: Testing Setup

1. Created `tests/test_api.py` with comprehensive test cases:
   - Health endpoint verification
   - Empty/whitespace/missing question rejection
   - Response structure validation (all expected fields present)
   - FAQ direct answer confidence checks
   - 5-section format verification (Answer, Steps, Links, Sources, Confidence)
   - Feedback logging (all 3 ratings)
   - LLM unreachable scenario (503 handling)
   - SPA serving verification

---

## 6. Testing and Results

Running `pytest tests/test_api.py -v` verifies:

| Test | Status | Description |
| :--- | :--- | :--- |
| `test_health_returns_200` | PASS | Health endpoint responds |
| `test_health_has_expected_fields` | PASS | Returns status, llm_connected, timestamp |
| `test_rejects_empty_question` | PASS | Empty string returns 400 |
| `test_rejects_whitespace_only` | PASS | Whitespace returns 400 |
| `test_rejects_missing_question` | PASS | Missing field returns 422 |
| `test_response_has_expected_fields` | PASS | All response fields present |
| `test_faq_direct_answer_has_high_confidence` | PASS | FAQ answers have High confidence |
| `test_response_includes_links_section` | PASS | Useful Links section present |
| `test_response_includes_steps_section` | PASS | Steps section present |
| `test_response_includes_confidence` | PASS | Confidence section present |
| `test_feedback_saves_successfully` | PASS | Feedback endpoint works |
| `test_feedback_rejects_invalid_rating` | PASS | Invalid rating returns 422 |
| `test_feedback_accepts_average` | PASS | Average rating accepted |
| `test_feedback_accepts_poor` | PASS | Poor rating accepted |
| `test_returns_503_when_llm_unreachable` | PASS | 503 on LLM connection failure |
| `test_frontend_response_has_expected_format` | PASS | 5-section format confirmed |
| `test_spa_serves_index_html` | PASS | SPA served at root |

### Situation Error Handling Matrix (Task 7)

| Situation | Expected Behavior | Implementation |
| :--- | :--- | :--- |
| **Backend Not Running** | Frontend shows connection error | `catch (e)` block displays "❌ Network Error: Could not reach the API backend server." |
| **Model Not Running** | Backend returns clear error | `/health` reports `status: degraded`; `/ask` returns HTTP 503 "Local LLM service is currently unavailable" |
| **Empty Question** | Frontend asks user to enter a question | `alert("Please enter a question.")` + backend Pydantic `min_length=1` validation |
| **Slow Response** | Frontend shows loading/spinner | Animated ping loader message: "Retrieving database records..." |

---

## 7. Challenges Encountered

1. **Small Model Formatting Limitations**: The Llama 3.2 1B model lacks the capacity to reliably follow complex formatting instructions. We solved this by keeping the LLM prompt minimal (just ask it to answer naturally) and handling all 5-section formatting in Python code via `_format_structured_response()` with regex-based step extraction.
2. **Cold Start Timeouts**: The first LLM generation after a cold start exceeded 45 seconds. We increased the HTTP timeout to 120 seconds and added prompt truncation to keep generation time reasonable.
3. **LLM Number Hallucination**: The 1B model frequently invents fee amounts and dates. We addressed this by injecting retrieved KB context directly into the prompt and using the FAQ Direct engine to bypass the LLM entirely for known questions.

---

## 8. Bonus Features Implemented

### Option B: Retrieval-Augmented Generation (RAG)
- **11 knowledge-base markdown documents** covering all UDSM service areas, loaded and indexed at startup
- **Keyword overlap scoring** to rank and retrieve the most relevant document sections
- **FAQ injection** into the LLM prompt when FAQ confidence is between 60% and 85%
- FAQ Direct engine bypasses the LLM entirely when confidence >= 85% (sub-second responses)

### Option E: Response Evaluation
- User rating buttons (Good / Average / Poor) on each assistant message
- Feedback submitted via `POST /feedback` and logged to `logs/feedback.log`
- Visual confirmation after rating submission

---

## 9. Task 9: Industry Production Reflection

### 1. What are the main components of your deployed LLM system?
- **Ollama**: Serving the local model `llama3.2:1b` via REST API.
- **FastAPI Application**: Core API backend with RAG, caching, conversation memory, confidence scoring, and structured formatting.
- **Tailwind CSS SPA**: User interface with chat, dashboard, dark mode, and responsive design.
- **Knowledge Base (`knowledge-base/*.md`)**: 11 official documents for RAG context.
- **FAQ Database (`faq.json`)**: Keyword-linked FAQ answers.
- **Log Files**: `app.log` (interactions) and `feedback.log` (ratings).
- **Virtual Environment (`venv`)**: Python package isolation.

### 2. Why is FastAPI useful in this pipeline?
FastAPI is highly asynchronous, handles concurrent LLM generation requests without blocking, automatically generates interactive Swagger documentation (`/docs`), validates request bodies using Pydantic schemas, and provides structured HTTP exception handling.

### 3. What role does your chosen LLM model play?
`llama3.2:1b` processes the student question and retrieved context, synthesizes facts, and generates a human-like response. The 1B parameter size allows it to run on consumer hardware without a GPU.

### 4. What role does the frontend play?
The SPA captures user input, manages loading states, displays formatted 5-section responses with confidence badges and source citations, captures feedback ratings, and provides dark mode and responsive layout.

### 5. What is the difference between running the model locally and using an external API?
- **Local Run**: Complete privacy, zero cost per token, offline availability. Limited to smaller models.
- **External API**: More intelligent models, no local hardware req, auto-updates. Requires internet, incurs token costs, raises data privacy concerns.

### 6. What security risks may exist if this system is deployed in an organisation?
- **Prompt Injection**: Students craft inputs to bypass system rules.
- **Denial of Service**: Rapid concurrent queries overwhelm the local server.
- **Log Exposure**: Log files may record sensitive student identifiers.
- **Model Data Leakage**: The LLM might inadvertently repeat confidential information from its training data.

### 7. What improvements would be needed before deploying this system in production?
- **Authentication**: OAuth2 / SSO login for student identity verification.
- **GPU Acceleration**: NVIDIA CUDA deployment for sub-second generation.
- **Vector Database**: Upgrade keyword RAG to semantic search (ChromaDB, Qdrant).
- **Containerization**: Docker packaging for reliable deployment and scaling.
- **Rate Limiting**: Prevent DoS attacks via request throttling.

### 8. How would you monitor the system in real-world use?
- **Prometheus + Grafana**: Monitor CPU/GPU utilization, memory, request latency, error rates.
- **LLM Observability (LangFuse, Phoenix)**: Track prompt tokens, generation latency, user rating trends.

### 9. How would you protect sensitive student information?
- **Data Sanitization**: Strip personal identifiers (phone numbers, passwords, SSNs) from logs via regex.
- **HTTPS/TLS**: Encrypt all frontend-backend-LLM traffic.
- **RBAC**: Restrict API access tokens to authenticated roles.
- **Audit Trail**: Log all access attempts with timestamps and user IDs.

### 10. What challenges did you face during implementation?
- **Small Model Constraints**: 1B parameter model struggles with formatting and number accuracy — worked around via code-side formatting and FAQ direct engine.
- **Timeout Management**: Cold-start LLM generation exceeded default timeouts — increased to 120s and added prompt truncation.
- **Windows Environment**: Python path and permission issues on Windows required explicit handling.

---

## 10. Conclusion

A self-hosted LLM application pipeline provides a private, secure, and cost-effective method to automate student inquiries. Through FastAPI, a Tailwind CSS SPA, and Ollama, a robust application was constructed that safely guides model outputs using an offline RAG pipeline with caching, conversation memory, confidence scoring, and structured response formatting. The architecture provides a production-ready template for enterprise AI systems that require data sovereignty.

---

## 11. Appendix: Project Structure

```
student-support-llm/
├── backend/
│   ├── main.py              # FastAPI application (4 endpoints)
│   ├── llm_client.py        # LLM client (RAG, cache, memory, confidence)
│   ├── config.py            # Environment configuration
│   ├── faq.json             # FAQ knowledge base
│   └── logs/
│       ├── app.log          # Interaction logs
│       └── feedback.log     # User ratings (Option E)
├── frontend/
│   ├── index.html           # Tailwind CSS SPA (responsive)
│   └── app.py               # Streamlit wrapper
├── knowledge-base/          # 11 UDSM markdown documents (Option B RAG)
├── tests/
│   └── test_api.py          # Pytest test suite (17 tests)
├── docs/
│   ├── screenshots/         # Assignment evidence screenshots
│   └── report.md            # This report
├── requirements.txt         # Python dependencies
└── README.md                # Setup and operations guide
```

### Appendix: Task 6 Prompt Comparison

#### Original Prompt
```
{question}
```

#### Improved Prompt (Simplified)
```
You are the UDSM Student Support Assistant. Answer based only on the official UDSM information below. Never invent policies or fees.

Official UDSM information:
{retrieved KB context}

Student question: {question}
```

#### Effect of Improved Prompt
Before improvement, the model would answer from its general training data, often inventing university policies and fees. After improvement with RAG context injection, the model answers exclusively from the provided official documents. Additionally, the `_format_structured_response()` method wraps the LLM output in a consistent 5-section format (Answer, Steps, Useful Links, Sources, Confidence) that no longer depends on the model's formatting ability.
