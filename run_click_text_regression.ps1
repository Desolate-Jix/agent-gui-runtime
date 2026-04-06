$ErrorActionPreference = 'Stop'
Set-Location 'D:\ai agent framework'

$serviceUrl = 'http://127.0.0.1:8000'
$targetText = 'HELLO OCR TEST'
$roi = @{ x = 0; y = 0; width = 900; height = 260 }
$logsDir = Join-Path (Get-Location) 'logs'
New-Item -ItemType Directory -Force -Path $logsDir | Out-Null
$timestamp = Get-Date -Format 'yyyyMMdd-HHmmss'
$resultPath = Join-Path $logsDir ("click-text-regression-$timestamp.json")

function Write-Artifact {
  param([object]$Payload)
  $Payload | ConvertTo-Json -Depth 100 | Set-Content -Encoding UTF8 $resultPath
}

function Fail-And-Exit {
  param(
    [string]$Reason,
    [int]$Code = 1,
    [object]$Artifact = $null
  )

  if ($null -eq $Artifact) {
    $Artifact = [ordered]@{
      ok = $false
      reason = $Reason
      result_path = $resultPath
      timestamp = (Get-Date).ToString('o')
    }
  }
  else {
    $Artifact.ok = $false
    $Artifact.reason = $Reason
    $Artifact.result_path = $resultPath
    $Artifact.timestamp = (Get-Date).ToString('o')
  }

  Write-Artifact -Payload $Artifact
  Write-Output ("FAIL: " + $Reason)
  Write-Output ("Saved result: " + $resultPath)
  exit $Code
}

function Invoke-JsonPost {
  param(
    [string]$Uri,
    [object]$BodyObject,
    [string]$EndpointName,
    [hashtable]$Artifact
  )

  try {
    $body = $BodyObject | ConvertTo-Json -Depth 20
    $response = Invoke-WebRequest -UseBasicParsing -Method POST -Uri $Uri -ContentType 'application/json' -Body $body
    return ($response.Content | ConvertFrom-Json)
  }
  catch {
    $Artifact.endpoint_failure = @{ endpoint = $EndpointName; uri = $Uri; message = $_.Exception.Message }
    Fail-And-Exit -Reason ("Endpoint failed: " + $EndpointName + " :: " + $_.Exception.Message) -Artifact $Artifact
  }
}

$artifact = [ordered]@{
  ok = $null
  reason = $null
  timestamp = (Get-Date).ToString('o')
  service = $serviceUrl
  target_text = $targetText
  roi = $roi
}

# 1. Health check
try {
  $health = (Invoke-WebRequest -UseBasicParsing "$serviceUrl/health").Content | ConvertFrom-Json
  $artifact.health = $health
}
catch {
  $artifact.endpoint_failure = @{ endpoint = '/health'; uri = "$serviceUrl/health"; message = $_.Exception.Message }
  Fail-And-Exit -Reason ("Service health check failed: " + $_.Exception.Message) -Artifact $artifact
}

if (-not $health.success) {
  Fail-And-Exit -Reason 'Service returned unhealthy response' -Artifact $artifact
}

# 2. Prepare controlled Notepad baseline
try {
  $baselineRaw = & powershell.exe -NoProfile -ExecutionPolicy Bypass -File 'D:\ai agent framework\tmp_notepad_click_text_baseline.ps1'
  $baseline = $baselineRaw | ConvertFrom-Json
  $artifact.baseline = $baseline
}
catch {
  Fail-And-Exit -Reason ("Baseline preparation failed: " + $_.Exception.Message) -Artifact $artifact
}

# 3. Bind Notepad
$bindResponse = Invoke-JsonPost -Uri "$serviceUrl/session/bind_window" -BodyObject @{ process_name = 'notepad.exe' } -EndpointName '/session/bind_window' -Artifact $artifact
$artifact.bind = $bindResponse
if (-not $bindResponse.success) {
  Fail-And-Exit -Reason 'Bind window failed' -Artifact $artifact
}

