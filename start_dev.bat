@echo off
:: =============================================================================
:: UDSM Student Support AI — Dev Launcher
:: Starts the FastAPI backend and Streamlit frontend in separate terminals.
::
:: Usage: double-click start_dev.bat  OR  run from project root in any terminal
:: =============================================================================

setlocal

:: ── Resolve project root (the folder this .bat file lives in) ─────────────────
set "ROOT=%~dp0"
:: Strip trailing backslash
if "%ROOT:~-1%"=="\" set "ROOT=%ROOT:~0,-1%"

:: ── Detect virtual environment ────────────────────────────────────────────────
set "VENV_ACTIVATE=%ROOT%\venv\Scripts\activate.bat"
set "ACTIVATE_CMD="
if exist "%VENV_ACTIVATE%" (
    set "ACTIVATE_CMD=call "%VENV_ACTIVATE%" &&"
) else (
    echo [WARN] No venv found at venv\Scripts\activate.bat — using system Python.
    echo        Run:  python -m venv venv ^&^& venv\Scripts\pip install -r requirements.txt
    echo.
)

:: ── 1. FastAPI Backend (uvicorn) ───────────────────────────────────────────────
echo [START] Launching FastAPI backend on http://localhost:8000 ...
start "UDSM Backend (FastAPI)" cmd /k ^
    "title UDSM Backend (FastAPI ^| port 8000) && ^
     cd /d "%ROOT%\backend" && ^
     %ACTIVATE_CMD% ^
     echo. && ^
     echo  =========================================== && ^
     echo   UDSM Backend  ^|  http://localhost:8000    && ^
     echo   API Docs      ^|  http://localhost:8000/docs && ^
     echo  =========================================== && ^
     echo. && ^
     python -m uvicorn main:app --host 127.0.0.1 --port 8000 --reload"

:: Small delay so the backend gets a head start before the frontend tries to connect
timeout /t 3 /nobreak >nul

:: ── 2. Streamlit Frontend ──────────────────────────────────────────────────────
echo [START] Launching Streamlit frontend on http://localhost:8501 ...
start "UDSM Frontend (Streamlit)" cmd /k ^
    "title UDSM Frontend (Streamlit ^| port 8501) && ^
     cd /d "%ROOT%" && ^
     %ACTIVATE_CMD% ^
     echo. && ^
     echo  =========================================== && ^
     echo   UDSM Frontend ^|  http://localhost:8501    && ^
     echo   Connects to   ^|  http://localhost:8000    && ^
     echo  =========================================== && ^
     echo. && ^
     streamlit run frontend\app.py --server.port 8501 --server.address localhost"

:: ── Done ──────────────────────────────────────────────────────────────────────
echo.
echo  Both services are starting in separate windows.
echo.
echo  Backend  -^>  http://localhost:8000
echo  Frontend -^>  http://localhost:8501
echo  API Docs -^>  http://localhost:8000/docs
echo.
echo  Close each terminal window to stop the service.
echo.
pause
endlocal
