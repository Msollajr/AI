import datetime
import logging
import sys
from fastapi import FastAPI, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, field_validator
from config import LOG_FILE_PATH, HOST, PORT, PROJECT_ROOT
from llm_client import LLMClient, LLMConnectionError

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s - %(message)s",
    handlers=[
        logging.FileHandler(LOG_FILE_PATH, encoding="utf-8"),
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger("student_support_backend")

# Initialize FastAPI and client
app = FastAPI(
    title="University Student Support Assistant API",
    description="Backend API serving a self-hosted LLM with semantic vector RAG (ChromaDB + sentence-transformers).",
    version="2.0.0"
)

# Configure CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # In production, specify the actual frontend domains
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

llm_client = LLMClient()

# Mount frontend directory for static assets (logo, etc)
app.mount(
    "/static",
    StaticFiles(directory=str(PROJECT_ROOT / "frontend")),
    name="static"
)

# Request/Response schemas
class QuestionRequest(BaseModel):
    question: str = Field(default="", description="The student's question")
    use_improved_prompt: bool = Field(True, description="Whether to apply prompt engineering / system template")

    @field_validator("question", mode="before")
    @classmethod
    def allow_empty_question(cls, v):
        """Allow empty strings — endpoint logic handles 400 response."""
        if v is None:
            return ""
        return v

class AskResponse(BaseModel):
    answer: str
    rag_context_used: bool
    category: str | None
    sources: list[str] = []
    confidence_label: str = "Low"
    confidence_score: float = 0.0
    faq_direct: bool = False
    timestamp: str

class FeedbackRequest(BaseModel):
    question: str
    answer: str
    rating: str = Field(..., description="Good / Average / Poor")

    @field_validator("rating")
    @classmethod
    def validate_rating(cls, v):
        allowed = {"Good", "Average", "Poor"}
        if v not in allowed:
            raise ValueError(f"Rating must be one of: {', '.join(sorted(allowed))}")
        return v

@app.get("/")
async def serve_spa():
    """
    Serves the premium modernized Student Support AI SPA portal.
    """
    index_path = PROJECT_ROOT / "frontend" / "index.html"
    if not index_path.exists():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Modernized index.html frontend was not found in project workspace."
        )
    return FileResponse(index_path)

@app.get("/health", status_code=status.HTTP_200_OK)
async def health_check():
    """
    Checks backend health and verifies local LLM availability.
    """
    logger.info("Health check endpoint called.")
    llm_connected, error_msg = llm_client.check_connection()
    if not llm_connected:
        logger.error(f"Health check LLM connection failed: {error_msg}")

    return {
        "status": "healthy" if llm_connected else "degraded",
        "llm_connected": llm_connected,
        "error": error_msg,
        "timestamp": datetime.datetime.now().isoformat()
    }

@app.post("/ask", response_model=AskResponse)
async def ask_question(request: QuestionRequest):
    """
    Receives a student's question, retrieves FAQ context, queries the local LLM,
    logs the interaction, and returns the response.
    """
    question = request.question.strip()
    if not question:
        logger.warning("Empty question received.")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Question cannot be empty or just whitespace."
        )

    logger.info(f"Received question: '{question}'")
    start_time = datetime.datetime.now()

    try:
        result = llm_client.generate_response(
            question=question,
            use_improved_prompt=request.use_improved_prompt
        )
        
        duration = (datetime.datetime.now() - start_time).total_seconds()
        logger.info(
            f"Successfully generated answer. Duration: {duration:.2f}s. "
            f"RAG: {result['rag_context_used']}, Category: {result['category']}"
        )
        
        # Log the full interaction details in the application log file
        logger.info(
            f"[INTERACTION]\n"
            f"Timestamp: {start_time.isoformat()}\n"
            f"Question: {question}\n"
            f"Answer: {result['answer']}\n"
            f"Prompt Used: {result['prompt_used']}\n"
            f"----------------------------------------"
        )
        
        return AskResponse(
            answer=result["answer"],
            rag_context_used=result["rag_context_used"],
            category=result["category"],
            sources=result.get("sources", []),
            confidence_label=result.get("confidence_label", "Low"),
            confidence_score=result.get("confidence_score", 0.0),
            faq_direct=result.get("faq_direct", False),
            timestamp=start_time.isoformat()
        )

    except LLMConnectionError as e:
        logger.error(f"Error handling question: {e}")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"Local LLM service is currently unavailable. Details: {str(e)}"
        )
    except Exception as e:
        logger.error(f"Unexpected error while processing question: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="An unexpected error occurred in the backend application."
        )

@app.post("/feedback", status_code=status.HTTP_200_OK)
async def submit_feedback(request: FeedbackRequest):
    """
    Saves user feedback / rating (Good / Average / Poor) to a feedback log.
    """
    feedback_file = LOG_FILE_PATH.parent / "feedback.log"
    timestamp = datetime.datetime.now().isoformat()
    
    log_entry = (
        f"Timestamp: {timestamp}\n"
        f"Question: {request.question}\n"
        f"Answer: {request.answer}\n"
        f"Rating: {request.rating}\n"
        f"----------------------------------------\n"
    )
    
    try:
        with open(feedback_file, "a", encoding="utf-8") as f:
            f.write(log_entry)
        
        logger.info(f"Feedback logged successfully: {request.rating}")
        return {"status": "success", "message": "Feedback saved."}
    except Exception as e:
        logger.error(f"Failed to save feedback: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to save feedback."
        )

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host=HOST, port=PORT, reload=True)
