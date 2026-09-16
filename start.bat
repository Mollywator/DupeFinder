@echo off
rem Developer launcher. End users get DupeFinder.exe from the GitHub release.
cd /d "%~dp0"
where pythonw >nul 2>nul || (echo Python wurde nicht gefunden. Bitte DupeFinder.exe verwenden. & pause & exit /b 1)
start "" pythonw DupeFinder.pyw
