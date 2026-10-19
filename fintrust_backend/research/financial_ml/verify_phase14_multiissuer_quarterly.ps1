$ErrorActionPreference = 'Stop'
python -m unittest discover -s tests -p 'test_financial_ml_phase14_multiissuer_quarterly_cohort.py' -v
if ($LASTEXITCODE -ne 0) { throw 'Phase14 tests failed' }
python -m unittest discover -s tests -p 'test_financial_ml_phase13_quarterly_temporal_features.py' -v
if ($LASTEXITCODE -ne 0) { throw 'Phase13 regression failed' }
python -m unittest discover -s tests -p 'test_financial_ml_phase12_kangyou_quarterly_panel.py' -v
if ($LASTEXITCODE -ne 0) { throw 'Phase12 regression failed' }
python -m unittest discover -s tests -p 'test_financial_ml_phase1_*.py' -v
if ($LASTEXITCODE -ne 0) { throw 'Phase1 case registry failed' }
$root = (git rev-parse --show-toplevel).Trim()
if (-not $root.EndsWith('Financial-Risk-Alert-System-ML')) { throw 'Dedicated ML worktree only' }
$data = Join-Path (Join-Path (Split-Path $root -Parent) 'Financial-Risk-Alert-System') 'fintrust_backend\data\financial_ml'
$cohort = Join-Path $data 'finmind_scaled_120\finmind_scaled_cohort.csv'
$out = Join-Path $data 'phase14_multiissuer_quarterly_comparison'
if (-not (Test-Path -LiteralPath $cohort)) { throw 'Frozen 120 issuer cohort missing' }
python -m research.financial_ml.phase14_multiissuer_quarterly_cohort --cohort-csv $cohort --output $out --execute
if ($LASTEXITCODE -ne 0) { throw 'Phase14 source acquisition failed' }
Get-Content (Join-Path $out 'phase14_integrated_report.json') -Raw -Encoding UTF8
