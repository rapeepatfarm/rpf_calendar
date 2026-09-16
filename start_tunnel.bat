@echo off
REM ============================================================
REM  Open the Cloudflare quick tunnel for RPF Calendar.
REM
REM  All logic and Thai messages live in scripts\tunnel.py --
REM  cmd.exe garbles Thai text stored inside a .bat file because
REM  it reads the file using the system OEM codepage (874), not
REM  UTF-8.  Python can force UTF-8 output, so the text is safe
REM  there.  Keep this wrapper in English only.
REM
REM    start_tunnel.bat            open (reuse if already open)
REM    start_tunnel.bat restart    close then open, gives a NEW url
REM    start_tunnel.bat stop       close the tunnel
REM ============================================================
chcp 65001 >nul
cd /d %~dp0
python scripts\tunnel.py %1
echo.
pause
