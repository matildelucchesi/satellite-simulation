@echo off
setlocal
pushd "%~dp0.."
if not exist ".venv\Scripts\python.exe" (
  echo Ambiente Python del progetto non disponibile.
  popd
  pause
  exit /b 1
)
set PYTHONUTF8=1
echo Console TeraFlow: http://127.0.0.1:18092/
".venv\Scripts\python.exe" tools\serve_gui.py
set "gui_exit=%ERRORLEVEL%"
popd
exit /b %gui_exit%
