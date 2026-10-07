@echo off
setlocal
echo Video Slicer - one-time setup
echo ==============================
echo.
echo Installing ffmpeg via winget - this may take a minute or two...
echo.
winget install --id Gyan.FFmpeg -e --accept-source-agreements --accept-package-agreements

if errorlevel 1 (
    echo.
    echo Could not install ffmpeg automatically. This is usually because
    echo "winget" ^(Windows Package Manager^) isn't set up on this PC yet.
    echo winget comes with Windows 11 and most updated Windows 10 systems,
    echo via the free "App Installer" from the Microsoft Store.
    echo.
    echo Opening the Microsoft Store page for it now - install it, then
    echo re-run this file.
    start ms-windows-store://pdp/?ProductId=9NBLGGH4NNS1
    echo.
    pause
    exit /b 1
)

echo.
echo ============================================================
echo Done! If this is the very first time you've used winget to
echo install something, Windows sometimes needs you to sign out
echo and back in (or restart) before new programs are found by
echo other apps. Video Slicer also looks in ffmpeg's usual
echo install folder on its own, so it will likely work right away
echo without that - just try opening "Video Slicer.exe" next.
echo ============================================================
echo.
pause