# 4. Call click_text baseline with validation enabled
$clickBody = @{
  text = $targetText
  roi = $roi
  partial_match = $true
  enable_validation = $true
}
$clickResponse = Invoke-JsonPost -Uri "$serviceUrl/action/click_text" -BodyObject $clickBody -EndpointName '/action/click_text' -Artifact $artifact
$artifact.click_text = $clickResponse

if (-not $clickResponse.success) {
  Fail-And-Exit -Reason 'click_text returned success=false' -Artifact $artifact
}

$result = $clickResponse.data.result
if (-not $result) {
  Fail-And-Exit -Reason 'click_text response missing data.result' -Artifact $artifact
}

$clickInfo = $result.click
$verification = $result.verification
$diff = $verification.diff
$matchStrategy = [string]$result.match_strategy
$matchedText = [string]$result.matched_text
$clicked = ($null -ne $clickInfo -and $null -ne $clickInfo.clicked -and [bool]$clickInfo.clicked)
$verified = ($null -ne $verification -and $null -ne $verification.verified -and [bool]$verification.verified)
$cursorMoved = ($null -ne $verification -and $null -ne $verification.cursor_moved -and [bool]$verification.cursor_moved)
$foregroundConsistent = ($null -ne $verification -and $null -ne $verification.foreground_consistent -and [bool]$verification.foreground_consistent)
$diffAvailable = ($null -ne $diff -and $null -ne $diff.available -and [bool]$diff.available)
$diffChanged = ($null -ne $diff -and $null -ne $diff.changed -and [bool]$diff.changed)
$diffCount = if ($null -ne $diff -and $null -ne $diff.count) { [int]$diff.count } else { -1 }

$artifact.assertions = [ordered]@{
  success = $clickResponse.success
  match_strategy = $matchStrategy
  matched_text_non_empty = -not [string]::IsNullOrWhiteSpace($matchedText)
  clicked = $clicked
  verification_verified = $verified
  verification_cursor_moved = $cursorMoved
  verification_foreground_consistent = $foregroundConsistent
  verification_diff_available = $diffAvailable
  verification_diff_changed = $diffChanged
  verification_diff_count = $diffCount
  screen_point_present = ($null -ne $clickInfo -and $null -ne $clickInfo.screen_point)
  image_path_present = -not [string]::IsNullOrWhiteSpace([string]$result.image_path)
}

if ($clickResponse.success -ne $true) {
  Fail-And-Exit -Reason 'Assertion failed: success != true' -Artifact $artifact
}
if ($matchStrategy -notin @('exact', 'normalized_exact')) {
  Fail-And-Exit -Reason ("Assertion failed: unexpected match_strategy = " + $matchStrategy) -Artifact $artifact
}
if ([string]::IsNullOrWhiteSpace($matchedText)) {
  Fail-And-Exit -Reason 'Assertion failed: matched_text is empty' -Artifact $artifact
}
if (-not $clicked) {
  Fail-And-Exit -Reason 'Assertion failed: click.clicked != true' -Artifact $artifact
}
if (-not $verified) {
  Fail-And-Exit -Reason 'Assertion failed: verification.verified != true' -Artifact $artifact
}
if (-not $cursorMoved) {
  Fail-And-Exit -Reason 'Assertion failed: verification.cursor_moved != true' -Artifact $artifact
}
if (-not $foregroundConsistent) {
  Fail-And-Exit -Reason 'Assertion failed: verification.foreground_consistent != true' -Artifact $artifact
}
if (-not $diffAvailable) {
  Fail-And-Exit -Reason 'Assertion failed: verification.diff.available != true' -Artifact $artifact
}
if (-not $diffChanged) {
  Fail-And-Exit -Reason 'Assertion failed: verification.diff.changed != true' -Artifact $artifact
}

$artifact.ok = $true
$artifact.reason = 'PASS'
Write-Artifact -Payload $artifact
Write-Output ("PASS: click_text regression ok (strategy=" + $matchStrategy + ", matched_text='" + $matchedText + "', diff.count=" + $diffCount + ")")
Write-Output ("Saved result: " + $resultPath)
exit 0
