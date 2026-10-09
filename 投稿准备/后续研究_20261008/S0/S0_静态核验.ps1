param([switch]$RequireReview)
$ErrorActionPreference = 'Stop'
$base = $PSScriptRoot
$workspace = (Resolve-Path -LiteralPath (Join-Path $base '../../..')).Path
function ReadJson([string]$path) { Get-Content -LiteralPath $path -Raw -Encoding utf8 | ConvertFrom-Json -AsHashtable }
function Hash([string]$path) { (Get-FileHash -LiteralPath $path -Algorithm SHA256).Hash.ToLowerInvariant() }
$checks = [System.Collections.Generic.List[object]]::new()
function Check([string]$name,[bool]$ok,$detail) {
    $checks.Add([ordered]@{name=$name;pass=$ok;detail=$detail})
}
$config = ReadJson (Join-Path $base 'S0_preregistration.json')
$planAssets = ReadJson (Join-Path $workspace '投稿准备/后续研究_20261008/方案来源与冻结边界.json')
$oldStart = ReadJson (Join-Path $workspace '投稿准备/adaptive_poolhbi/final_experiments/experiment_manifest_start.json')
$R6 = ReadJson (Join-Path $workspace '投稿准备/adaptive_poolhbi/FINAL_CONFIG_R6.json')
$bindings = [System.Collections.Generic.List[object]]::new()
function Bind([string]$role,[string]$path,$expected) {
    $resolved = (Resolve-Path -LiteralPath $path).Path
    $actual = Hash $resolved
    $matched = if($null -eq $expected) { $null } else { $actual -eq $expected }
    $bindings.Add([ordered]@{role=$role;path=$resolved;bytes=(Get-Item -LiteralPath $resolved).Length;sha256=$actual;expected_sha256=$expected;matches_expected=$matched})
    if($null -ne $expected) { Check ("hash:"+$role) $matched $resolved }
}
foreach($item in $planAssets.sources) { Bind $item.role $item.path $item.sha256 }
Bind 'prior_roadmap' $planAssets.plan.path $planAssets.plan.sha256
foreach($key in $R6.source_sha256.Keys) { Bind ('frozen_source:'+$key) (Join-Path $workspace ('投稿准备/adaptive_poolhbi/final/'+$key)) $R6.source_sha256[$key] }
Bind 'historical_unified_binary' (Join-Path $workspace '投稿准备/adaptive_poolhbi/final_experiments/unified_driver.exe') 'cc494d3253fa3513f24d173bcb66230b582916c8db43d88c33369f19e596d1a6'
Bind 'legacy_pool' (Join-Path $workspace '投稿准备/adaptive_poolhbi/final_experiments/legacy/pool_index.hpp') '710202ee8396ac899d11cf3e3945ab5d630d8d86d3651cd7cec0da93bba45774'
Bind 'legacy_generators' (Join-Path $workspace '投稿准备/adaptive_poolhbi/final_experiments/legacy/generators.hpp') '954cc8e923911926f1a689ba3eac2afd30c71351b87220713a62659d9730d6a6'
$horizonStart = ReadJson (Join-Path $workspace '投稿准备/adaptive_poolhbi/supplementary_20261007/horizon/manifest_start.json')
$driverPath = (Resolve-Path -LiteralPath (Join-Path $workspace '投稿准备/adaptive_poolhbi/final_experiments/driver_core.hpp')).Path
Bind 'driver_core_current_frozen_horizon' $driverPath $horizonStart.frozen_assets[$driverPath]
Check 'driver_core_has_horizon_anchor' ($null -ne $horizonStart.frozen_assets[$driverPath]) $driverPath
Bind 'driver_core_historical_snapshot' (Join-Path $workspace '投稿准备/adaptive_poolhbi/final_experiments/driver_pre_review_green/driver_core.hpp') 'e6cf584bdea6100dcfebd1cef68dbce41f85fc7ead36d137741d379eed140bc0'
Bind 'wall_driver' (Join-Path $workspace '投稿准备/adaptive_poolhbi/final_experiments/wall_driver.hpp') 'ca2bc88e7e891605d352531c0054c8f00d76b2e1ddef9940143bad275546aa03'
$cachePath = (Resolve-Path -LiteralPath (Join-Path $workspace '投稿准备/adaptive_poolhbi/final_experiments/trace_cache.hpp')).Path
Bind 'trace_cache_current_frozen_horizon' $cachePath $horizonStart.frozen_assets[$cachePath]
Check 'trace_cache_has_horizon_anchor' ($null -ne $horizonStart.frozen_assets[$cachePath]) $cachePath
Bind 'horizon_frozen_source_manifest' (Join-Path $workspace '投稿准备/adaptive_poolhbi/supplementary_20261007/horizon/manifest_start.json') $null
Bind 'dataset_January' $config.dataset.path $config.dataset.sha256
foreach($key in @('executable','frontend')) {
    $item = $oldStart.machine_audit.compiler[$key]
    Bind ('compiler:'+$key) $item.path $item.sha256
}
foreach($key in $oldStart.machine_audit.legacy_wall_tools.Keys) {
    $item = $oldStart.machine_audit.legacy_wall_tools[$key]
    foreach($part in @('source','binary','interpreter')) {
        if($item.Contains($part) -and $null -ne $item[$part]) {
            if($part -eq 'interpreter') {
                Bind ('S0_runtime_current:'+$key) $item[$part].path $config.environment.pair_python_sha256
            } else { Bind ('tool:'+$key+':'+$part) $item[$part].path $item[$part].sha256 }
        }
    }
}
$historicalFiles = @(
'投稿准备/adaptive_poolhbi/final_experiments/protocol.json',
'投稿准备/adaptive_poolhbi/final_experiments/mechanism_protocol.json',
'投稿准备/adaptive_poolhbi/final_experiments/observer_protocol.json',
'投稿准备/adaptive_poolhbi/final_experiments/C_phase_observation_registration_v3.json',
'投稿准备/adaptive_poolhbi/supplementary_20261007/horizon/protocol.json',
'投稿准备/adaptive_poolhbi/supplementary_20261007/bucket/protocol_candidate.json',
'投稿准备/adaptive_poolhbi/supplementary_20261007/bucket/aa_protocol_candidate.json'
)
function ExtractSeed($node,[bool]$inside,[System.Collections.Generic.HashSet[long]]$set) {
    if($null -eq $node) { return }
    if($node -is [System.Collections.IDictionary]) {
        foreach($key in $node.Keys) { ExtractSeed $node[$key] ($inside -or ($key -match 'seed')) $set }
    } elseif(($node -is [System.Collections.IEnumerable]) -and ($node -isnot [string])) {
        foreach($value in $node) { ExtractSeed $value $inside $set }
    } elseif($inside -and ($node -is [long] -or $node -is [int] -or $node -is [uint64])) {
        [void]$set.Add([long]$node)
    }
}
$historical = [System.Collections.Generic.HashSet[long]]::new()
$seedScope = @()
foreach($rel in $historicalFiles) {
    $path = Join-Path $workspace $rel
    $values = [System.Collections.Generic.HashSet[long]]::new()
    ExtractSeed (ReadJson $path) $false $values
    foreach($n in $values) { [void]$historical.Add($n) }
    $seedScope += [ordered]@{path=$path;sha256=(Hash $path);seeds=@($values | Sort-Object)}
    Bind ('seed_scope:'+$rel) $path $null
}
$newSeeds = @()
foreach($key in $config.seeds.Keys) { $newSeeds += @($config.seeds[$key]) }
$intersection = @($newSeeds | Where-Object { $historical.Contains([long]$_) })
Check 'seed_sets_pairwise_disjoint' (@($newSeeds | Sort-Object -Unique).Count -eq $newSeeds.Count) $config.seeds
Check 'seed_sets_historical_scope_disjoint' ($intersection.Count -eq 0) $intersection
Check 'schema_and_stage' ($config.schema -eq 'adaptive_poolhbi.S0.preregistration.v1' -and $config.stage -eq 'S0') $config.status
Check 'methods_cases_pairs' ($config.methods.Count -eq 7 -and $config.final_cases.Count -eq 7 -and $config.dev_cases.Count -eq 10 -and $config.primary_pairs.Count -eq 8) $true
$counts = [ordered]@{
dev_inputs = $config.dev_cases.Count*$config.seeds.dev.Count
dev_timing_children = $config.dev_cases.Count*$config.seeds.dev.Count*($config.dev_selection.event_candidates.Count+$config.dev_selection.fixed_candidates.Count)*4
dev_aa_children = $config.aa.dev.methods.Count*$config.aa.dev.cases.Count*$config.aa.dev.timepoints.Count*$config.aa.children_per_profile
primary_pairs = $config.final_cases.Count*$config.seeds.final.Count*$config.primary_pairs.Count
primary_timing_children = $config.final_cases.Count*$config.seeds.final.Count*$config.primary_pairs.Count*4
diagnostic_timing_children = $config.final_cases.Count*$config.seeds.final.Count*$config.diagnostic_pairs.Count*4
final_aa_children = $config.aa.final.methods.Count*$config.aa.final.cases.Count*$config.aa.final.timepoints.Count*$config.aa.children_per_profile
mechanism_runs = $config.seeds.mechanism.Count*6
latency_runs = $config.final_cases.Count*$config.seeds.final.Count*$config.methods.Count
resource_runs = $config.final_cases.Count*$config.seeds.final.Count*$config.methods.Count
cpu_profile_attempts = $config.diagnostics.cpu_profile.cases.Count
}
$counts.total_timing_children = $counts.dev_timing_children+$counts.dev_aa_children+$counts.primary_timing_children+$counts.diagnostic_timing_children+$counts.final_aa_children
foreach($key in $counts.Keys) { Check ('matrix:'+ $key) ($counts[$key] -eq $config.planned_counts[$key]) $counts[$key] }
foreach($case in $config.final_cases) {
    Check ('API:'+ $case.id) ($case.api_calls -eq 2*$case.U+$case.queries) $case.api_calls
    if($case.Contains('q')) {
        $q = if($case.q -gt 0) { [math]::Floor($case.U/$case.q) } else { 0 }
        Check ('queries:'+ $case.id) ($case.queries -eq $q) $q
    }
}
$f04 = $config.final_cases | Where-Object { $_.id -eq 'F04' }
$phaseQueries = 0
for($i=0;$i -lt $f04.phase_lengths.Count;$i++) { $phaseQueries += [math]::Floor($f04.phase_lengths[$i]/$f04.phase_q[$i]) }
Check 'F04_phase_units' (($f04.phase_lengths | Measure-Object -Sum).Sum -eq $f04.U) $f04.phase_lengths
Check 'F04_phase_queries' ($phaseQueries -eq $f04.queries) $phaseQueries
Check 'confirmatory_family_42' ($config.statistics.confirmatory_family_size -eq $config.statistics.confirmatory_pairs.Count*$config.final_cases.Count*$config.statistics.confirmatory_components.Count) $config.statistics.confirmatory_family_size
Check 'selected_thresholds_absent' ($null -eq $config.dev_selection.selected_theta -and $null -eq $config.dev_selection.selected_h -and $config.dev_selection.status -eq 'NOT_RUN') $config.dev_selection.status
foreach($key in $config.execution.Keys) { Check ('no_execution:'+ $key) ($config.execution[$key] -eq 0) $config.execution[$key] }
Check 'S1_gates_false' (!$config.gate.S1_DEV_READY -and !$config.gate.S1_FINAL_READY) $config.gate
$fp = $R6.fingerprint.parameters
foreach($p in @('epoch_size','min_tree_size','tree_budget','down_idle_epochs','cooldown_epochs','payback','max_convert_records','scan_ns_per_work','conversion_base_ns','conversion_ns_per_record')) {
    Check ('R6_param:'+ $p) ($config.freeze.R6[$p] -eq $fp[$p]) $fp[$p]
}
$coverage = @(Import-Csv -LiteralPath (Join-Path $base 'S0_测试与指标覆盖矩阵.csv'))
Check 'coverage_24_unique' ($coverage.Count -eq 24 -and @($coverage.id | Sort-Object -Unique).Count -eq 24) $coverage.id
Check 'coverage_NOT_RUN' (@($coverage | Where-Object { $_.status -ne 'NOT_WRITTEN_NOT_RUN' }).Count -eq 0) $true
Check 'native_account_macros_off' ($config.environment.native_forbidden_macros -contains 'INDEX_MEMORY' -and $config.environment.native_forbidden_macros -contains 'INDEX_FAILURE_TEST' -and $config.environment.mode_macros.native.account_values -eq 'NA') $config.environment.mode_macros.native
Check 'latency_account_macros_off' ($config.environment.mode_macros.latency.forbidden -contains 'INDEX_MEMORY' -and $config.environment.mode_macros.latency.forbidden -contains 'ADAPTIVE_ALLOC_TRACK') $config.environment.mode_macros.latency
Check 'resource_account_macros_on' ($config.environment.mode_macros.resource.enabled -contains 'INDEX_MEMORY' -and $config.environment.mode_macros.resource.enabled -contains 'ADAPTIVE_ALLOC_TRACK' -and $config.environment.mode_macros.resource.forbidden -contains 'INDEX_FAILURE_TEST') $config.environment.mode_macros.resource
Check 'statistics_explicit_log_endpoint_fast' ($config.statistics.strong_fast.Contains('log_ci_upper') -and $config.statistics.strong_fast.Contains('component_AA_log_floor')) $config.statistics.strong_fast
Check 'statistics_explicit_log_endpoint_slow' ($config.statistics.strong_slow.Contains('log_ci_lower') -and $config.statistics.strong_slow.Contains('component_AA_log_floor')) $config.statistics.strong_slow
Check 'statistics_explicit_ratio_endpoint_reporting' ($config.statistics.ratio_ci_lower -eq 'exp(log_ci_lower)' -and $config.statistics.ratio_ci_upper -eq 'exp(log_ci_upper)' -and $config.statistics.AA_floor_scale -eq 'log_ratio') $true
$normative = @('S0_同布局比较合约_v1.md','S0_实验预注册_v1.md','S0_preregistration.json','S0_测试与指标覆盖矩阵.csv','S0_审计与范围裁决.md')
$reviews = @(Get-ChildItem -LiteralPath $base -File -Filter 'S0_独立审查_round*.md' | Sort-Object { [int]($_.BaseName -replace '^S0_独立审查_round','') })
$reviewPassed = $false
if($reviews.Count -gt 0) {
    $latest = $reviews[-1]
    $review = Get-Content -LiteralPath $latest.FullName -Raw
    $reviewPassed = $review -match '(?im)^\*{0,2}Status:?\*{0,2}\s*(Approved/freezable|Approved / freezable)'
    Check 'independent_review_status' $reviewPassed $latest.FullName
    foreach($file in $normative) {
        Check ('review_current_hash:'+ $file) ($review.ToLowerInvariant().Contains((Hash (Join-Path $base $file)))) $file
    }
}
if($RequireReview) { Check 'independent_review_required' $reviewPassed $true }
$ownFiles = @($normative)+@('S0_入口清单.md','S0_静态核验.ps1')
foreach($file in $ownFiles) { Bind ('S0_asset:'+ $file) (Join-Path $base $file) $null }
foreach($file in $reviews) { Bind 'independent_review' $file.FullName $null }
foreach($file in $normative) { Bind ('round1_review_input:'+ $file) (Join-Path $base ('audit/round1_input/'+$file)) $null }
Bind 'initial_static_failed_record' (Join-Path $base 'audit/S0_核验记录_initial_FAILED.json') $null
Bind 'initial_static_failed_assets' (Join-Path $base 'audit/S0_资产清单_initial_FAILED.json') $null
Bind 'pre_round2_old_review_rejection' (Join-Path $base 'audit/S0_核验记录_pre_round2_FAIL_old_review.json') $null
$failures = @($checks | Where-Object { !$_.pass })
$passed = $failures.Count -eq 0
$manifest = [ordered]@{
schema='adaptive_poolhbi.S0.assets.v1'; registration_date='2026-10-08'; checked_at=(Get-Date).ToString('o')
scope='S0 design and preregistration only'
status=if($passed -and $reviewPassed) { 'S0_SPEC_FREEZABLE' } elseif($passed) { 'STATIC_PASS_REVIEW_PENDING' } else { 'STATIC_CHECK_FAILED' }
bindings=$bindings; historical_seed_scope=$seedScope; historical_unique_seeds=@($historical | Sort-Object)
runtime_change=[ordered]@{old_path=$oldStart.machine_audit.legacy_wall_tools.bench_pinned_pair.interpreter.path;old_sha256=$oldStart.machine_audit.legacy_wall_tools.bench_pinned_pair.interpreter.sha256;current_sha256=$config.environment.pair_python_sha256;old_hash_reused=$false;current_interpreter_executed=$false;live_S1_environment_verified=$false}
new_seed_sets=$config.seeds; seed_intersection=$intersection
new_algorithm_implementation_files=0; benchmark_processes_launched=0
S1_DEV_READY=$false; S1_FINAL_READY=$false
}
$manifestPath = Join-Path $base 'S0_资产清单.json'
$manifest | ConvertTo-Json -Depth 24 | Set-Content -LiteralPath $manifestPath -Encoding utf8
$verification = [ordered]@{
schema='adaptive_poolhbi.S0.static_verification.v1'; checked_at=(Get-Date).ToString('o')
status=if($passed) { 'PASS' } else { 'FAIL' }
scope='hash/schema/matrix/seed/review checks only, not algorithm tests'
manifest_path=$manifestPath; manifest_sha256=(Hash $manifestPath)
checks=$checks; failed_checks=$failures; failed_count=$failures.Count; check_count=$checks.Count
planned_counts=$counts; independent_review_passed=$reviewPassed
S0_SPEC_FREEZABLE=($passed -and $reviewPassed); S1_DEV_READY=$false; S1_FINAL_READY=$false
experiment_or_algorithm_test_processes_launched=0
}
$verification | ConvertTo-Json -Depth 24 | Set-Content -LiteralPath (Join-Path $base 'S0_核验记录.json') -Encoding utf8
[ordered]@{status=$verification.status;check_count=$checks.Count;failed_count=$failures.Count;failed_checks=$failures;S0_SPEC_FREEZABLE=$verification.S0_SPEC_FREEZABLE;S1_DEV_READY=$false;S1_FINAL_READY=$false;timing_children_planned=$counts.total_timing_children;timing_children_run=0} | ConvertTo-Json -Depth 6
if(!$passed) { exit 1 }
