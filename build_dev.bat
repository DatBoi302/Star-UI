@echo off
:: Check if you actually dragged a file onto the script
if "%~1"=="" (
    echo You have to drag and drop your Python script onto this .bat file, genius.
    echo I can't compile thin air.
    pause
    goto :eof
)

:: Set the filename variable so we don't have to type it
set "FILENAME=%~n1"
set "FULLPATH=%~1"
set "DEST_DIR=%~dp0"

echo ----------------------------------------------------
echo  Compiling %FILENAME%... try not to break anything.
echo ----------------------------------------------------

:: The actual compile command.
pyinstaller --onefile --icon=Star_UI_Icon.ico --clean "%FULLPATH%"

:: Check if it actually worked
if %ERRORLEVEL% NEQ 0 (
    echo.
    echo ----------------------------------------------------
    echo  It failed. Read the red text above.
    echo ----------------------------------------------------
    pause
    goto :eof
)

echo.
echo ----------------------------------------------------
echo  Build successful. Cleaning up the mess...
echo ----------------------------------------------------

:: Cleanup the artifacts. 
if exist "build" rmdir /s /q "build"
if exist "%FILENAME%.spec" del /q "%FILENAME%.spec"

:: Check for naming conflicts and move
if exist "dist\%FILENAME%.exe" (
    if exist "%DEST_DIR%%FILENAME%.exe" (
        :: If a conflict exists, append a unique timestamp (HHMMSS) to the new file
        set "TIMESTAMP=%time:~0,2%%time:~3,2%%time:~6,2%"
        set "TIMESTAMP=%TIMESTAMP: =0%"
        echo  Conflict detected! Renaming new build to %FILENAME%_%TIMESTAMP%.exe
        move /y "dist\%FILENAME%.exe" "%DEST_DIR%%FILENAME%_%TIMESTAMP%.exe" >nul
    ) else (
        move /y "dist\%FILENAME%.exe" "%DEST_DIR%" >nul
    )
    :: Clean up the now-empty dist folder
    rmdir /s /q "dist"
)

echo.
echo  Done. Your .exe is ready in the main folder.
echo ----------------------------------------------------
pause