param(
    [Parameter(Mandatory=$true)]
    [string]$ContentPath,
    [Parameter(Mandatory=$true)]
    [string]$OutputDir
)

$ErrorActionPreference = "Stop"
Add-Type -AssemblyName System.Drawing

function Rgb([int]$R, [int]$G, [int]$B) {
    return [System.Drawing.Color]::FromArgb($R, $G, $B)
}

function New-RoundPath([System.Drawing.RectangleF]$Rect, [float]$Radius) {
    $path = New-Object System.Drawing.Drawing2D.GraphicsPath
    $d = $Radius * 2
    $path.AddArc($Rect.X, $Rect.Y, $d, $d, 180, 90)
    $path.AddArc($Rect.Right - $d, $Rect.Y, $d, $d, 270, 90)
    $path.AddArc($Rect.Right - $d, $Rect.Bottom - $d, $d, $d, 0, 90)
    $path.AddArc($Rect.X, $Rect.Bottom - $d, $d, $d, 90, 90)
    $path.CloseFigure()
    return $path
}

function Draw-Box($G, [string]$Text, [float]$X, [float]$Y, [float]$W, [float]$H, [System.Drawing.Color]$Fill, [System.Drawing.Color]$Line, [float]$FontSize, [bool]$Bold, [string]$Align = "Center") {
    $xf = [float]$X
    $yf = [float]$Y
    $wf = [float]$W
    $hf = [float]$H
    $rect = [System.Drawing.RectangleF]::new($xf, $yf, $wf, $hf)
    $path = New-RoundPath $rect 18
    $fillBrush = New-Object System.Drawing.SolidBrush($Fill)
    $pen = New-Object System.Drawing.Pen($Line, 2)
    $G.FillPath($fillBrush, $path)
    $G.DrawPath($pen, $path)

    $style = [System.Drawing.FontStyle]::Regular
    if ($Bold) { $style = [System.Drawing.FontStyle]::Bold }
    $font = New-Object System.Drawing.Font("Microsoft YaHei", $FontSize, $style)
    $textBrush = New-Object System.Drawing.SolidBrush((Rgb 28 39 56))
    $sf = New-Object System.Drawing.StringFormat
    $sf.LineAlignment = [System.Drawing.StringAlignment]::Center
    if ($Align -eq "Left") {
        $sf.Alignment = [System.Drawing.StringAlignment]::Near
    } else {
        $sf.Alignment = [System.Drawing.StringAlignment]::Center
    }
    $sf.Trimming = [System.Drawing.StringTrimming]::EllipsisWord
    $textRect = [System.Drawing.RectangleF]::new(($xf + 14), ($yf + 8), ($wf - 28), ($hf - 16))
    $G.DrawString($Text, $font, $textBrush, $textRect, $sf)

    $sf.Dispose()
    $textBrush.Dispose()
    $font.Dispose()
    $pen.Dispose()
    $fillBrush.Dispose()
    $path.Dispose()
}

function Draw-Text($G, [string]$Text, [float]$X, [float]$Y, [float]$W, [float]$H, [float]$FontSize, [bool]$Bold, [System.Drawing.Color]$Color, [string]$Align = "Center") {
    $xf = [float]$X
    $yf = [float]$Y
    $wf = [float]$W
    $hf = [float]$H
    $style = [System.Drawing.FontStyle]::Regular
    if ($Bold) { $style = [System.Drawing.FontStyle]::Bold }
    $font = New-Object System.Drawing.Font("Microsoft YaHei", $FontSize, $style)
    $brush = New-Object System.Drawing.SolidBrush($Color)
    $sf = New-Object System.Drawing.StringFormat
    if ($Align -eq "Left") {
        $sf.Alignment = [System.Drawing.StringAlignment]::Near
    } else {
        $sf.Alignment = [System.Drawing.StringAlignment]::Center
    }
    $sf.LineAlignment = [System.Drawing.StringAlignment]::Center
    $rect = [System.Drawing.RectangleF]::new($xf, $yf, $wf, $hf)
    $G.DrawString($Text, $font, $brush, $rect, $sf)
    $sf.Dispose()
    $brush.Dispose()
    $font.Dispose()
}

function Draw-Arrow($G, [float]$X1, [float]$Y1, [float]$X2, [float]$Y2, [System.Drawing.Color]$Color) {
    $pen = New-Object System.Drawing.Pen($Color, 3)
    $cap = New-Object System.Drawing.Drawing2D.AdjustableArrowCap(6, 6)
    $pen.CustomEndCap = $cap
    $G.DrawLine($pen, $X1, $Y1, $X2, $Y2)
    $cap.Dispose()
    $pen.Dispose()
}

function New-Canvas() {
    $bmp = New-Object System.Drawing.Bitmap(1280, 720)
    $g = [System.Drawing.Graphics]::FromImage($bmp)
    $g.SmoothingMode = [System.Drawing.Drawing2D.SmoothingMode]::AntiAlias
    $g.TextRenderingHint = [System.Drawing.Text.TextRenderingHint]::ClearTypeGridFit
    $g.Clear((Rgb 248 250 252))
    return @($bmp, $g)
}

New-Item -ItemType Directory -Force -Path $OutputDir | Out-Null
$content = ConvertFrom-Json ([System.IO.File]::ReadAllText($ContentPath, [System.Text.Encoding]::UTF8))

