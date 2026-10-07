@echo off
setlocal EnableDelayedExpansion
cd /d "%~dp0\.."

set "CLUSTER=%~1"
if "%CLUSTER%"=="" set "CLUSTER=localnet"
set "BRAND=%~2"
if not defined WAGGI_DIR (
  if exist ..ackend\main.py (set "WAGGI_DIR=..") else (set "WAGGI_DIR=../waggi")
)

if not exist .keys mkdir .keys

if "%CLUSTER%"=="localnet" (
  echo == local validator
  docker compose --profile localnet up -d --wait validator || exit /b 1
)

echo == program, deployer, clipUSD mint (%CLUSTER%)
docker compose --profile tools run --rm anchor bash -c "sed -i 's/\r$//' scripts/chain.sh && bash scripts/chain.sh %CLUSTER% %BRAND%" || exit /b 1

echo == tools image
docker compose --profile tools build tools || exit /b 1

echo == init_config + bonus pool
docker compose --profile tools run --rm tools python scripts/init_config.py || exit /b 1

echo == waggi .env
docker compose --profile tools run --rm tools python scripts/write_env.py || exit /b 1

echo == indexer + partner
docker compose up -d --build --wait indexer partner || exit /b 1

echo == waggi stack
pushd "%WAGGI_DIR%"
docker compose up -d --build
if errorlevel 1 (
  popd
  exit /b 1
)
popd

set "CODE=000"
for /l %%n in (1,1,60) do (
  for /f "delims=" %%c in ('curl -s -o NUL -w "%%{http_code}" http://localhost:8000/api/solana/config') do set "CODE=%%c"
  if "!CODE!"=="200" goto ready
  timeout /t 2 /nobreak >NUL
)
:ready
echo backend /api/solana/config -^> !CODE!
curl -s http://localhost:8000/api/solana/config
echo.
echo frontend  http://localhost:5173
echo backend   http://localhost:8000/docs
echo indexer   http://localhost:8001/health
echo partner   http://localhost:8002/health
if "%CLUSTER%"=="localnet" (
  echo wallet: Phantom -^> Settings -^> Developer settings -^> custom RPC http://localhost:8899
) else (
  echo wallet: Phantom -^> Settings -^> Developer settings -^> Devnet
)
echo end-to-end check: scripts\docker-compose.bat e2e
echo keys and addresses: .keys\chain.json (demo only, never commit)
endlocal
