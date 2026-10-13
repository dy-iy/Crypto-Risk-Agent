param(
    [Parameter(Mandatory=$true)]
    [string]$DocPath,
    [Parameter(Mandatory=$true)]
    [string]$ContentPath,
    [Parameter(Mandatory=$true)]
    [string]$WorkflowImage,
    [Parameter(Mandatory=$true)]
    [string]$ArchitectureImage
)

$ErrorActionPreference = "Stop"

function To-WordText([string]$Text) {
    if ($null -eq $Text) { return "" }
    return ($Text -replace "`n", "`r")
}

function Set-CellText($Table, [int]$Row, [int]$Col, [string]$Text, [double]$FontSize = 10.5, [bool]$Bold = $false) {
    $cell = $Table.Cell($Row, $Col)
    $range = $cell.Range
    $range.End = $range.End - 1
    $range.Text = To-WordText $Text
    $cell.Range.Font.NameFarEast = "Microsoft YaHei"
    $cell.Range.Font.Name = "Microsoft YaHei"
    $cell.Range.Font.Size = $FontSize
    $cell.Range.Font.Bold = $Bold
    $cell.Range.ParagraphFormat.LineSpacingRule = 0
    $cell.Range.ParagraphFormat.SpaceAfter = 3
}

function Append-Text($Cell, [string]$Text, [double]$FontSize = 10.5) {
    $range = $Cell.Range
    $range.End = $range.End - 1
    $range.Collapse(0)
    $range.InsertAfter("`r" + (To-WordText $Text))
    $Cell.Range.Font.NameFarEast = "Microsoft YaHei"
    $Cell.Range.Font.Name = "Microsoft YaHei"
    $Cell.Range.Font.Size = $FontSize
    $Cell.Range.ParagraphFormat.LineSpacingRule = 0
    $Cell.Range.ParagraphFormat.SpaceAfter = 3
}

function Append-Image($Doc, $Cell, [string]$ImagePath, [string]$Caption) {
    $range = $Cell.Range
    $range.End = $range.End - 1
    $range.Collapse(0)
    $range.InsertAfter("`r")
    $range = $Cell.Range
    $range.End = $range.End - 1
    $range.Collapse(0)
    $shape = $Doc.InlineShapes.AddPicture($ImagePath, $false, $true, $range)
    $shape.LockAspectRatio = $true
    if ($shape.Width -gt 440) {
        $shape.Width = 440
    }
    $shape.Range.ParagraphFormat.Alignment = 1

    $range = $shape.Range
    $range.Collapse(0)
    $range.InsertAfter("`r" + $Caption + "`r")
    $Cell.Range.Font.NameFarEast = "Microsoft YaHei"
    $Cell.Range.Font.Name = "Microsoft YaHei"
    $Cell.Range.Font.Size = 10
}

$content = ConvertFrom-Json ([System.IO.File]::ReadAllText($ContentPath, [System.Text.Encoding]::UTF8))
$docFullPath = [System.IO.Path]::GetFullPath($DocPath)
$backupPath = [System.IO.Path]::Combine(
    [System.IO.Path]::GetDirectoryName($docFullPath),
    ([System.IO.Path]::GetFileNameWithoutExtension($docFullPath) + ".before_riskpilot_opt_" + (Get-Date -Format "yyyyMMdd_HHmmss") + [System.IO.Path]::GetExtension($docFullPath))
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

    if ($doc.Tables.Count -lt 1) {
        throw "No table found in target document."
    }
    $table = $doc.Tables.Item(1)
    $table.Range.Font.NameFarEast = "Microsoft YaHei"
    $table.Range.Font.Name = "Microsoft YaHei"

    Set-CellText -Table $table -Row 1 -Col 2 -Text ([string]$content.work_name) -FontSize 12 -Bold $true
    Set-CellText -Table $table -Row 13 -Col 1 -Text (([string]$content.intro_title) + "`n" + ([string]$content.intro)) -FontSize 10.5 -Bold $false
    Set-CellText -Table $table -Row 14 -Col 1 -Text (([string]$content.usage_title) + "`n" + ([string]$content.usage)) -FontSize 10.5 -Bold $false
    Set-CellText -Table $table -Row 15 -Col 1 -Text (([string]$content.effects_title) + "`n" + ([string]$content.effects)) -FontSize 10.5 -Bold $false

    Set-CellText -Table $table -Row 16 -Col 1 -Text (([string]$content.design_title) + "`n" + ([string]$content.design_intro)) -FontSize 10.5 -Bold $false
    $designCell = $table.Cell(16, 1)
    Append-Image -Doc $doc -Cell $designCell -ImagePath ([System.IO.Path]::GetFullPath($WorkflowImage)) -Caption ([string]$content.workflow_caption)
    Append-Text -Cell $designCell -Text ([string]$content.design_after_workflow) -FontSize 10.5
    Append-Image -Doc $doc -Cell $designCell -ImagePath ([System.IO.Path]::GetFullPath($ArchitectureImage)) -Caption ([string]$content.architecture_caption)
    Append-Text -Cell $designCell -Text ([string]$content.design_after_arch) -FontSize 10.5

    Set-CellText -Table $table -Row 17 -Col 1 -Text (([string]$content.difficulty_title) + "`n" + ([string]$content.difficulty)) -FontSize 10.5 -Bold $false
    Set-CellText -Table $table -Row 18 -Col 1 -Text (([string]$content.teacher_review_title) + "`n" + ([string]$content.teacher_review)) -FontSize 10.5 -Bold $false

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
