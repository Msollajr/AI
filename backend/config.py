import os
from pathlib import Path

# Base directories
BASE_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = BASE_DIR.parent

# API Server Configuration
HOST = os.getenv("API_HOST", "127.0.0.1")
PORT = int(os.getenv("API_PORT", 8000))

# LLM / Ollama Configuration
OLLAMA_API_URL = os.getenv("OLLAMA_API_URL", "http://localhost:11434/api/generate")
MODEL_NAME = os.getenv("MODEL_NAME", "qwen2.5:3b")

# File Paths
FAQ_FILE_PATH = BASE_DIR / "faq.json"
LOG_DIR = BASE_DIR / "logs"
LOG_FILE_PATH = LOG_DIR / "app.log"

# Vector Store (ChromaDB) path — persisted on disk, rebuilt only when docs change
VECTOR_STORE_PATH = BASE_DIR / "vector_store"

# Ensure directories exist
LOG_DIR.mkdir(parents=True, exist_ok=True)
VECTOR_STORE_PATH.mkdir(parents=True, exist_ok=True)

