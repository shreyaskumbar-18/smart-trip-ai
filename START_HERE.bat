@echo off
setlocal
cd /d "%~dp0"
echo.
echo SmartTrip AI setup
if not exist venv (
    python -m venv venv
    if errorlevel 1 goto python_error
    call venv\Scripts\activate
    python -m pip install --upgrade pip
    if errorlevel 1 goto install_error
    python -m pip install -r requirements.txt
    if errorlevel 1 goto install_error
)
call venv\Scripts\activate
if not exist .env (
    copy .env.example .env >nul
    echo Created .env from the example. Review its local settings before continuing.
)
echo.
echo This launcher does not migrate or seed your database.
echo Back up the target database and review pending migrations first.
python manage.py check
if errorlevel 1 goto app_error
echo.
echo SmartTrip AI is starting at http://127.0.0.1:8000/
python manage.py runserver
goto end

:python_error
echo Could not create the Python virtual environment. Install Python 3.10 or newer and retry.
pause
exit /b 1
:install_error
echo Dependency installation failed. Check your Python version and internet connection.
pause
exit /b 1
:app_error
echo Django checks failed. Review the error above.
pause
exit /b 1
:end
endlocal
