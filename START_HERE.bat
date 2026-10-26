@echo off
setlocal
cd /d "%~dp0"
echo.
echo SmartTrip AI setup
if not exist venv (
    python -m venv venv
    if errorlevel 1 goto python_error
)
call venv\Scripts\activate
if not exist .env copy .env.example .env >nul
python -m pip install --upgrade pip
if errorlevel 1 goto install_error
python -m pip install -r requirements.txt
if errorlevel 1 goto install_error
echo.
echo Checking database migrations. Make sure MySQL Server is running and
 echo the database named in .env exists. Default: smarttrip.
echo Configure SMTP values in .env before testing email OTP.
python manage.py migrate
if errorlevel 1 goto database_error
python manage.py seed_data
if errorlevel 1 goto database_error
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
:database_error
echo.
echo Database setup failed. Check .env database credentials and ensure MySQL is running.
echo For a fresh database, run in this folder:
echo mysql -u root -p ^< database\create_mysql_database.sql
pause
exit /b 1
:app_error
echo Django checks failed. Review the error above.
pause
exit /b 1
:end
endlocal
