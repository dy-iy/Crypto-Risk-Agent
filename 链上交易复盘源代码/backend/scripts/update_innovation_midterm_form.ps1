param(
    [Parameter(Mandatory=$true)]
    [string]$DocPath,
    [Parameter(Mandatory=$true)]
    [string]$ContentPath
)

$ErrorActionPreference = "Stop"

function To-WordText([string]$Text) {
    if ($null -eq $Text) { return "" }
    return ($Text -replace "`n", "`r")
}

function Set-CellText($Table, [int]$Row, [int]$Col, [string]$Text, [double]$FontSize = 10.5) {
    $cell = $Table.Cell($Row, $Col)
    $range = $cell.Range
    $range.End = $range.End - 1
    $range.Text = To-WordText $Text
    $cell.Range.Font.NameFarEast = "Microsoft YaHei"
    $cell.Range.Font.Name = "Microsoft YaHei"
    $cell.Range.Font.Size = $FontSize
    $cell.Range.ParagraphFormat.LineSpacingRule = 0
    $cell.Range.ParagraphFormat.SpaceAfter = 3
}

$content = ConvertFrom-Json ([System.IO.File]::ReadAllText($ContentPath, [System.Text.Encoding]::UTF8))
$docFullPath = [System.IO.Path]::GetFullPath($DocPath)
$backupPath = [System.IO.Path]::Combine(
    [System.IO.Path]::GetDirectoryName($docFullPath),
    ([System.IO.Path]::GetFileNameWithoutExtension($docFullPath) + ".before_midterm_fill_" + (Get-Date -Format "yyyyMMdd_HHmmss") + [System.IO.Path]::GetExtension($docFullPath))
)
Copy-Item -LiteralPath $docFullPath -Destination $backupPath -Force

$word = $null
$doc = $null
try {
    $word = New-Object -ComObject Word.Application
    $word.Visible = $false
    $word.DisplayAlerts = 0
    $doc = $word.Documents.Open($docFullPath, $false, $false)
    $doc.TrackRevisions = $false

    if ($doc.Tables.Count -lt 2) {
        throw "The target document does not contain the midterm content table."
    }

    $midTable = $doc.Tables.Item(2)
    Set-CellText -Table $midTable -Row 1 -Col 1 -Text ([string]$content.midterm_content) -FontSize 10.5

    $doc.Content.Font.NameFarEast = "Microsoft YaHei"
    $doc.Content.Font.Name = "Microsoft YaHei"
    $doc.Save()
    Write-Output ("updated=" + $docFullPath)
    Write-Output ("backup=" + $backupPath)
}
finally {
    if ($doc -ne $null) {
        $doc.Close($true) | Out-Null
    }
    if ($word -ne $null) {
        $word.Quit() | Out-Null
    }
}
