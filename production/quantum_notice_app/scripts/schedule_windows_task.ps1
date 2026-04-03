param(
    [string]$TaskName = "QuantumNoticeDaily",
    [string]$StartTime = "09:00",
    [string]$PythonExe = "python",
    [string]$AppDir = "$PSScriptRoot\.."
)

$AppDir = (Resolve-Path $AppDir).Path
$ScriptPath = Join-Path $AppDir "quantum_notice_app.py"
$DbPath = Join-Path $AppDir "data\quantum_notices.json"
$EnvPath = Join-Path $AppDir ".env"

$taskCmd = "`"$PythonExe`" `"$ScriptPath`" --env-file `"$EnvPath`" --db `"$DbPath`" run"

Write-Host "[등록] 작업명: $TaskName"
Write-Host "[등록] 실행시각: 매일 $StartTime"
Write-Host "[등록] 명령: $taskCmd"

schtasks /Create /F /SC DAILY /TN $TaskName /TR $taskCmd /ST $StartTime | Out-Host

Write-Host "완료: 작업 스케줄러 등록"
