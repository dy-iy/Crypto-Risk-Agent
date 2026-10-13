param(
    [Parameter(Mandatory=$true)]
    [string]$Path
)

$ErrorActionPreference = "Stop"

function Clean-Text([string]$Text) {
    if ($null -eq $Text) { return "" }
    return ($Text -replace "[`r`a]", "" -replace "\s+", " ").Trim()
}

$word = $null
$doc = $null
try {
    $word = New-Object -ComObject Word.Application
    $word.Visible = $false
    $doc = $word.Documents.Open($Path, $false, $true)

    Write-Output "FILE: $Path"
    Write-Output "PARAGRAPHS:"
    for ($i = 1; $i -le $doc.Paragraphs.Count; $i++) {
        $text = Clean-Text $doc.Paragraphs.Item($i).Range.Text
        if ($text.Length -gt 0) {
            Write-Output ("P{0}: {1}" -f $i, $text)
        }
    }

    Write-Output ""
    Write-Output "TABLES:"
    for ($t = 1; $t -le $doc.Tables.Count; $t++) {
        $table = $doc.Tables.Item($t)
        Write-Output ("TABLE {0}: rows={1}, cols={2}" -f $t, $table.Rows.Count, $table.Columns.Count)
        for ($r = 1; $r -le $table.Rows.Count; $r++) {
            $cells = @()
            for ($c = 1; $c -le $table.Columns.Count; $c++) {
                try {
                    $cellText = Clean-Text $table.Cell($r, $c).Range.Text
                    $cells += ("[{0},{1}] {2}" -f $r, $c, $cellText)
                } catch {
                    $cells += ("[{0},{1}] <merged>" -f $r, $c)
                }
            }
            Write-Output ($cells -join " | ")
        }
    }
}
finally {
    if ($doc -ne $null) {
        $doc.Close($false) | Out-Null
    }
    if ($word -ne $null) {
        $word.Quit() | Out-Null
    }
}
