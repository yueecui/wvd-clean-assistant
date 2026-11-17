@echo off
rem 构建绿色版：dist\WvdClean\  （Vue 前端 + Python 后端 + 主数据 + 图标 + adb）
setlocal
cd /d "%~dp0"

echo [1/4] 构建前端 web/dist ...
pushd web
call pnpm install --reporter=silent || goto :err
call pnpm build || goto :err
popd

echo [2/4] 打包 python 后端 ...
python -m PyInstaller --noconfirm --onefile --name wvd-clean ^
  --add-data "web\dist;web\dist" ^
  --collect-all rapidocr_onnxruntime ^
  --collect-all onnxruntime ^
  app\main.py || goto :err

echo [3/4] 组装 dist\WvdClean ...
set OUT=dist\WvdClean
rem 任何一步失败都要停下：exe 被占用时 rd / copy 会失败，否则会静默留下旧文件
if exist "%OUT%" rd /s /q "%OUT%" || goto :err
mkdir "%OUT%" || goto :err
copy /y dist\wvd-clean.exe "%OUT%\" >nul || goto :err
xcopy /e /i /y web\dist "%OUT%\web\dist" >nul || goto :err

rem 不创建 config / rules / result，也不复制开发环境的配置，避免升级覆盖用户数据
rem 三者都由运行时按需创建，随包的子目录只有 icons masterdata web

rem 主数据：装备 / 类型 / 词条 / 改造石数值档位（评分、名称校验、星级判定要用）
set MASTER=D:\WizardyDaphne\WizardyDaphneUnpack\out\masterdata
if "%WVD_MASTER%" NEQ "" set MASTER=%WVD_MASTER%
mkdir "%OUT%\masterdata"
for %%F in (Equipment.json EquipmentType.json EquipmentEffect.json EquipmentEffectUpgrade.json) do (
  if exist "%MASTER%\%%F" copy /y "%MASTER%\%%F" "%OUT%\masterdata\" >nul
)

rem 装备图标
set ICONS=D:\WizardyDaphne\WizardyDaphneUnpack\out\assets.lib\sprite\ListIcon
if "%WVD_ICONS%" NEQ "" set ICONS=%WVD_ICONS%
if exist "%ICONS%" xcopy /e /i /y "%ICONS%" "%OUT%\icons" >nul

rem 自带 adb（缺失时自动回退系统 PATH）
set MUMU=C:\Program Files\Netease\MuMu\nx_main
for %%F in (adb.exe AdbWinApi.dll AdbWinUsbApi.dll) do (
  if exist "%MUMU%\%%F" copy /y "%MUMU%\%%F" "%OUT%\" >nul
)

echo [4/4] 完成
echo.
dir /b "%OUT%"
echo.
echo 输出: %OUT%\wvd-clean.exe
endlocal
exit /b 0

:err
echo 构建失败
endlocal
exit /b 1
