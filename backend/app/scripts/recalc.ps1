param (
    [string]$FilePath
)

$excel = New-Object -ComObject Excel.Application
$excel.Visible = $false
$excel.DisplayAlerts = $false
$excel.ScreenUpdating = $false
$excel.EnableEvents = $false

try {
    Write-Host "Opening: $FilePath"
    $wb = $excel.Workbooks.Open($FilePath)
    Write-Host "Running full calculation..."
    $excel.CalculateFull()
    Write-Host "Saving..."
    $wb.Save()
    $wb.Close($false)
    Write-Host "Success!"
} catch {
    Write-Host "Error during calculation: $_"
} finally {
    $excel.Quit()
    [System.Runtime.Interopservices.Marshal]::ReleaseComObject($excel) | Out-Null
    [System.GC]::Collect()
    [System.GC]::WaitForPendingFinalizers()
}
