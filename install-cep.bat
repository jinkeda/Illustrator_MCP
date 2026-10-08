@echo off
REM Python 3.10+ is already required by the server. Activate its venv first.
python "%~dp0install_cep.py"
exit /b %errorlevel%
