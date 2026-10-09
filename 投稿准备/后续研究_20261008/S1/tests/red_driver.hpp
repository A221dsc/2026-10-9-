#pragma once
// Tests-only compiled negative shim. Deliberately plausible wrong behavior.
#include "../../../adaptive_poolhbi/final_experiments/driver_core.hpp"
#include <map>
namespace s1 {
using udriver::Record;using udriver::Bundle;
struct Expected{std::uint64_t api_ordinal=0;std::vector<Record> records;};
struct Fixture{Bundle bundle;std::vector<Expected> expected;};
inline Fixture synthetic_fixture(const std::string& c,unsigned seed){Fixture f;auto& b=f.bundle;b.domain={UINT64_C(1)<<40,4096};b.request.seed=seed;b.request.initial=8192;b.request.units=4096;b.request.days=0;b.query_period=4097;for(std::uint64_t i=1;i<=8192;++i)b.whole.initial.push_back({i,i});b.whole.final=b.whole.initial;std::mt19937_64 rng(seed);for(std::size_t i=0;i<4096;++i){auto n=2048+rng()%4097;udriver::Step st;st.erased=n;st.added={n,n};if(c=="F07"){st.query=true;st.lo=6144;st.hi=6153;st.expected_count=9;++b.whole.queries;b.whole.returned+=9;f.expected.push_back({3*(i+1),{}});}b.whole.steps.push_back(st);}return f;}
struct WorkProfile{std::uint64_t positive_events=8192,work=100000,api_calls=8192;};inline WorkProfile work_profile(const Bundle&){return {};}
inline bool prefix_clock_check(const Bundle&){return false;}
inline std::vector<Record> load_public_verified(){return {};}
inline Fixture public_fixture(const std::string&,unsigned){Fixture f;auto& b=f.bundle;b.request.initial=b.request.units=262144;for(int j=0;j<3;++j){udriver::PhaseSegment s;s.begin=j*87381;s.end=(j+1)*87381;b.segments.push_back(s);}return f;}
inline bool cache_roundtrip(const Fixture&,const std::string&){return false;}
inline Fixture engineering_fixture(std::size_t,std::size_t){return {};}
struct PhaseTime{std::uint64_t online_ns=1;};
struct NativeResult{std::uint64_t build_ns=1,online_ns=1,destroy_ns=1,total_ns=1,lifecycle_ns=1;std::vector<PhaseTime> phases{{}};std::vector<std::string> boundaries;std::string work="0";std::array<std::string,4> accounts{{"0","0","0","0"}};bool verified=false;};
inline NativeResult native_engineering(const Bundle&,const std::string&){NativeResult r;
#if defined(DRIVER_RED_CLOCK)||defined(DRIVER_RED_MACROS)
 r.total_ns=2;r.lifecycle_ns=3;r.work="NA";r.accounts={"NA","NA","NA","NA"};r.verified=true;
#ifdef DRIVER_RED_MACROS
 r.boundaries={"construct_build","initial_values","phase_online_hash_output_release","final_values","counters","destroy"};
#endif
#endif
 return r;}
inline std::vector<std::string> registered_methods(){return {"R6"};}
struct ModeContract{bool native_forbidden=false,latency_only_trace=false,resource_three_macros=false;};inline ModeContract mode_contract(){return {};}
struct MechanismEvidence{std::size_t budget=32,idle=4,cooldown=8,epoch=512,minimum=128,no_idle_scheduled=0,no_idle_cleanup=0;bool old_hot_nonempty=false,reached_budget=false,budget_stall=false,idle_recovery=false,B_promoted=false,A_return_repromoted=false,exact=false;};inline MechanismEvidence mechanism_engineering(){return {};}
struct DiagnosticEvidence{std::size_t samples=0,promotions=0,scheduled=0,cleanup=0;double p50=0,p95=0,p99=0,maximum=0;bool production_diagnostic_trajectory=false,events_complete=false,latency_accounts_na=false,original_accounts_na=false,resource_samples=false,dedup=false,output_released=false,every_conversion_snapshot=false,owner_zero=false,whole_peak_simultaneous=false,pause_ancestry_frees=false;};inline DiagnosticEvidence diagnostic_engineering(const std::string& =""){DiagnosticEvidence d;
#ifdef DRIVER_RED_EVENTS
 d.production_diagnostic_trajectory=true;d.samples=1;d.p50=d.p95=d.p99=d.maximum=1;
#endif
 return d;}
}
