@echo off
chcp 65001 >nul
echo ========================================
echo   龙的传人网站 - 一键发布到 Cloudflare Pages
echo ========================================
echo.

echo [1/3] 正在构建网站...
python build_site.py
if %errorlevel% neq 0 (
    echo.
    echo ❌ 构建失败，请检查错误信息
    pause
    exit /b 1
)
echo ✅ 构建完成
echo.

echo [2/3] 正在部署到 Cloudflare Pages...
npx wrangler pages deploy dist --project-name=longchen-nyingtik --branch=main
if %errorlevel% neq 0 (
    echo.
    echo ❌ 部署失败，请检查错误信息
    pause
    exit /b 1
)
echo ✅ 部署完成
echo.

echo [3/3] 发布成功！
echo.
echo 临时地址: https://longchen-nyingtik.pages.dev
echo 正式地址: https://longchen-nyingtik.wiki （DNS 生效后可用）
echo.
echo ========================================
pause
