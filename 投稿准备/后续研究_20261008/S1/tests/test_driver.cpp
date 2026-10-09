#ifdef DRIVER_RED
#include "red_driver.hpp"
#else
#include "../src/workloads.hpp"
#include "../src/native_run.hpp"
#include "../src/diagnostic_run.hpp"
#include "../src/metadata.hpp"
#endif
#include <iostream>
#include <unordered_set>
#include <cmath>
using namespace s1;
static void require(bool c,const char* m){if(!c)throw std::runtime_error(m);}
static std::vector<Record> query(const std::map<std::uint64_t,std::uint64_t>& ref,std::uint64_t lo,std::uint64_t hi){std::vector<Record> out;for(auto it=ref.lower_bound(lo);it!=ref.end()&&it->first<hi;++it)out.push_back(*it);return out;}
static void SX16(){
 auto low=synthetic_fixture("F05",94001),high=synthetic_fixture("F06",94001);
 require(low.bundle.whole.initial==high.bundle.whole.initial,"SX16 identical initial multiset");
 require(low.bundle.whole.final==low.bundle.whole.initial && high.bundle.whole.final==high.bundle.whole.initial,"SX16 restored complete multiset");
 auto l=work_profile(low.bundle),h=work_profile(high.bundle);
 std::cout<<"SX16 low_events="<<l.positive_events<<" high_events="<<h.positive_events<<" low_W="<<l.work<<" high_W="<<h.work<<" low_API="<<l.api_calls<<" high_API="<<h.api_calls<<'\n';
 require(l.positive_events==8192&&h.positive_events==8192,"SX16 equal positive event count = 2U");
 require(l.work<h.work&&l.work>0,"SX16 low work strictly below high work, both positive");
 require(l.api_calls==8192&&h.api_calls==8192,"SX16 API=2U for q0");
 require(low.bundle.query_period==4097&&low.bundle.request.days==0,"SX16 q0 cache has positive U+1 period and synthetic days0");
 std::map<std::uint64_t,std::uint64_t> lr(low.bundle.whole.initial.begin(),low.bundle.whole.initial.end()),hr(lr);
 for(std::size_t i=0;i<4096;++i){for(auto p:{std::pair<Fixture*,decltype(lr)*>{&low,&lr},{&high,&hr}}){auto& st=p.first->bundle.whole.steps[i];auto it=p.second->find(st.erased);require(it!=p.second->end(),"SX16 erase exists");auto rank=std::distance(p.second->begin(),it)+1;require(p.first==&low?(rank>=2&&rank<=8):(rank>=2048&&rank<=6144),"SX16 independently checked one-based rank interval");require(st.added==*it&&!st.query,"SX16 erase/reinsert same complete record, no query");}}
}
static void SX17(){
 auto f=synthetic_fixture("F07",94002);auto& b=f.bundle;
 std::cout<<"SX17 queries="<<b.whole.queries<<" returned="<<b.whole.returned<<" API="<<2*b.request.units+b.whole.queries<<'\n';
 require(b.whole.queries==4096&&b.whole.returned==32768,"SX17 eight complete results per query");
 require(2*b.request.units+b.whole.queries==12288,"SX17 API=2U+Q");
 std::map<std::uint64_t,std::uint64_t> ref(b.whole.initial.begin(),b.whole.initial.end());std::uint64_t ord=0;
 for(std::size_t i=0;i<b.whole.steps.size();++i){const auto& st=b.whole.steps[i];require(ref.erase(st.erased)==1,"SX17 erase actual record");ref.insert(st.added);ord+=3;
   auto start=ref.begin();std::advance(start,6143);auto stop=start;std::advance(stop,8);auto ans=query(ref,st.lo,st.hi);
   require(st.lo==start->first&&st.hi==stop->first&&ans.size()==8,"SX17 one-based rank floor(3n/4), half-open 8");
   require(f.expected[i].api_ordinal==ord&&f.expected[i].records==ans,"SX17 exact query reference and API ordinal");}
 require(prefix_clock_check(b),"SX17 range leaves epoch/ops unchanged; later structure registers candidates");
}
static void SX18(const std::string& out){
 auto f=public_fixture("F04",94001);auto& b=f.bundle;
 require(b.request.initial==262144&&b.request.units==262144,"SX18 full frozen N/U shape");
 require(b.segments.size()==3&&b.segments[0].end==87381&&b.segments[1].begin==87381&&b.segments[1].end==174762&&b.segments[2].end==262144,"SX18 unequal lengths 87381/87381/87382");
 require(b.segments[0].queries==341&&b.segments[1].queries==10922&&b.segments[2].queries==341&&b.whole.queries==11604,"SX18 phase-local q256/q8/q256 yields 11604");
 require(2*b.request.units+b.whole.queries==535892,"SX18 API=535892");
 require(b.query_period==0&&b.cancel_period==0&&!b.ordered&&b.request.days==31,"SX18 authoritative segments and public days31");
 auto physical=load_public_verified();auto sorted=physical;std::sort(sorted.begin(),sorted.end());std::mt19937_64 start_rng(UINT64_C(0x6249037adf150be1)+94001ULL*104729);
 std::uniform_int_distribution<std::uint64_t> start_d(0,sorted.size()-524288);require(start_d(start_rng)==b.whole.start,"SX18 independent start RNG");
 require(std::vector<Record>(sorted.begin()+b.whole.start,sorted.begin()+b.whole.start+262144)==b.whole.initial,"SX18 actual source identities, duplicate TIME preserved");
 std::vector<unsigned char> alive(262144,1);std::size_t oldest=0,qi=0;std::uint64_t ord=0,water=b.whole.initial.back().first/b.domain.stride;
 std::mt19937_64 cancel(UINT64_C(0x81ec39b7526a04df)^(94001ULL*104729)),shuffle(UINT64_C(0x35710df29a48b6ce)+94001ULL*130363);
 std::map<std::uint64_t,std::uint64_t> ref(b.whole.initial.begin(),b.whole.initial.end());
 for(std::size_t phase=0;phase<3;++phase){auto seg=b.segments[phase];std::vector<Record> incoming(sorted.begin()+b.whole.start+262144+seg.begin,sorted.begin()+b.whole.start+262144+seg.end);if(phase==1)std::shuffle(incoming.begin(),incoming.end(),shuffle);
  for(std::size_t local=0;local<incoming.size();++local){while(!alive[oldest])++oldest;auto pos=oldest;if(phase==1||(local+1)%256==0){std::uniform_int_distribution<std::size_t> remaining(oldest,262143);do{pos=remaining(cancel);}while(!alive[pos]);}alive[pos]=0;
   const auto& st=b.whole.steps[seg.begin+local];require(st.erased==b.whole.initial[pos].first&&st.added==incoming[local],"SX18 independent old-alive rejection and middle cohort shuffle replay");require(ref.erase(st.erased)==1,"SX18 each initial old record deleted once");require(ref.insert(st.added).second,"SX18 unique incoming identity");ord+=2;water=std::max(water,st.added.first/b.domain.stride);
   require(st.query==((local+1)%(phase==1?8:256)==0),"SX18 phase-local query counter reset");if(st.query){++ord;require(st.hi==(water+1)*b.domain.stride&&st.lo==(water+1>60?water+1-60:0)*b.domain.stride,"SX18 recent60s watermark bounds");auto ans=query(ref,st.lo,st.hi);require(f.expected[qi].api_ordinal==ord&&f.expected[qi++].records==ans,"SX18 full Records independent exact query reference");}}
 }
 require(std::vector<Record>(ref.begin(),ref.end())==b.whole.final&&std::count(alive.begin(),alive.end(),1)==0,"SX18 exact final and all U initial identities deleted");
 require(cache_roundtrip(f,out),"SX18 APHTRC01 + S0EXP001 roundtrip actual SHA identity and metadata");
#ifndef DRIVER_RED
 auto verified=verify_cache(std::filesystem::u8path(out)/"cache.bin",sha_file(std::filesystem::u8path(out)/"cache.bin"),true);require(verified.fixture.bundle.whole.hash==b.whole.hash,"SX18 actual complete metadata verification");reverify_cache(verified);
#endif
}
static void SX19(){
 auto f=engineering_fixture(128,16);auto r=native_engineering(f.bundle,"M_LIST");
 require(r.build_ns>0&&r.online_ns>0&&r.destroy_ns>0,"SX19 positive construction/build/online/destroy clocks");
 require(r.total_ns==r.build_ns+r.online_ns&&r.lifecycle_ns==r.total_ns+r.destroy_ns,"SX19 total and lifecycle arithmetic");
 require(r.phases.size()==1&&r.phases[0].online_ns==r.online_ns,"SX19 online is exact sum of fixed phase clocks");
 require(r.boundaries==std::vector<std::string>{"construct_build","initial_values","phase_online_hash_output_release","final_values","counters","destroy"},"SX19 measured body boundary order");
 require(r.work=="NA"&&r.accounts[0]=="NA"&&r.accounts[1]=="NA"&&r.accounts[2]=="NA"&&r.accounts[3]=="NA","SX19 native LIST W and four accounts NA");
 for(const auto& method:registered_methods())require(native_engineering(f.bundle,method).verified,"SX19 every method same compiled static dispatch exact contents");
 auto macros=mode_contract();require(macros.native_forbidden&&macros.latency_only_trace&&macros.resource_three_macros,"SX19 actual native/latency/resource macro classification");
}
static void SX22(){auto e=mechanism_engineering();std::cout<<"SX22 old_nonempty="<<e.old_hot_nonempty<<" K32="<<e.reached_budget<<" stall="<<e.budget_stall<<" idle="<<e.idle_recovery<<" B="<<e.B_promoted<<" A_return="<<e.A_return_repromoted<<" exact="<<e.exact<<'\n';require(e.budget==32&&e.idle==4&&e.cooldown==8&&e.epoch==512&&e.minimum==128,"SX22 actual frozen scheduler parameters");require(e.old_hot_nonempty&&e.reached_budget&&e.budget_stall,"SX22 actually reach K32 with old hot nonempty and stall");require(e.idle_recovery&&e.B_promoted&&e.A_return_repromoted,"SX22 ordinary idle recovery, B hot, idle, A re-promotion");require(e.no_idle_scheduled==0&&e.no_idle_cleanup>0,"SX22 NO_IDLE scheduled off but legal cleanup active");require(e.exact,"SX22 exact complete content each update and phase");}
static void SX24(const std::string& out){auto d=diagnostic_engineering(out+"_diagnostic");std::cout<<"SX24 samples="<<d.samples<<" promotion="<<d.promotions<<" scheduled="<<d.scheduled<<" cleanup="<<d.cleanup<<" events_complete="<<d.events_complete<<'\n';require(d.production_diagnostic_trajectory,"SX24 direct unchanged R6 vs diagnostic Cost no-tie content/counters/tree/credit trajectory");require(d.samples>0&&d.p50>0&&d.p50<=d.p95&&d.p95<=d.p99&&d.p99<=d.maximum,"SX24 full per-API samples and linear quantiles including max");require(d.promotions>0&&d.scheduled>0&&d.cleanup>0,"SX24 all three successful conversion types via legal APIs");require(d.events_complete,"SX24 event ordinal/epoch/slot/n/body_ns and containing API latency");require(d.latency_accounts_na&&d.original_accounts_na,"SX24 latency and Original four-account NA actual outputs");require(d.resource_samples&&d.dedup&&d.output_released&&d.every_conversion_snapshot,"SX24 same-run tree/bytes sampling512, phase/final dedup, released output, all conversions");require(d.owner_zero&&d.whole_peak_simultaneous&&d.pause_ancestry_frees,"SX24 production owner scope, simultaneous whole peak and paused ancestry frees");}
#ifndef DRIVER_RED
static void cache_norms(const std::string& out){auto f=registered_fixture("D01",90001,"dev");f.bundle.query_period=1; // Deliberately false aggregate q, while authoritative segment stays q0/U+1.
 auto dir=std::filesystem::u8path(out+"_negative_registered_q");write_fixture(f,dir);std::ofstream marker(dir/"engineering_negative_fixture.json");marker<<"{\"engineering_only\":true,\"intent\":\"invalid registered aggregate q; no timing experiment\"}\n";marker.close();bool rejected=false;try{auto v=verify_cache(dir/"cache.bin",sha_file(dir/"cache.bin"));(void)v;}catch(const std::exception&){rejected=true;}require(rejected,"CACHE_NORMS registered D01 q0 cannot accept aggregate q1 despite internally consistent metadata/cache");}
