@echo off
REM Build the Docker image
echo Building Docker image...
docker compose up --build

REM Check if the build was successful
if %ERRORLEVEL% NEQ 0 (
    echo Docker build failed!
    exit /b %ERRORLEVEL%
)