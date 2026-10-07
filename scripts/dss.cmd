@echo off
rem Carbon Urban DSS operations runner.
rem Usage: scripts\dss.cmd [All, Doctor, Status, Backup, Rebuild, Probe, Collect, Snapshot, VerifyRestore, FrontendTest, ExportBundle, ImportBundle, MergeBundle, VerifyBundle, VerifyCases] [options]
chcp 65001 >nul
set "DSS_DIR=%~dp0"
set "DSS_ACTION=%~1"
if "%DSS_ACTION%"=="" set "DSS_ACTION=All"
if not "%~1"=="" shift
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%DSS_DIR%dss.ps1" -Action %DSS_ACTION% %1 %2 %3 %4 %5 %6
set "DSS_CODE=%errorlevel%"
echo.
echo Results: data\ops  (see data\ops\latest.txt)
if not "%DSS_NO_PAUSE%"=="1" pause
exit /b %DSS_CODE%
