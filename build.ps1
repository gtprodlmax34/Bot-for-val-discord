# Rebuilds dist\SigmaMafia.exe after you change gui.py or main.py.
# Run from the project root: .\build.ps1

# --icon NONE: plain default Windows exe icon. --collect-all winrt: the
# Windows OCR bindings are split into many small modules PyInstaller can't
# find on its own.
# .venv\Scripts\python.exe -m PyInstaller --onefile --windowed --name SigmaMafia --icon NONE --collect-all winrt gui.py

# Write-Host ""
# Write-Host "Done. Exe is at dist\SigmaMafia.exe - share just that file, there's nothing to set up." -ForegroundColor Green