$ink = Rgb 15 23 42
$muted = Rgb 71 85 105
$line = Rgb 148 163 184
$white = Rgb 255 255 255
$blue = Rgb 219 234 254
$blueLine = Rgb 59 130 246
$green = Rgb 220 252 231
$greenLine = Rgb 34 197 94
$amber = Rgb 254 243 199
$amberLine = Rgb 245 158 11
$purple = Rgb 237 233 254
$purpleLine = Rgb 139 92 246
$rose = Rgb 255 228 230
$roseLine = Rgb 244 63 94
$cyan = Rgb 207 250 254
$cyanLine = Rgb 6 182 212
$slate = Rgb 241 245 249

# Workflow diagram.
$canvas = New-Canvas
$bmp = $canvas[0]
$g = $canvas[1]
Draw-Text -G $g -Text "RiskPilot AI-Native Exploit Review Workflow" -X 60 -Y 30 -W 1160 -H 44 -FontSize 26 -Bold $true -Color $ink
Draw-Text -G $g -Text "From on-chain evidence to explainable vulnerability report" -X 60 -Y 72 -W 1160 -H 30 -FontSize 14 -Bold $false -Color $muted

$fills = @($blue, $green, $amber, $purple, $cyan, $rose)
$lines = @($blueLine, $greenLine, $amberLine, $purpleLine, $cyanLine, $roseLine)
$x = 45
for ($i = 0; $i -lt $content.workflow_boxes.Count; $i++) {
    $boxText = [string]($content.workflow_boxes[$i])
    $boxFill = $fills[$i]
    $boxLine = $lines[$i]
    Draw-Box -G $g -Text $boxText -X $x -Y 190 -W 180 -H 116 -Fill $boxFill -Line $boxLine -FontSize 14 -Bold $true
    if ($i -lt $content.workflow_boxes.Count - 1) {
        Draw-Arrow -G $g -X1 ($x + 184) -Y1 248 -X2 ($x + 197) -Y2 248 -Color $line
    }
    $x += 202
}

Draw-Box -G $g -Text "Stable Demo Cache`npersisted tasks, logs and reports" -X 120 -Y 410 -W 285 -H 95 -Fill $slate -Line $line -FontSize 15 -Bold $true
Draw-Box -G $g -Text "Evidence Grounding`ntrace / source / storage" -X 497 -Y 410 -W 285 -H 95 -Fill $slate -Line $line -FontSize 15 -Bold $true
Draw-Box -G $g -Text "Review and Export`nreport, audit view, JSON/Markdown" -X 874 -Y 410 -W 285 -H 95 -Fill $slate -Line $line -FontSize 15 -Bold $true
Draw-Text -G $g -Text "Key idea: AI plans and explains; tools verify facts; persisted evidence makes demos reproducible." -X 100 -Y 570 -W 1080 -H 38 -FontSize 16 -Bold $false -Color $muted

$workflowPath = Join-Path $OutputDir "riskpilot_workflow.png"
$bmp.Save($workflowPath, [System.Drawing.Imaging.ImageFormat]::Png)
$g.Dispose()
$bmp.Dispose()

# Architecture diagram.
$canvas = New-Canvas
$bmp = $canvas[0]
$g = $canvas[1]
Draw-Text -G $g -Text "RiskPilot System Architecture" -X 60 -Y 30 -W 1160 -H 44 -FontSize 26 -Bold $true -Color $ink
Draw-Text -G $g -Text "Frontend experience, task orchestration, agent reasoning, deterministic tools and persistent evidence" -X 60 -Y 72 -W 1160 -H 30 -FontSize 14 -Bold $false -Color $muted

$layerFills = @($blue, $green, $purple, $amber, $cyan)
$layerLines = @($blueLine, $greenLine, $purpleLine, $amberLine, $cyanLine)
for ($i = 0; $i -lt $content.architecture_layers.Count; $i++) {
    $layer = $content.architecture_layers[$i]
    $layerTitle = [string]$layer.title
    $layerItems = [string]$layer.items
    $y = 126 + ($i * 101)
    $layerFill = $layerFills[$i]
    $layerLine = $layerLines[$i]
    $softLine = Rgb 203 213 225
    Draw-Box -G $g -Text $layerTitle -X 70 -Y $y -W 185 -H 76 -Fill $layerFill -Line $layerLine -FontSize 18 -Bold $true
    Draw-Box -G $g -Text $layerItems -X 285 -Y $y -W 915 -H 76 -Fill $white -Line $softLine -FontSize 15 -Bold $false -Align "Left"
    if ($i -lt $content.architecture_layers.Count - 1) {
        Draw-Arrow -G $g -X1 640 -Y1 ($y + 78) -X2 640 -Y2 ($y + 99) -Color $line
    }
}
Draw-Text -G $g -Text "AI Native Core: task planning -> tool-grounded evidence -> explainable report -> audit feedback" -X 100 -Y 650 -W 1080 -H 35 -FontSize 15 -Bold $false -Color $muted

$archPath = Join-Path $OutputDir "riskpilot_architecture.png"
$bmp.Save($archPath, [System.Drawing.Imaging.ImageFormat]::Png)
$g.Dispose()
$bmp.Dispose()

Write-Output $workflowPath
Write-Output $archPath
