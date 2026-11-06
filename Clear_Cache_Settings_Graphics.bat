@echo off
echo Moving Starsector UI files to the Recycle Bin...

:: Set the base directory to the exact folder where this batch file is located
set "BASE_DIR=%~dp0"

:: Use PowerShell to dynamically locate the files and send them to the Recycle Bin
powershell -NoProfile -Command ^
  "Add-Type -AssemblyName Microsoft.VisualBasic;" ^
  "$jsonPath = Join-Path '%BASE_DIR%' 'Star_UI\Star_UI_Settings.json';" ^
  "if (Test-Path $jsonPath) { [Microsoft.VisualBasic.FileIO.FileSystem]::DeleteFile($jsonPath, 'OnlyErrorDialogs', 'SendToRecycleBin') };" ^
  "$cachePath = Join-Path '%BASE_DIR%' 'Star_UI\.cache';" ^
  "if (Test-Path $cachePath) { Get-ChildItem -Path $cachePath | ForEach-Object { if ($_.PSIsContainer) { [Microsoft.VisualBasic.FileIO.FileSystem]::DeleteDirectory($_.FullName, 'OnlyErrorDialogs', 'SendToRecycleBin') } else { [Microsoft.VisualBasic.FileIO.FileSystem]::DeleteFile($_.FullName, 'OnlyErrorDialogs', 'SendToRecycleBin') } } };" ^
  "$graphicsPath = Join-Path '%BASE_DIR%' 'Star_UI\Data\graphics_basegame';" ^
  "if (Test-Path $graphicsPath) { [Microsoft.VisualBasic.FileIO.FileSystem]::DeleteDirectory($graphicsPath, 'OnlyErrorDialogs', 'SendToRecycleBin') };" ^
  "$exePath = 'D:\- Starsector UI Color\Star_UI.exe';" ^
  "if (Test-Path $exePath) { [Microsoft.VisualBasic.FileIO.FileSystem]::DeleteFile($exePath, 'OnlyErrorDialogs', 'SendToRecycleBin') };"

echo.
echo Cleanup finished. Check your Recycle Bin to confirm.
pause