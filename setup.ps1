# Setup script for Finance Automation Project
Write-Host "--- Finance Automation Setup ---" -ForegroundColor Cyan

# 1. Check for Virtual Environment
if (!(Test-Path "venv")) {
    Write-Host "Error: Virtual environment not found. Please ensure the venv folder is included." -ForegroundColor Red
    exit
}

Write-Host "Virtual environment found." -ForegroundColor Green

# 3. Install Requirements
Write-Host "Installing dependencies..." -ForegroundColor Yellow
.\venv\Scripts\python.exe -m pip install --upgrade pip
.\venv\Scripts\pip.exe install -r requirements.txt

# 4. Handle .env file
if (!(Test-Path ".env")) {
    Write-Host "Creating .env file from template..." -ForegroundColor Yellow
    Copy-Item ".env.example" ".env"
    
    $apiKey = Read-Host "Enter your Gemini API Key (or press Enter to skip)"
    if ($apiKey) {
        $content = Get-Content ".env"
        $content = $content -replace "GEMINI_API_KEY=your_api_key_here", "GEMINI_API_KEY=$apiKey"
        Set-Content ".env" $content
    }
}

Write-Host "`nSetup complete! You can now run 'start.bat' to launch the app." -ForegroundColor Cyan
