# Rebuilds dist\SigmaMafia.exe after you change gui.py or main.py.
# Run from the project root: .\build.ps1

.venv\Scripts\python.exe -m PyInstaller --onefile --windowed --name SigmaMafia --icon icon.ico --add-data "icon.ico;." gui.py

Write-Host ""
Write-Host "Done. Exe is at dist\SigmaMafia.exe" -ForegroundColor Green
Write-Host "Copy templates\ next to it (or run capture_templates.py again) before running it."
