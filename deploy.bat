@echo off
:: =============================================================================
:: UDSM Student Support AI — One-Command Docker Deployment (Windows)
::
:: Usage:  deploy.bat           (production — Nginx on port 80)
::         deploy.bat dev       (dev mode — hot reload, port 8000)
::         deploy.bat down      (stop all containers)
::         deploy.bat logs      (tail all logs)
::         deploy.bat reset     (stop + delete all volumes ⚠ destroys data)
::
:: Prerequisites: Docker Desktop running with Linux containers
:: =============================================================================

setlocal
set "ROOT=%~dp0"
if "%ROOT:~-1%"=="\" set "ROOT=%ROOT:~0,-1%"
set "MODE=%~1"

:: ── Colour helpers (ANSI via PowerShell echo trick) ───────────────────────────
set "GREEN=[32m"
set "YELLOW=[33m"
set "RED=[31m"
set "CYAN=[36m"
set "RESET=[0m"

:: ── Handle sub-commands ───────────────────────────────────────────────────────
if /i "%MODE%"=="down" (
    echo %CYAN%[UDSM] Stopping all containers...%RESET%
    docker compose -f "%ROOT%\docker-compose.yml" down
    goto :EOF
)

if /i "%MODE%"=="logs" (
    echo %CYAN%[UDSM] Tailing logs (Ctrl+C to stop)...%RESET%
    docker compose -f "%ROOT%\docker-compose.yml" logs -f
    goto :EOF
)

if /i "%MODE%"=="reset" (
    echo %RED%[WARN] This will DELETE all volumes (models, vector store, cache).%RESET%
    set /p CONFIRM="Type YES to confirm: "
    if /i "!CONFIRM!"=="YES" (
        docker compose -f "%ROOT%\docker-compose.yml" down -v
        echo %GREEN%[UDSM] All volumes removed.%RESET%
    ) else (
        echo %YELLOW%[UDSM] Reset cancelled.%RESET%
    )
    goto :EOF
)

:: ── Pre-flight checks ─────────────────────────────────────────────────────────
echo.
echo  %CYAN%=============================================%RESET%
echo   UDSM Student Support AI — Docker Deploy
echo  %CYAN%=============================================%RESET%
echo.

:: Check Docker is available
docker info >nul 2>&1
if errorlevel 1 (
    echo %RED%[ERROR] Docker is not running or not installed.%RESET%
    echo         Please start Docker Desktop and try again.
    pause
    exit /b 1
)
echo %GREEN%[OK]%RESET% Docker is running.

:: Create .env from .env.example if it doesn't exist
if not exist "%ROOT%\.env" (
    if exist "%ROOT%\.env.example" (
        echo %YELLOW%[INFO] .env not found — copying from .env.example%RESET%
        copy "%ROOT%\.env.example" "%ROOT%\.env" >nul
        echo %GREEN%[OK]%RESET% .env created. Edit it to customise settings.
    ) else (
        echo %YELLOW%[WARN] No .env or .env.example found — using built-in defaults.%RESET%
    )
)

:: Validate docker-compose config
echo %CYAN%[INFO]%RESET% Validating docker-compose config...
docker compose -f "%ROOT%\docker-compose.yml" config --quiet
if errorlevel 1 (
    echo %RED%[ERROR] docker-compose.yml has errors. Aborting.%RESET%
    pause
    exit /b 1
)
echo %GREEN%[OK]%RESET% Config valid.

:: ── Launch ────────────────────────────────────────────────────────────────────
if /i "%MODE%"=="dev" (
    echo.
    echo %YELLOW%[DEV]%RESET% Starting in DEVELOPMENT mode (hot-reload, port 8000)...
    echo.
    docker compose -f "%ROOT%\docker-compose.yml" -f "%ROOT%\docker-compose.override.yml" up -d --build
    if errorlevel 1 (
        echo %RED%[ERROR] Docker Compose failed. Check the output above.%RESET%
        pause & exit /b 1
    )
    echo.
    echo  %GREEN%Services started:%RESET%
    echo   Backend   -^>  http://localhost:8000
    echo   API Docs  -^>  http://localhost:8000/docs
    echo   Health    -^>  http://localhost:8000/health
) else (
    echo.
    echo %CYAN%[PROD]%RESET% Starting in PRODUCTION mode (Nginx on port 80)...
    echo.
    docker compose -f "%ROOT%\docker-compose.yml" up -d --build
    if errorlevel 1 (
        echo %RED%[ERROR] Docker Compose failed. Check the output above.%RESET%
        pause & exit /b 1
    )
    echo.
    echo  %GREEN%Services started:%RESET%
    echo   App       -^>  http://localhost
    echo   API Docs  -^>  http://localhost/docs
    echo   Health    -^>  http://localhost/health
    echo   API       -^>  http://localhost/api/ask
)

echo.
echo  Useful commands:
echo    Logs:   deploy.bat logs
echo    Stop:   deploy.bat down
echo    Dev:    deploy.bat dev
echo.
pause
endlocal
