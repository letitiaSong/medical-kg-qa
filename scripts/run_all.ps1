# 一键跑通离线全流程（不需要 TuGraph / API Key）
# 用法：在项目根目录执行  pwsh -File scripts\run_all.ps1
$ErrorActionPreference = "Stop"
$env:PYTHONIOENCODING = "utf-8"

$py = "python"
if ($args.Count -ge 1) { $py = $args[0] }

$steps = @(
    @{ Name = "环境自检";       Cmd = "scripts/00_check_env.py" },
    @{ Name = "清洗 + 抽取";    Cmd = "scripts/01_preprocess.py" },
    @{ Name = "构图 + 入图";    Cmd = "scripts/02_build_graph.py --mock" },
    @{ Name = "入图验证";       Cmd = "scripts/03_verify_graph.py --mock" },
    @{ Name = "生成测试集";     Cmd = "scripts/build_testset.py" },
    @{ Name = "评测对比";       Cmd = "scripts/05_evaluate.py --mock" },
    @{ Name = "批量问答";       Cmd = "scripts/04_ask.py --mock --fake" },
    @{ Name = "问答演示";       Cmd = "cli.py --mock --llm fake --demo" }
)

$index = 0
foreach ($step in $steps) {
    $index++
    Write-Host ""
    Write-Host ("=" * 70) -ForegroundColor DarkGray
    Write-Host ("[{0}/{1}] {2}" -f $index, $steps.Count, $step.Name) -ForegroundColor Cyan
    Write-Host ("=" * 70) -ForegroundColor DarkGray
    $parts = $step.Cmd -split " "
    $scriptPath = $parts[0]
    $scriptArgs = @()
    if ($parts.Length -gt 1) { $scriptArgs = $parts[1..($parts.Length - 1)] }
    & $py $scriptPath @scriptArgs
    if ($LASTEXITCODE -ne 0) {
        Write-Host ("步骤失败：{0}（退出码 {1}）" -f $step.Name, $LASTEXITCODE) -ForegroundColor Red
        exit $LASTEXITCODE
    }
}

Write-Host ""
Write-Host "全部完成。产物在 outputs/ 与 data/graph/，报告见 docs/实验报告.docx" -ForegroundColor Green