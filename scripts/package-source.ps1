$ErrorActionPreference = 'Stop'
$projectRoot = [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
$archiveDirectory = Join-Path $projectRoot 'data/submission'
New-Item -ItemType Directory -Path $archiveDirectory -Force | Out-Null
$archivePath = Join-Path $archiveDirectory ('tradecheck-source-' + (Get-Date -Format 'yyyyMMdd-HHmmss') + '.zip')
Add-Type -AssemblyName System.IO.Compression
$archive = [System.IO.Compression.ZipFile]::Open($archivePath, [System.IO.Compression.ZipArchiveMode]::Create)
try {
    $rootFiles = @('README.md', 'PLAN.md', '.gitignore', 'package.json', 'package-lock.json', 'index.html', 'vite.config.js', 'playwright.config.js')
    $sourceFiles = foreach ($folder in @('backend', 'src', 'tests', 'scripts', 'docs')) {
        Get-ChildItem -LiteralPath (Join-Path $projectRoot $folder) -Recurse -File |
            Where-Object { $_.Extension -in @('.py', '.js', '.jsx', '.mjs', '.css', '.md', '.ps1', '.html', '.json') -and $_.FullName -notmatch '[\\/]__pycache__[\\/]' }
    }
    foreach ($file in $rootFiles) { $sourceFiles += Get-Item -LiteralPath (Join-Path $projectRoot $file) }
    foreach ($file in $sourceFiles) {
        $relative = [System.IO.Path]::GetRelativePath($projectRoot, $file.FullName).Replace('\', '/')
        if ($relative.StartsWith('../')) { throw 'Source path escaped the project.' }
        [System.IO.Compression.ZipFileExtensions]::CreateEntryFromFile($archive, $file.FullName, $relative) | Out-Null
    }
} finally {
    $archive.Dispose()
}
Write-Output $archivePath
