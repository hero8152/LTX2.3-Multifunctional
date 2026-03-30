$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path

# Find shortcut in LTX_Shortcut folder
$shortcut = Get-ChildItem -Path "$scriptDir\LTX_Shortcut" -Filter "*.lnk" | Select-Object -First 1

if (-not $shortcut) {
    Write-Host "[!] No shortcut found in LTX_Shortcut folder"
    Write-Host "Please put LTX Desktop shortcut in LTX_Shortcut folder"
    exit 1
}

Write-Host "     Found: $($shortcut.Name)"

# Get target path from shortcut
$shell = New-Object -ComObject WScript.Shell
$shortcutObj = $shell.CreateShortcut($shortcut.FullName)
$targetPath = $shortcutObj.TargetPath

# Remove \LTX Desktop.exe from end
$ltxDir = $targetPath -replace '\\LTX Desktop\.exe$', ''

if (-not $ltxDir) {
    Write-Host "[!] Could not read shortcut target"
    exit 1
}

Write-Host "     LTX Dir: $ltxDir"

$policyFile = Join-Path $ltxDir "resources\backend\runtime_config\runtime_policy.py"

if (Test-Path $policyFile) {
    Write-Host "     Found: $policyFile"
    
    $content = Get-Content $policyFile -Raw
    $content = $content -replace [regex]::Escape('vram_gb < 31'), 'vram_gb < 6'
    Set-Content -Path $policyFile -Value $content
    
    Write-Host "     ^_^ VRAM threshold changed to 6GB"
} else {
    Write-Host "[!] runtime_policy.py not found"
    Write-Host "     Expected: $policyFile"
    exit 1
}
