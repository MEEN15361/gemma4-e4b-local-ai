@echo off
title Gemma 4 E4B - AI Chat
echo ==========================================
echo   Gemma 4 E4B - Local AI Chat
echo ==========================================
echo.

:: Check if Ollama is running
tasklist /fi "imagename eq ollama.exe" 2>nul | findstr /i "ollama.exe" >nul
if errorlevel 1 (
    echo [*] Starting Ollama...
    start "" "%LOCALAPPDATA%\Programs\Ollama\ollama.exe" serve
    timeout /t 3 /nobreak >nul
) else (
    echo [OK] Ollama is already running
)

:: Load model from Modelfile (always update to pick up config changes)
echo [*] Loading model from Modelfile...
ollama create gemma4-e4b -f "%~dp0Modelfile"

echo [OK] Model: gemma4-e4b
echo [*] Starting Gradio Chat UI...
echo [*] Open browser: http://localhost:7860
echo.
echo     Press Ctrl+C to stop
echo ==========================================
echo.

cd /d "%~dp0"

:: Check Python and install dependencies if needed
py -3 -c "import gradio" 2>nul
if errorlevel 1 (
    echo [*] Installing dependencies...
    py -3 -m pip install -r requirements.txt
    echo.
)

py -3 app.py
pause
