@echo off
rem T14 Machine Log - double-click to start
chcp 65001 >nul
title T14 Machine Log - do not close this window while in use
cd /d "%~dp0"
set PYTHONUTF8=1
set PYTHONDONTWRITEBYTECODE=1
if not exist "%~dp0python\python.exe" (
  echo [ERROR] python\python.exe not found. Please extract the whole zip file.
  pause
  exit /b 1
)
"%~dp0python\python.exe" "%~dp0run.py"
if errorlevel 1 pause
