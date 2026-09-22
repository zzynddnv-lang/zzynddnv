@echo off
chcp 65001 > nul
set "PATH=C:\Program Files\Git\cmd;%PATH%"
title GitHub'ga kodni yuklash
echo ========================================================
echo   ZUXRIDDIN YORDAMCHISI - GITHUB'GA YUKLASH (PUSH)
echo ========================================================
echo.
echo GitHub'ga yuklanmoqda...
echo Agar brauzeringizda oyna ochilsa, "Sign in with your browser" yoki "Authorize" tugmasini bosing.
echo.

git push -u origin main

echo.
echo ========================================================
echo   Muvaffaqiyatli bo'lsa, istalgan tugmani bosib yoping!
echo ========================================================
pause
