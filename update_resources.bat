@echo off
chcp 65001 >nul
cd /d "%~dp0"
title WVD 资源更新

rem ==================== 本地解包目录配置 ====================
rem 游戏客户端解包后的 out 目录（内含 masterdata\ 与 assets.lib\sprite\ListIcon\）
rem 留空 = 从 GitHub 增量下载；填写 = 从该目录同步资源进项目并刷新 manifest
set "WVD_UNPACK=D:\WizardyDaphne\WizardyDaphneUnpack\out"
rem ==========================================================

echo ============================================
echo   WVD 装备清理助手 - 游戏资源更新
echo   (masterdata / icons)
echo ============================================
echo.
if defined WVD_UNPACK (
  echo 模式：从本地解包目录同步
  echo   %WVD_UNPACK%
) else (
  echo 模式：从 GitHub 增量更新
)
echo.

python tools\update_resources_cli.py
set RC=%ERRORLEVEL%

echo.
if "%RC%"=="0" (
  echo 资源更新结束。
) else (
  echo 资源更新失败，请查看上面的错误信息。
)
echo.
pause
