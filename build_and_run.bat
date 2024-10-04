@echo off
REM Variables
set IMAGE_NAME=naruzosa/salmon_run_notifier
set TAG=latest

REM Build the Docker image
echo Building Docker image...
docker build -t %IMAGE_NAME%:%TAG% .

REM Check if the build was successful
if %ERRORLEVEL% NEQ 0 (
    echo Docker build failed!
    exit /b %ERRORLEVEL%
)

REM Run the Docker container
echo Running Docker container...
docker run --rm -it %IMAGE_NAME%:%TAG%