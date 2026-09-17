@echo off
REM ============================================================
REM  One-click launcher for ATS Resume Scorer
REM  Starts both FastAPI backend and Streamlit frontend
REM ============================================================

cd /d "%~dp0"
if exist "venv\Scripts\python.exe" (
    "venv\Scripts\python.exe" run.py
) else (
    python run.py
)
pause
