param(
  [Parameter(Mandatory = $true)][string]$InputVideo,
  [Parameter(Mandatory = $true)][string]$OutputVideo,
  [string]$Voice = 'Microsoft Hazel Desktop',
  [double]$Tempo = 1.15
)
$ErrorActionPreference = 'Stop'

$outputDir = Split-Path -Parent $OutputVideo
$audio = Join-Path $outputDir 'narration.wav'
$fastAudio = Join-Path $outputDir 'narration-fast.wav'
$text = @'
Welcome to TradeCheck, a portfolio adviser built for Binance Agent OS.
This demonstration uses live Spot market data and current financial news, while all funds remain simulated.
The dashboard begins with a one hundred twenty-five USDT paper wallet and protects a one hundred USDT reserve.
First, the adviser displays a sample assessment with its evidence, risks, counterarguments, and conditions that could change the conclusion.
The live price comes through a reviewed Binance Agent OS Spot operation. News links and timestamps are shown so the evidence can be checked.
Now we try a forty USDT purchase. The server blocks it because it would breach the protected reserve.
We revise the request to twenty USDT. The preview shows quantity, fees, market checks, and the balance after the trade.
Approval is a separate human action. Once approved, the paper fill is recorded atomically and cannot be duplicated by pressing approve again.
The activity view connects the request and approval to holdings and the portfolio ledger.
Reports provide daily and monthly summaries with fees, buys, sells, cost basis, and coverage notes.
A private schedule can publish reports while the local backend is running, with safe retry and duplicate protection.
This is a paper workflow. No real order, withdrawal, or transfer is submitted. Live model reasoning can be enabled through local model setup.
'@

Add-Type -AssemblyName System.Speech
$synth = New-Object System.Speech.Synthesis.SpeechSynthesizer
$synth.Rate = 0
$synth.Volume = 92
$installedVoice = $synth.GetInstalledVoices() | Where-Object { $_.VoiceInfo.Name -eq $Voice } | Select-Object -First 1
if (-not $installedVoice) { $installedVoice = $synth.GetInstalledVoices() | Where-Object { $_.VoiceInfo.Culture.Name -like 'en-*' } | Select-Object -First 1 }
if ($installedVoice) { $synth.SelectVoice($installedVoice.VoiceInfo.Name) }
$synth.SetOutputToWaveFile($audio)
$synth.Speak($text)
$synth.Dispose()

if ($Tempo -lt 0.5 -or $Tempo -gt 2.0) { throw 'Tempo must be between 0.5 and 2.0.' }
& ffmpeg -y -loglevel error -i $audio -filter:a "atempo=$Tempo" $fastAudio
if ($LASTEXITCODE -ne 0) { throw 'Could not adjust narration speed.' }
& ffmpeg -y -loglevel error -i $InputVideo -i $fastAudio -map 0:v:0 -map 1:a:0 -c:v copy -c:a aac -b:a 128k -af apad -t 120 -movflags +faststart $OutputVideo
if ($LASTEXITCODE -ne 0) { throw 'Could not mux narration into the demo.' }
Remove-Item -LiteralPath $audio -Force
Remove-Item -LiteralPath $fastAudio -Force
Write-Output "Saved narrated demo: $OutputVideo"
