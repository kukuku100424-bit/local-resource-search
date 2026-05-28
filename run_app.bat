@echo off
title Risk Map Server

echo ==============================
echo   위험지역 지도 서버 시작
echo ==============================

echo.
python --version

echo.
echo 서버를 시작합니다...
echo.

timeout /t 1 >nul

start "" "http://127.0.0.1:5000"

python app.py

echo.
echo 서버가 종료되었습니다.
pause