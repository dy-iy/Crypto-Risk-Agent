param(
    [Parameter(Mandatory=$true)]
    [string]$ContentPath,
    [Parameter(Mandatory=$true)]
    [string]$OutputDir
)

$ErrorActionPreference = "Stop"

function Ole-Rgb([int]$R, [int]$G, [int]$B) {
    return $R + ($G * 256) + ($B * 65536)
}

function Set-ShapeText($Shape, [string]$Text, [int]$Size, [bool]$Bold, [int]$Color) {
    $Shape.TextFrame.TextRange.Text = ($Text -replace "`n", "`r")
    $Shape.TextFrame.TextRange.Font.Name = "Microsoft YaHei"
    $Shape.TextFrame.TextRange.Font.NameFarEast = "Microsoft YaHei"
    $Shape.TextFrame.TextRange.Font.Size = $Size
    $Shape.TextFrame.TextRange.Font.Bold = $Bold
    $Shape.TextFrame.TextRange.Font.Color.RGB = $Color
    $Shape.TextFrame.MarginLeft = 10
    $Shape.TextFrame.MarginRight = 10
    $Shape.TextFrame.MarginTop = 6
    $Shape.TextFrame.MarginBottom = 6
    $Shape.TextFrame.TextRange.ParagraphFormat.Alignment = 2
    $Shape.TextFrame.VerticalAnchor = 3
}

function Add-Box($Slide, [string]$Text, [double]$X, [double]$Y, [double]$W, [double]$H, [int]$Fill, [int]$Line, [int]$FontSize, [bool]$Bold) {
    $shape = $Slide.Shapes.AddShape(5, $X, $Y, $W, $H)
    $shape.Fill.ForeColor.RGB = $Fill
    $shape.Line.ForeColor.RGB = $Line
    $shape.Line.Weight = 1.2
    Set-ShapeText $shape $Text $FontSize $Bold (Ole-Rgb 28 39 56)
    return $shape
}

function Add-Text($Slide, [string]$Text, [double]$X, [double]$Y, [double]$W, [double]$H, [int]$Size, [bool]$Bold, [int]$Color) {
    $shape = $Slide.Shapes.AddTextbox(1, $X, $Y, $W, $H)
    $shape.Fill.Visible = 0
    $shape.Line.Visible = 0
    Set-ShapeText $shape $Text $Size $Bold $Color
    return $shape
}

New-Item -ItemType Directory -Force -Path $OutputDir | Out-Null
$content = ConvertFrom-Json ([System.IO.File]::ReadAllText($ContentPath, [System.Text.Encoding]::UTF8))

$ppt = $null
$presentation = $null
try {
    $ppt = New-Object -ComObject PowerPoint.Application
    $ppt.Visible = 1
    $presentation = $ppt.Presentations.Add()
    $presentation.PageSetup.SlideWidth = 1280
    $presentation.PageSetup.SlideHeight = 720

    $bg = Ole-Rgb 248 250 252
    $ink = Ole-Rgb 15 23 42
    $muted = Ole-Rgb 71 85 105
    $blue = Ole-Rgb 219 234 254
    $blueLine = Ole-Rgb 59 130 246
    $green = Ole-Rgb 220 252 231
    $greenLine = Ole-Rgb 34 197 94
    $amber = Ole-Rgb 254 243 199
    $amberLine = Ole-Rgb 245 158 11
    $purple = Ole-Rgb 237 233 254
    $purpleLine = Ole-Rgb 139 92 246
    $rose = Ole-Rgb 255 228 230
    $roseLine = Ole-Rgb 244 63 94
    $cyan = Ole-Rgb 207 250 254
    $cyanLine = Ole-Rgb 6 182 212

    # Workflow diagram.
    $slide = $presentation.Slides.Add(1, 12)
    $slide.Background.Fill.ForeColor.RGB = $bg
    Add-Text $slide "RiskPilot AI-Native Exploit Review Workflow" 60 32 1160 42 26 $true $ink | Out-Null
    Add-Text $slide "From on-chain evidence to explainable vulnerability report" 60 74 1160 30 14 $false $muted | Out-Null

    $fills = @($blue, $green, $amber, $purple, $cyan, $rose)
    $lines = @($blueLine, $greenLine, $amberLine, $purpleLine, $cyanLine, $roseLine)
    $x = 55
    for ($i = 0; $i -lt $content.workflow_boxes.Count; $i++) {
        Add-Box $slide $content.workflow_boxes[$i] $x 190 170 116 $fills[$i] $lines[$i] 15 $true | Out-Null
        if ($i -lt $content.workflow_boxes.Count - 1) {
            Add-Text $slide ">" ($x + 174) 225 28 42 24 $true $muted | Out-Null
        }
        $x += 202
    }

    Add-Box $slide "Stable Demo Cache`ncompleted tasks, persisted logs, reports" 120 410 285 95 (Ole-Rgb 241 245 249) (Ole-Rgb 148 163 184) 15 $true | Out-Null
    Add-Box $slide "Evidence-Bound Reasoning`ntrace nodes, source, events, storage" 497 410 285 95 (Ole-Rgb 241 245 249) (Ole-Rgb 148 163 184) 15 $true | Out-Null
    Add-Box $slide "Review and Export`nstructured report, audit view, JSON/Markdown" 874 410 285 95 (Ole-Rgb 241 245 249) (Ole-Rgb 148 163 184) 15 $true | Out-Null
    Add-Text $slide "Key idea: AI plans and explains; tools verify facts; persisted evidence makes demos reproducible." 100 570 1080 38 16 $false $muted | Out-Null

    $workflowPath = Join-Path $OutputDir "riskpilot_workflow.png"
    $slide.Export($workflowPath, "PNG", 1280, 720)

    # Architecture diagram.
    $slide2 = $presentation.Slides.Add(2, 12)
    $slide2.Background.Fill.ForeColor.RGB = $bg
    Add-Text $slide2 "RiskPilot System Architecture" 60 32 1160 42 26 $true $ink | Out-Null
    Add-Text $slide2 "Frontend experience, task orchestration, agent reasoning, deterministic tools and persistent evidence" 60 74 1160 30 14 $false $muted | Out-Null

    $layerFills = @($blue, $green, $purple, $amber, $cyan)
    $layerLines = @($blueLine, $greenLine, $purpleLine, $amberLine, $cyanLine)
    for ($i = 0; $i -lt $content.architecture_layers.Count; $i++) {
        $layer = $content.architecture_layers[$i]
        $y = 126 + ($i * 101)
        Add-Box $slide2 $layer.title 70 $y 185 76 $layerFills[$i] $layerLines[$i] 18 $true | Out-Null
        Add-Box $slide2 $layer.items 285 $y 915 76 (Ole-Rgb 255 255 255) (Ole-Rgb 203 213 225) 15 $false | Out-Null
        if ($i -lt $content.architecture_layers.Count - 1) {
            Add-Text $slide2 "v" 620 ($y + 72) 40 28 18 $true $muted | Out-Null
        }
    }

    Add-Text $slide2 "AI Native Core: task planning -> tool-grounded evidence -> explainable report -> audit feedback" 100 650 1080 35 15 $false $muted | Out-Null
    $archPath = Join-Path $OutputDir "riskpilot_architecture.png"
    $slide2.Export($archPath, "PNG", 1280, 720)

    Write-Output $workflowPath
    Write-Output $archPath
}
finally {
    if ($presentation -ne $null) {
        $presentation.Close()
    }
    if ($ppt -ne $null) {
        $ppt.Quit()
    }
}
