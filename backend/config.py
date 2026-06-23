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
MODEL_NAME = os.getenv("MODEL_NAME", "llama3.2:1b")

# File Paths
FAQ_FILE_PATH = BASE_DIR / "faq.json"
LOG_DIR = BASE_DIR / "logs"
LOG_FILE_PATH = LOG_DIR / "app.log"

# Ensure log directory exists
LOG_DIR.mkdir(parents=True, exist_ok=True)
