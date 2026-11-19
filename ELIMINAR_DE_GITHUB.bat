@echo off
setlocal
cd /d "%~dp0"
where git >nul 2>nul
if errorlevel 1 (
  echo Git no esta instalado. https://git-scm.com/download/win
  pause
  exit /b 1
)
set /p REPO=URL del repositorio (https://github.com/USUARIO/REPO.git): 
set "BR=main"
set /p BR=Rama [main]: 
if not defined BR set "BR=main"

if not exist ".git" git init -q
git remote remove origin >nul 2>nul
git remote add origin %REPO%
git fetch origin
if errorlevel 1 (
  echo No se pudo leer el repositorio. Revisa la URL y tu inicio de sesion.
  pause
  exit /b 1
)
git symbolic-ref HEAD refs/heads/%BR%
git reset -q origin/%BR%
if errorlevel 1 (
  echo La rama %BR% no existe en el repositorio.
  pause
  exit /b 1
)

echo.
echo ===== Archivos de compilacion o pesados que hay AHORA en GitHub =====
git ls-files | findstr /i /r "\.exe$ \.dll$ \.pyd$ \.spec$ \.zip$ ^dist/ ^build/ glass-venv build-venv \.dist/ \.build/ \.venv/"
echo ======================================================================
echo (Si no sale nada, GitHub ya esta limpio. Revisa que la rama sea la correcta.)
echo.

:loop
set "DEL="
set /p DEL=Ruta o carpeta a eliminar de GitHub (ej: dist  o  SSTool+.exe). Enter para terminar: 
if not defined DEL goto :commit
git rm -r --cached -- "%DEL%"
goto :loop

:commit
git diff --cached --quiet
if not errorlevel 1 (
  echo No marcaste nada para borrar. No se sube ningun cambio.
  pause
  exit /b 0
)
git status --short
git commit -m "Quita archivos de compilacion del repositorio"
git push origin %BR%
if errorlevel 1 (
  echo No se pudo subir. Prueba: git pull --rebase origin %BR%  y repite.
  pause
  exit /b 1
)
echo Listo: eliminado de GitHub. Tus archivos locales no se tocaron.
pause
