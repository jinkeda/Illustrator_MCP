<#
.SYNOPSIS
    ES3 lint gate for Illustrator MCP JSX files.
.DESCRIPTION
    Scans all .jsx files under resources/scripts/ for forbidden ES6+ tokens.
    Returns exit code 0 if clean, 1 if violations found.
.EXAMPLE
    .\scripts\es3_lint.ps1
#>

$ErrorActionPreference = "Stop"

$scriptsDir = Join-Path (Join-Path (Join-Path (Join-Path $PSScriptRoot "..") "illustrator_mcp") "resources") "scripts"

if (-not (Test-Path $scriptsDir)) {
    Write-Error "Scripts directory not found: $scriptsDir"
    exit 1
}

# Forbidden patterns (regex)
$patterns = @(
    @{ Name = "const"; Regex = '\bconst\b'; Desc = "Use var instead of const" },
    @{ Name = "let"; Regex = '\blet\b'; Desc = "Use var instead of let" },
    @{ Name = "arrow"; Regex = '=>'; Desc = "Use function() instead of =>" },
    @{ Name = "Map"; Regex = '\bnew\s+Map\b'; Desc = "Use plain object instead of Map" },
    @{ Name = "Set"; Regex = '\bnew\s+Set\b'; Desc = "Use plain object instead of Set" },
    @{ Name = "for-of"; Regex = '\bfor\s*\(\s*var\s+\w+\s+of\b'; Desc = "Use indexed for loop" },
    @{ Name = "class"; Regex = '\bclass\s+\w'; Desc = "Use constructor function" }
)

$violations = [System.Collections.ArrayList]@()
$fileCount = 0

Get-ChildItem -Path $scriptsDir -Filter "*.jsx" -Recurse | ForEach-Object {
    $file = $_
    $fileCount++
    $lineNum = 0

    Get-Content $file.FullName -Encoding UTF8 | ForEach-Object {
        $lineNum++
        $line = $_

        # Skip pure comment lines (JSDoc arrow functions are OK)
        if ($line -match '^\s*(\*|//|/\*)') { return }

        foreach ($p in $patterns) {
            if ($line -match $p.Regex) {
                $null = $violations.Add([PSCustomObject]@{
                        File    = $file.Name
                        Line    = $lineNum
                        Pattern = $p.Name
                        Desc    = $p.Desc
                        Content = $line.Trim().Substring(0, [Math]::Min($line.Trim().Length, 80))
                    })
            }
        }
    }
}

Write-Host ""
Write-Host "ES3 Lint Gate - Illustrator MCP JSX" -ForegroundColor Cyan
Write-Host "Scanned $fileCount .jsx files"
Write-Host ""

if ($violations.Count -eq 0) {
    Write-Host "  PASS: No ES6+ violations found" -ForegroundColor Green
    Write-Host ""
    exit 0
}
else {
    Write-Host "  FAIL: $($violations.Count) violation(s) found" -ForegroundColor Red
    Write-Host ""
    foreach ($v in $violations) {
        Write-Host "  $($v.File):$($v.Line) [$($v.Pattern)] $($v.Desc)" -ForegroundColor Yellow
        Write-Host "    $($v.Content)" -ForegroundColor DarkGray
    }
    Write-Host ""
    exit 1
}
