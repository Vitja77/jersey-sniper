@echo off
setlocal EnableDelayedExpansion
title Jersey Sniper - watching for deals
cd /d "%~dp0"
set "PATH=%PATH%;C:\Program Files\Tesseract-OCR;%LOCALAPPDATA%\Programs\Tesseract-OCR"
set "PY="
for /d %%D in ("%LOCALAPPDATA%\Programs\Python\Python3*") do if exist "%%D\python.exe" set "PY=%%D\python.exe"
if not defined PY for /d %%D in ("C:\Program Files\Python3*") do if exist "%%D\python.exe" set "PY=%%D\python.exe"
if not defined PY (echo Python not found - run START.bat first. & pause & exit /b)
echo Jersey Sniper is running. It scans every few minutes. Close this window to stop.
"!PY!" sniper.py run
pause
