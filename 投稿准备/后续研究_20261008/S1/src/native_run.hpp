#pragma once
#include "workloads.hpp"
#include "adapters.hpp"
#define WIN32_LEAN_AND_MEAN
#define NOMINMAX
#include <windows.h>
namespace s1 {
using Clock=std::chrono::steady_clock;
inline std::uint64_t elapsed_ns(Clock::time_point begin,Clock::time_point end){return static_cast<std::uint64_t>(std::chrono::duration_cast<std::chrono::nanoseconds>(end-begin).count());}
struct Placement{std::uint64_t process_mask=0,system_mask=0;unsigned cpu=UINT_MAX,group=UINT_MAX;};
inline Placement placement(){DWORD_PTR mask=0,system=0;PROCESSOR_NUMBER number{};GetCurrentProcessorNumberEx(&number);if(!GetProcessAffinityMask(GetCurrentProcess(),&mask,&system))throw std::runtime_error("process affinity query failed");return {std::uint64_t(mask),std::uint64_t(system),number.Number,number.Group};}
inline void validate_placement(const Placement& p){if(p.process_mask!=8||p.cpu!=3||p.group!=0)throw std::runtime_error("fixed placement requires process_mask8 cpu3 group0");}
struct PhaseTime{std::size_t begin=0,end=0;std::uint64_t queries=0,returned=0,online_ns=0;std::string name;};
struct NativeResult {
 std::uint64_t build_ns=0,online_ns=0,total_ns=0,destroy_ns=0,lifecycle_ns=0,api_calls=0,returned=0,query_hash=udriver::phase_hash_basis;
 std::vector<PhaseTime> phases;std::vector<std::string> boundaries;
 std::string work="NA",promotions="NA",scheduled="NA",cleanup="NA",demotions="NA",peak_trees="NA",final_trees="NA",cand_last="NA",cand_max="NA",nodes="NA",up_ns="NA",down_ns="NA",failures="NA",credit_unit="NA";
 std::array<std::string,4> accounts{{"NA","NA","NA","NA"}};std::array<pbadaptive::MemoryStats,4> account_stats{};
 Placement start,end;bool verified=false;
};
template<class A>void collect_counters(NativeResult& r,const typename A::Index& x,const pbadaptive::MemoryAccounts& mem){
 r.promotions=std::to_string(x.promotions());r.final_trees=std::to_string(x.tree_buckets());
 if constexpr(A::original){r.nodes=std::to_string(x.pool_capacity());r.up_ns=std::to_string(x.conversion_ns());}
 else{if constexpr(!A::list)r.work=std::to_string(x.total_avoidable_work());r.scheduled=std::to_string(x.scheduled_demotions());r.cleanup=std::to_string(x.cleanup_demotions());r.demotions=std::to_string(x.total_demotions());r.peak_trees=std::to_string(x.peak_tree_buckets());r.cand_last=std::to_string(x.last_epoch_candidate_count());r.cand_max=std::to_string(x.max_epoch_candidate_count());r.nodes=std::to_string(x.nodes_allocated());r.up_ns=std::to_string(x.conversion_up_ns());r.down_ns=std::to_string(x.conversion_down_ns());r.failures=std::to_string(x.conversion_failures());r.credit_unit=A::event?"event":A::list?"NA":A::threshold?"none":"ns";
#ifdef INDEX_MEMORY
  r.account_stats={mem.pool,mem.buckets,mem.tree,mem.manager};for(unsigned j=0;j<4;++j)r.accounts[j]=std::to_string(r.account_stats[j].current);
#endif
 }(void)mem;
}
// The measured body has only constructor/build, two fixed phase boundary clocks,
// and destruction clocks. API calls/hash/output destruction stay inside phase.
template<class A>NativeResult native_body(const Bundle& b,bool fixed_placement){
 NativeResult r;r.phases.reserve(b.segments.size());r.boundaries={"construct_build","initial_values","phase_online_hash_output_release","final_values","counters","destroy"};pbadaptive::MemoryAccounts memory;
 r.start=placement();if(fixed_placement)validate_placement(r.start);
 // AUDIT_BUILD_BEGIN: constructor and its reserves are inside build.
 const auto build_begin=Clock::now();std::unique_ptr<typename A::Index>x(A::construct(b.domain,memory));x->build(b.whole.initial);const auto build_end=Clock::now();r.build_ns=elapsed_ns(build_begin,build_end);
 // AUDIT_INITIAL_VALUES: outside build/online, before first online clock.
 if(x->values()!=b.whole.initial)throw std::runtime_error("initial complete values mismatch");
 for(const auto& seg:b.segments){PhaseTime p;p.begin=seg.begin;p.end=seg.end;p.name=seg.name;p.queries=seg.queries;p.returned=seg.returned;
  // AUDIT_ONLINE_BEGIN: fixed phase boundary; no per-API Clock.
  const auto begin=Clock::now();
  for(std::size_t unit=seg.begin;unit<seg.end;++unit){const auto& st=b.whole.steps[unit];x->erase(st.erased);x->insert(st.added);r.api_calls+=2;if(st.query){++r.api_calls;auto output=x->range(st.lo,st.hi);const auto hash=udriver::hash_records(output);if(hash!=st.expected_hash||output.size()!=st.expected_count)throw std::runtime_error("online hash/count mismatch");r.query_hash=udriver::mix(r.query_hash,hash);r.returned+=output.size();} // output destroyed before next unit/end Clock.
  }
  const auto end=Clock::now();p.online_ns=elapsed_ns(begin,end);r.online_ns+=p.online_ns;r.phases.push_back(std::move(p));
 }
 // AUDIT_FINAL_VALUES_COUNTERS: complete values and counters outside online.
 if(x->values()!=b.whole.final)throw std::runtime_error("final complete values mismatch");collect_counters<A>(r,*x,memory);
 // AUDIT_DESTROY: separate from total.
 const auto destroy_begin=Clock::now();x.reset();const auto destroy_end=Clock::now();r.destroy_ns=elapsed_ns(destroy_begin,destroy_end);r.total_ns=r.build_ns+r.online_ns;r.lifecycle_ns=r.total_ns+r.destroy_ns;r.end=placement();if(fixed_placement)validate_placement(r.end);r.verified=true;return r;
}
struct NativeCall{const Bundle& bundle;bool fixed;template<class A>NativeResult operator()(){return native_body<A>(bundle,fixed);}};
inline NativeResult native_engineering(const Bundle& b,const std::string& method){return native_dispatch(method,NativeCall{b,false});}
inline NativeResult native_production(const Bundle& b,const std::string& method){if(mode_contract().active!="native")throw std::runtime_error("native run requires native binary");return native_dispatch(method,NativeCall{b,true});}
}
