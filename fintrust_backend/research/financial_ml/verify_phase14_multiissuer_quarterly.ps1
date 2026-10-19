$ErrorActionPreference = 'Stop'
python -m unittest discover -s tests -p 'test_financial_ml_phase14_multiissuer_quarterly_cohort.py' -v
if ($LASTEXITCODE -ne 0) { throw 'Phase14 tests failed' }
$root = (git rev-parse --show-toplevel).Trim()
$data = Join-Path (Join-Path (Split-Path $root -Parent) 'Financial-Risk-Alert-System') 'fintrust_backend\data\financial_ml'
$cohort = Join-Path $data 'finmind_scaled_120\finmind_scaled_cohort.csv'
$out = Join-Path $data 'phase14_multiissuer_quarterly_comparison'
python -m research.financial_ml.phase14_multiissuer_quarterly_cohort --cohort-csv $cohort --output $out --execute
if ($LASTEXITCODE -ne 0) { throw 'Phase14 source acquisition failed' }
Get-Content (Join-Path $out 'phase14_integrated_report.json') -Raw -Encoding UTF8
