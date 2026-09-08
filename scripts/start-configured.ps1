$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath (Join-Path $PSScriptRoot '..')
if (-not (Test-Path -LiteralPath 'data/openai.credential') -and -not $env:OPENAI_API_KEY) {
    python -m backend.setup
    if ($LASTEXITCODE -ne 0) { throw 'Model setup did not complete.' }
}
$serverArguments = @('-m', 'backend.server', '--interpreter', 'openai', '--market-data', 'binance')
if (Test-Path -LiteralPath 'data/mcp-account.json') { $serverArguments += @('--mcp-manifest', 'data/mcp-account.json') }
python @serverArguments
