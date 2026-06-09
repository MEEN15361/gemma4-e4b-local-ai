@echo off
title Stopping Gemma 4 E4B
echo ==========================================
echo   Stopping Gemma 4 E4B - Free VRAM
echo ==========================================
echo.

:: 1. Stop the Gradio app
echo [1/4] Stopping Gradio app...
for /f "tokens=5" %%a in ('netstat -ano ^| findstr "0.0.0.0:7860" ^| findstr "LISTENING"') do (
    taskkill /PID %%a /F >nul 2>&1
)
echo       Done.

:: 2. Unload model from VRAM
echo [2/4] Unloading model from VRAM...
ollama stop gemma4-e4b >nul 2>&1
echo       Done.

:: 3. Stop Ollama processes
echo [3/4] Stopping Ollama processes...
taskkill /im "ollama_runners.exe" /f >nul 2>&1
taskkill /im "ollama.exe" /f >nul 2>&1
:: Also kill the Ollama desktop/tray app if running
taskkill /im "ollama app.exe" /f >nul 2>&1
echo       Done.

:: 4. Stop Ollama Windows service (if installed as service)
echo [4/4] Stopping Ollama service...
net stop "Ollama" >nul 2>&1
sc stop "ollama" >nul 2>&1
echo       Done.

:: Wait for VRAM to fully release
timeout /t 3 /nobreak >nul

:: Verify Ollama is stopped
tasklist /fi "imagename eq ollama.exe" 2>nul | findstr /i "ollama.exe" >nul
if errorlevel 1 (
    echo.
    echo ==========================================
    echo   VRAM freed! Ollama stopped completely.
    echo ==========================================
) else (
    echo.
    echo ==========================================
    echo   WARNING: Ollama may still be running!
    echo   Try: taskkill /im "ollama.exe" /f
    echo   Or restart your PC to fully free VRAM.
    echo ==========================================
)
echo.
pause
