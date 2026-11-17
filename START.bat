@echo off
setlocal EnableDelayedExpansion
title Jersey Sniper - test scan
cd /d "%~dp0"
set "PATH=%PATH%;C:\Program Files\Tesseract-OCR;%LOCALAPPDATA%\Programs\Tesseract-OCR"

echo === Checking Python ===
call :findpy
if not defined PY (
  echo Python not installed - installing it now with winget ^(takes 1-3 minutes^)...
  winget install --id Python.Python.3.12 --exact --scope user --silent --accept-package-agreements --accept-source-agreements
  call :findpy
)
if not defined PY (
  echo.
  echo Could not install Python automatically.
  echo Install it from https://www.python.org/downloads/ and tick "Add Python to PATH", then run START again.
  pause & exit /b
)
"!PY!" --version

echo === Checking Tesseract ===
tesseract --version >nul 2>nul || (
  echo Tesseract not found - installing it now...
  winget install --id UB-Mannheim.TesseractOCR --exact --silent --accept-package-agreements --accept-source-agreements
)
tesseract --version >nul 2>nul || (echo Tesseract still not found. Restart the PC and run START again. & pause & exit /b)
echo Tesseract OK

echo === Installing packages (first time takes a minute) ===
"!PY!" -m pip install -q -r requirements.txt

echo === Running one test scan ===
"!PY!" sniper.py once -v
echo.
echo Done. Double-click RUN-FOREVER.bat to keep watching for deals.
pause
exit /b

:findpy
set "PY="
for /d %%D in ("%LOCALAPPDATA%\Programs\Python\Python3*") do if exist "%%D\python.exe" set "PY=%%D\python.exe"
if not defined PY for /d %%D in ("C:\Program Files\Python3*") do if exist "%%D\python.exe" set "PY=%%D\python.exe"
if not defined PY (py -3 --version >nul 2>nul && for /f "delims=" %%P in ('py -3 -c "import sys;print(sys.executable)"') do set "PY=%%P")
exit /b
