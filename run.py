import os
import sys
import subprocess
import signal
import time

def main():
    root_dir = os.path.dirname(os.path.abspath(__file__))
    
    # Locate python executable in venv if available
    venv_python = os.path.join(root_dir, "venv", "Scripts", "python.exe")
    python_exe = venv_python if os.path.exists(venv_python) else sys.executable

    print("=" * 60)
    print("      🚀 Starting ATS Resume Scorer Application")
    print("=" * 60)
    print(f"Using Python: {python_exe}\n")

    # Command for backend (FastAPI)
    backend_cmd = [
        python_exe, "-m", "uvicorn", 
        "backend.main:app", 
        "--host", "0.0.0.0", 
        "--port", "8000"
    ]

    # Command for frontend (Streamlit)
    frontend_cmd = [
        python_exe, "-m", "streamlit", 
        "run", "frontend/streamlit_app.py", 
        "--server.port", "8501", 
        "--server.address", "0.0.0.0"
    ]

    print("👉 Starting FastAPI Backend on http://localhost:8000 ...")
    backend_process = subprocess.Popen(backend_cmd, cwd=root_dir)

    # Give backend a moment to initialize before opening frontend
    time.sleep(2)

    print("👉 Starting Streamlit Frontend on http://localhost:8501 ...")
    frontend_process = subprocess.Popen(frontend_cmd, cwd=root_dir)

    print("\n" + "=" * 60)
    print(" ✅ Both services are running!")
    print(" • Frontend: http://localhost:8501")
    print(" • Backend:  http://localhost:8000")
    print(" • API Docs: http://localhost:8000/docs")
    print(" Press Ctrl+C in this window to stop both servers.")
    print("=" * 60 + "\n")

    def cleanup(signum=None, frame=None):
        print("\n🛑 Shutting down backend and frontend...")
        for proc in (frontend_process, backend_process):
            try:
                proc.terminate()
            except Exception:
                pass
        time.sleep(1)
        for proc in (frontend_process, backend_process):
            try:
                proc.kill()
            except Exception:
                pass
        print("👋 All services stopped.")
        sys.exit(0)

    signal.signal(signal.SIGINT, cleanup)
    signal.signal(signal.SIGTERM, cleanup)

    try:
        # Wait for either process to exit
        while True:
            if backend_process.poll() is not None:
                print("⚠️ Backend server stopped unexpectedly.")
                break
            if frontend_process.poll() is not None:
                print("⚠️ Frontend server stopped.")
                break
            time.sleep(1)
    except KeyboardInterrupt:
        pass
    finally:
        cleanup()

if __name__ == "__main__":
    main()
