@echo off
chcp 65001 >nul
rem 开发模式：后端 23456（源码模式，不自动开浏览器）+ 前端 Vite 5173（/api 代理到后端）
rem 平时改前端只需开着 pnpm dev，保存即热更新；要打绿色版才需要 pnpm build
setlocal
cd /d "%~dp0"

if not exist "web\node_modules" (
  echo [提示] 未找到 web\node_modules，正在安装前端依赖 ...
  pushd "%~dp0web"
  call pnpm install
  popd
)

echo [1/2] 启动后端 http://127.0.0.1:23456 ...
set WVD_NO_BROWSER=1
start "WVD backend" /d "%~dp0" cmd /k python app\main.py

echo [2/2] 启动前端 http://127.0.0.1:5173 ...
start "WVD web" /d "%~dp0web" cmd /k pnpm dev

echo.
echo 打开 http://127.0.0.1:5173 （热更新；后端接口走 vite 代理到 23456）
endlocal
