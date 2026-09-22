@echo off
echo ============================================================
echo Starting Autonomous Learning Agent (Local Mode - No Docker)
echo ============================================================

REM Check if Ollama is running
curl -s http://localhost:11434/api/tags >nul 2>&1
if %ERRORLEVEL% NEQ 0 (
    echo [WARNING] Ollama does not appear to be running!
    echo Please start Ollama or download it from https://ollama.com
    pause
)

echo Starting Backend API Server on http://localhost:8000...
start "Autonomous Agent Backend" cmd /k "cd /d %~dp0backend && .\venv\Scripts\activate && uvicorn app.main:app --port 8000 --reload"

echo Starting Frontend UI on http://localhost:5173...
start "Autonomous Agent Frontend" cmd /k "cd /d %~dp0frontend && npm run dev"

echo.
echo ============================================================
echo Both servers are launching in separate windows!
echo - Frontend: http://localhost:5173
echo - Backend:  http://localhost:8000
echo - Swagger:  http://localhost:8000/docs
echo ============================================================
pause
