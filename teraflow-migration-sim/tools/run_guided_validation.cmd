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
echo TeraFlow - collaudo reale alle tre velocita.
echo Avviare questo file da Esplora file, fuori dal terminale gestito da Codex.
echo Lasciare questa finestra aperta. Il programma si ferma al primo errore.
echo I riepiloghi sono salvati in results\guided-validation.
echo Partenza automatica comune alle tre velocita, scelta dal simulatore.
".venv\Scripts\python.exe" tools\validate_guided_flow.py --live
set "validation_exit=%ERRORLEVEL%"
echo.
echo Collaudo terminato con codice %validation_exit%.
popd
pause
exit /b %validation_exit%
