@echo off
setlocal EnableDelayedExpansion
cd /d "%~dp0\.."

set "ACTION=%~1"
if "%ACTION%"=="" set "ACTION=up"
if not defined WAGGI_DIR (
  if exist ..ackend\main.py (set "WAGGI_DIR=..") else (set "WAGGI_DIR=../waggi")
)
set "CLUSTER=localnet"
if exist .keys\cluster set /p CLUSTER=<.keys\cluster
set "PROFILE="
if "%CLUSTER%"=="localnet" set "PROFILE=--profile localnet"

if "%ACTION%"=="up" (
  docker compose %PROFILE% up -d --wait || exit /b 1
  pushd "%WAGGI_DIR%" && docker compose up -d & popd
  exit /b 0
)
if "%ACTION%"=="down" (
  pushd "%WAGGI_DIR%" && docker compose down & popd
  docker compose --profile localnet --profile tools down
  exit /b 0
)
if "%ACTION%"=="restart" (
  call "%~f0" down
  call "%~f0" up
  exit /b 0
)
if "%ACTION%"=="ps" (
  docker compose %PROFILE% ps
  pushd "%WAGGI_DIR%" && docker compose ps & popd
  exit /b 0
)
if "%ACTION%"=="logs" (
  if "%~2"=="" (
    docker compose %PROFILE% logs --tail 50
    pushd "%WAGGI_DIR%" && docker compose logs --tail 50 & popd
  ) else (
    docker compose %PROFILE% logs -f %~2 2>NUL || (pushd "%WAGGI_DIR%" && docker compose logs -f %~2 & popd)
  )
  exit /b 0
)
if "%ACTION%"=="e2e" (
  docker compose --profile tools run --rm tools python scripts/e2e.py
  exit /b !errorlevel!
)
if "%ACTION%"=="test" (
  docker compose --profile tools run --rm anchor bash -lc "anchor build && cargo test"
  exit /b !errorlevel!
)
if "%ACTION%"=="reset" (
  pushd "%WAGGI_DIR%" && docker compose down -v & popd
  docker compose --profile localnet --profile tools down -v
  if exist .keys rmdir /s /q .keys
  exit /b 0
)
echo usage: %~nx0 up^|down^|restart^|ps^|logs [service]^|e2e^|test^|reset
exit /b 1