static void registry(const std::string& id){auto spec=case_spec(id);Fixture f;if(spec.public_data){if(id=="F04")throw std::runtime_error("F04 full shape is SX18, never scaled here");auto scaled=spec;scaled.n=512;scaled.units=256;f=public_fixture(id,94001,&scaled);}else f=make_synthetic(spec,94001,true);auto& b=f.bundle;require(f.engineering,"registry fixture marked engineering");std::map<std::uint64_t,std::uint64_t> ref(b.whole.initial.begin(),b.whole.initial.end());std::uint64_t identity=b.request.initial+1,ordinal=0;auto tag=spec.pattern=="low"?1:spec.pattern=="high"?2:spec.pattern=="prefix"?3:spec.pattern=="endpoint"?4:5;std::mt19937_64 rng(UINT64_C(0x6a09e667f3bcc909)^(94001ULL*104729)^(std::uint64_t(tag)*UINT64_C(0x9e3779b97f4a7c15)));std::size_t queries=0;
 for(std::size_t phase=0;phase<b.segments.size();++phase){auto seg=b.segments[phase];for(std::size_t unit=seg.begin;unit<seg.end;++unit){auto st=b.whole.steps[unit];auto it=ref.find(st.erased);require(it!=ref.end(),"registry each erase exists");if(!spec.public_data){auto local=unit-seg.begin;bool endpoint=spec.pattern=="endpoint"||(spec.pattern=="mechanism"&&(phase==1||phase==3));auto slot=spec.pattern=="competition"?local%64:spec.pattern=="mechanism"&&!endpoint?(phase==2?32:0)+local%32:0;auto first=ref.lower_bound(slot*b.domain.stride);auto rank=std::distance(first,it)+1;if(endpoint){require(rank==1&&st.added==key(b.domain,slot,identity++),"registry endpoint fresh monotone global identity");}else{std::uniform_int_distribution<std::size_t> choose(spec.pattern=="low"?2:(spec.n+3)/4,spec.pattern=="low"?8:3*spec.n/4);require(std::size_t(rank)==choose(rng)&&st.added==*it,"registry independent separated RNG, per-bucket middle/low rank and restored full Record");}require(b.domain.slot(st.erased)==slot&&b.domain.slot(st.added.first)==slot,"registry slot/time mapping");}
  ref.erase(it);require(ref.insert(st.added).second,"registry fresh or restored unique complete key");ordinal+=2;if(st.query){++ordinal;auto ans=query(ref,st.lo,st.hi);require(queries<f.expected.size()&&f.expected[queries].records==ans&&f.expected[queries].api_ordinal==ordinal,"registry independent exact query/API replay");if(spec.pattern=="prefix")require(ans.size()==8,"registry prefix8");++queries;}}}
 require(std::vector<Record>(ref.begin(),ref.end())==b.whole.final&&queries==b.whole.queries&&ordinal==2*b.request.units+queries,"registry exact final/queries/API");if(id=="M01")require(b.request.initial==131072&&b.request.units==131072&&b.segments.size()==5&&b.segments[0].end==32768&&b.segments[1].end==49152&&b.segments[2].end==81920&&b.segments[3].end==98304&&b.segments[4].end==131072,"registry full formal M01 generator shape, no timing experiment");
 for(auto profile:std::vector<std::string>{"dev","final","aa","mechanism"}){bool allowed=profile=="dev"?id[0]=='D':profile=="final"?id[0]=='F':profile=="aa"?(id=="D02"||id=="D06"||id=="F01"||id=="F03"||id=="F06"):id=="M01";auto seed=profile=="dev"?90001:profile=="final"?91001:profile=="aa"?92001:93001;bool accepts=true;try{validate_registered(id,seed,profile);}catch(const std::invalid_argument&){accepts=false;}require(accepts==allowed,"registry exact case/seed/profile whitelist");}bool rejects=false;try{validate_registered(id,94001,"final");}catch(const std::invalid_argument&){rejects=true;}require(rejects,"registry test seed cannot masquerade formal input");std::cout<<"registry "<<id<<" U="<<b.request.units<<" APIs="<<ordinal<<" exact mismatches=0\n";}
#endif
int main(int argc,char** argv){try{if(argc<2)throw std::runtime_error("suite required");std::string test=argv[1];if(test=="SX16")SX16();else if(test=="SX17")SX17();else if(test=="SX18")SX18(argc>2?argv[2]:"driver_cache_test");else if(test=="SX19")SX19();else if(test=="SX22")SX22();else if(test=="SX24")SX24(argc>2?argv[2]:"driver_diag_test");
#ifndef DRIVER_RED
else if(test.rfind("REGISTRY_",0)==0)registry(test.substr(9));
else if(test=="CACHE_NORMS")cache_norms(argc>2?argv[2]:"driver_norm_test");
#endif
else throw std::runtime_error("unknown suite");std::cout<<"PASS "<<test<<" engineering correctness only\n";return 0;}catch(const std::exception& e){std::cerr<<"ASSERTION: "<<e.what()<<'\n';return 1;}}
