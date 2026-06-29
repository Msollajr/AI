import datetime
import logging
import sys
from fastapi import FastAPI, HTTPException, status, Depends
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, field_validator
from sqlalchemy.ext.asyncio import AsyncSession
from config import LOG_FILE_PATH, HOST, PORT, PROJECT_ROOT
from llm_client import LLMClient, LLMConnectionError
import database
import models
import auth
from sqlalchemy.future import select
from sqlalchemy import desc

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

# Include Auth router
app.include_router(auth.router)

# Request/Response schemas
class QuestionRequest(BaseModel):
    question: str = Field(default="", description="The student's question")
    use_improved_prompt: bool = Field(True, description="Whether to apply prompt engineering / system template")
    session_id: str | None = Field(None, description="The ID of the chat session, if continuing an existing chat")

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
    session_id: str | None = None

class ChatSessionResponse(BaseModel):
    id: str
    title: str
    created_at: str

class InteractionResponse(BaseModel):
    id: int
    question: str
    answer: str
    rag_context_used: bool
    category: str | None
    timestamp: str

class FeedbackRequest(BaseModel):
    question: str
    answer: str
    rating: str = Field(..., description="Good / Average / Poor")
    interaction_id: int | None = None

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
async def ask_question(request: QuestionRequest, db: AsyncSession = Depends(database.get_db), current_user: models.User | None = Depends(auth.get_current_user)):
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
        
        # Save to database
        user_id = current_user.id if current_user else None
        session_id = request.session_id
        
        if current_user:
            if not session_id:
                title = question[:30] + ("..." if len(question) > 30 else "")
                new_session = models.ChatSession(user_id=user_id, title=title)
                db.add(new_session)
                await db.commit()
                await db.refresh(new_session)
                session_id = str(new_session.id)
                
        interaction = models.InteractionLog(
            user_id=user_id,
            session_id=session_id,
            question=question,
            answer=result["answer"],
            rag_context_used=result["rag_context_used"],
            category=result.get("category"),
            duration_sec=duration,
            prompt_used=result.get("prompt_used")
        )
        db.add(interaction)
        await db.commit()
        await db.refresh(interaction)
        
        return AskResponse(
            answer=result["answer"],
            rag_context_used=result["rag_context_used"],
            category=result["category"],
            sources=result.get("sources", []),
            confidence_label=result.get("confidence_label", "Low"),
            confidence_score=result.get("confidence_score", 0.0),
            faq_direct=result.get("faq_direct", False),
            timestamp=start_time.isoformat(),
            session_id=session_id
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
async def submit_feedback(request: FeedbackRequest, db: AsyncSession = Depends(database.get_db), current_user: models.User | None = Depends(auth.get_current_user)):
    """
    Saves user feedback / rating (Good / Average / Poor) to the database.
    """
    try:
        user_id = current_user.id if current_user else None
        feedback = models.Feedback(
            user_id=user_id,
            interaction_id=request.interaction_id,
            question=request.question,
            answer=request.answer,
            rating=request.rating
        )
        db.add(feedback)
        await db.commit()
        
        logger.info(f"Feedback logged successfully: {request.rating}")
        return {"status": "success", "message": "Feedback saved to database."}
    except Exception as e:
        logger.error(f"Failed to save feedback to database: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to save feedback."
        )

@app.get("/chat/sessions", response_model=list[ChatSessionResponse])
async def get_chat_sessions(db: AsyncSession = Depends(database.get_db), current_user: models.User = Depends(auth.get_current_active_user)):
    """Fetches all chat sessions for the current user."""
    result = await db.execute(
        select(models.ChatSession)
        .filter(models.ChatSession.user_id == current_user.id)
        .order_by(desc(models.ChatSession.created_at))
    )
    sessions = result.scalars().all()
    return [
        ChatSessionResponse(
            id=str(s.id),
            title=s.title,
            created_at=s.created_at.isoformat()
        ) for s in sessions
    ]

@app.get("/chat/sessions/{session_id}", response_model=list[InteractionResponse])
async def get_session_interactions(session_id: str, db: AsyncSession = Depends(database.get_db), current_user: models.User = Depends(auth.get_current_active_user)):
    """Fetches all interactions for a specific session."""
    result = await db.execute(
        select(models.InteractionLog)
        .filter(models.InteractionLog.session_id == session_id)
        .filter(models.InteractionLog.user_id == current_user.id)
        .order_by(models.InteractionLog.timestamp)
    )
    interactions = result.scalars().all()
    return [
        InteractionResponse(
            id=i.id,
            question=i.question,
            answer=i.answer,
            rag_context_used=i.rag_context_used,
            category=i.category,
            timestamp=i.timestamp.isoformat()
        ) for i in interactions
    ]

@app.delete("/chat/sessions/{session_id}")
async def delete_chat_session(session_id: str, db: AsyncSession = Depends(database.get_db), current_user: models.User = Depends(auth.get_current_active_user)):
    """Deletes a specific chat session."""
    result = await db.execute(
        select(models.ChatSession)
        .filter(models.ChatSession.id == session_id)
        .filter(models.ChatSession.user_id == current_user.id)
    )
    session = result.scalars().first()
    if not session:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Session not found")
    
    await db.delete(session)
    await db.commit()
    return {"status": "success", "message": "Session deleted"}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host=HOST, port=PORT, reload=True)
