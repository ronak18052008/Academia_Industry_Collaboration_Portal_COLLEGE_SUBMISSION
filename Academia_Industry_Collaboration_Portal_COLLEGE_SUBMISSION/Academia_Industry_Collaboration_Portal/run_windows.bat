@echo off
setlocal
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  echo Creating virtual environment...
  python -m venv .venv
  if errorlevel 1 (
    echo Failed to create virtual environment. Make sure Python 3.10+ is installed.
    pause
    exit /b 1
  )
)
call ".venv\Scripts\activate.bat"
echo Installing required packages...
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
if errorlevel 1 (
  echo.
  echo Package installation failed.
  echo If you are using Python 3.14, this project requires psycopg 3.2.10 or newer.
  echo Try running: python -m pip install -r requirements.txt
  pause
  exit /b 1
)
if not exist ".env" copy ".env.example" ".env" >nul
python app.py
pause
