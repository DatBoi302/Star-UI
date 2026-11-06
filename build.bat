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

echo ----------------------------------------------------
echo  Compiling %FILENAME%... try not to break anything.
echo ----------------------------------------------------

:: The actual compile command.
:: --onefile: bundles it all up. 
:: --clean: clears the pyinstaller cache.
pyinstaller --onefile --noconsole --icon=Star_UI_Icon.ico --clean "%FULLPATH%"

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
:: If you like keeping useless .spec files, delete this section.
if exist "build" rmdir /s /q "build"
if exist "%FILENAME%.spec" del /q "%FILENAME%.spec"

echo.
echo  Done. Your .exe is in the /dist folder.
echo ----------------------------------------------------
pause