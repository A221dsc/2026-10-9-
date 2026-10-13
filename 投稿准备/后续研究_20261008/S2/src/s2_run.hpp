#pragma once
#include "s2_inputs.hpp"
#include "../../../adaptive_poolhbi/final/adaptive_poolhbi_final.hpp"
#include "../../../adaptive_poolhbi/final/frozen_config.hpp"
#include "../../S1/src/matched_index.hpp"
#include "../../S1/src/owner_tracker.hpp"
#include <tlx/container/btree_map.hpp>
#include <memory>
#if defined(INDEX_MEMORY) != defined(ADAPTIVE_ALLOC_TRACK)
#error S2 resource needs INDEX_MEMORY and ADAPTIVE_ALLOC_TRACK together
#endif
#if defined(S0_EVENT_TRACE)||defined(ADAPTIVE_ABLATION)||defined(INDEX_FAILURE_TEST)||defined(ALLOCATION_FAILURE_INJECTION)
#error Frozen S2 production indexes only
#endif
namespace s2 {
#ifdef ADAPTIVE_ALLOC_TRACK
using Owner=s1::owner::Owner;using OwnerScope=s1::owner::Scope;using OwnerPause=s1::owner::Pause;
#else
// Native instantiations have no owner State, allocator, TLS access or statistics.
struct Owner{};struct OwnerScope{explicit OwnerScope(Owner&) noexcept{}};struct OwnerPause{OwnerPause() noexcept{}};
static_assert(std::is_empty_v<Owner> && std::is_empty_v<OwnerScope> && std::is_empty_v<OwnerPause>);
#endif
inline std::string owner_value(std::size_t n){return n==SIZE_MAX?"NA":std::to_string(n);}
inline std::string owner_json(std::size_t n){return n==SIZE_MAX?"\"NA\"":std::to_string(n);}
inline const char* mode(){
#ifdef ADAPTIVE_ALLOC_TRACK
 return "resource";
#else
 return "native";
#endif
}
class Tlx {
 tlx::btree_map<std::uint64_t,std::uint64_t> data_;
public:
 Tlx(Domain,const pbadaptive::Params&,pbadaptive::MemoryAccounts&){}
 void build(const std::vector<Record>& input){for(std::size_t j=0;j<input.size();++j){if(input[j].first==UINT64_MAX||input[j].second==UINT64_MAX||(j&&input[j-1].first>=input[j].first))throw std::invalid_argument("TLX sorted unique build");}data_.bulk_load(input.begin(),input.end());}
 void insert(Record r){data_.insert(r);}void erase(std::uint64_t key){data_.erase(key);}
 std::vector<Record> range(std::uint64_t lo,std::uint64_t hi)const{if(lo>=hi)return {};return {data_.lower_bound(lo),data_.lower_bound(hi)};}
 std::vector<Record> values()const{return {data_.begin(),data_.end()};}
};
struct Placement{std::uint64_t process_mask=0;unsigned cpu=UINT_MAX,group=UINT_MAX;};
inline Placement placement(){DWORD_PTR mask=0,system=0;PROCESSOR_NUMBER n{};GetCurrentProcessorNumberEx(&n);if(!GetProcessAffinityMask(GetCurrentProcess(),&mask,&system))throw std::runtime_error("affinity query");return {std::uint64_t(mask),n.Number,n.Group};}
inline void require_placement(Placement p){if(p.process_mask!=8||p.cpu!=3||p.group!=0)throw std::runtime_error("S2 fixed mask8 cpu3 group0 required");}
struct Counters{std::string promotions="NA",scheduled_demotions="NA",cleanup_demotions="NA",total_demotions="NA",peak_tree_buckets="NA",final_tree_buckets="NA",candidate_max="NA",nodes_allocated="NA";};
struct Snapshot{std::size_t unit=0;bool phase_boundary=false;std::size_t whole_current=0,whole_peak=0,whole_live=0;std::array<std::string,4> current{{"NA","NA","NA","NA"}},peak{{"NA","NA","NA","NA"}};Counters counters;};
struct PhaseTime{std::string name;std::size_t begin=0,end=0;std::uint64_t queries=0,returned=0,online_ns=0;};
struct Result{std::uint64_t build_ns=0,online_ns=0,total_ns=0,destroy_ns=0,API_calls=0,returned=0,query_hash=udriver::phase_hash_basis;bool verified=false;std::size_t owner_current_after_destroy=SIZE_MAX,owner_live_after_destroy=SIZE_MAX,owner_peak=SIZE_MAX;Counters counters;std::array<std::string,4> account_current{{"NA","NA","NA","NA"}},account_peak{{"NA","NA","NA","NA"}};std::vector<PhaseTime> phases;std::vector<Snapshot> snapshots;Placement start,end;};
template<class T> Counters counters(const T& x){Counters c;if constexpr(!std::is_same_v<T,Tlx>){if(x.tree_buckets()>32||x.peak_tree_buckets()>32||x.total_demotions()!=x.scheduled_demotions()+x.cleanup_demotions())throw std::runtime_error("S2 conversion/budget invariant");c.promotions=std::to_string(x.promotions());c.scheduled_demotions=std::to_string(x.scheduled_demotions());c.cleanup_demotions=std::to_string(x.cleanup_demotions());c.total_demotions=std::to_string(x.total_demotions());c.peak_tree_buckets=std::to_string(x.peak_tree_buckets());c.final_tree_buckets=std::to_string(x.tree_buckets());c.candidate_max=std::to_string(x.max_epoch_candidate_count());c.nodes_allocated=std::to_string(x.nodes_allocated());}return c;}
inline std::array<pbadaptive::MemoryStats,4> accounts(const pbadaptive::MemoryAccounts& m){return {m.pool,m.buckets,m.tree,m.manager};}
using Clock=std::chrono::steady_clock;
inline std::uint64_t ns(Clock::time_point a,Clock::time_point b){return std::uint64_t(std::chrono::duration_cast<std::chrono::nanoseconds>(b-a).count());}
template<class T> Result run_body(const Bundle& b,bool pinned,bool exact){Result r;r.phases.reserve(b.segments.size());r.snapshots.reserve(b.segments.size()+3);pbadaptive::MemoryAccounts memory;Owner owner;r.start=placement();if(pinned)require_placement(r.start);std::unique_ptr<T> index;
 // Only actual index constructor/reserves/build are in the build clock.
 {OwnerScope scope(owner);const auto a=Clock::now();index.reset(new T(b.domain,pbadaptive::load_frozen_config("R6").params,memory));index->build(b.whole.initial);const auto z=Clock::now();r.build_ns=ns(a,z);}
 if(index->values()!=b.whole.initial)throw std::runtime_error("S2 initial full equality");
 std::map<std::uint64_t,std::uint64_t> ref;if(exact)ref.insert(b.whole.initial.begin(),b.whole.initial.end());
 for(const auto& seg:b.segments){PhaseTime p;p.name=seg.name;p.begin=seg.begin;p.end=seg.end;p.queries=seg.queries;p.returned=seg.returned;
  const auto a=Clock::now();
  for(std::size_t j=seg.begin;j<seg.end;++j){const auto& st=b.whole.steps[j];
   {OwnerScope scope(owner);index->erase(st.erased);index->insert(st.added);r.API_calls+=2;if(st.query){++r.API_calls;auto output=index->range(st.lo,st.hi);auto hash=udriver::hash_records(output);if(hash!=st.expected_hash||output.size()!=st.expected_count)throw std::runtime_error("S2 online hash/count equality");r.query_hash=udriver::mix(r.query_hash,hash);r.returned+=output.size();if(exact){OwnerPause pause;ref.erase(st.erased);ref.insert(st.added);if(output!=ref_range(ref,st.lo,st.hi))throw std::runtime_error("S2 exact query output");}}else if(exact){OwnerPause pause;ref.erase(st.erased);ref.insert(st.added);}}
#ifdef ADAPTIVE_ALLOC_TRACK
   // The query output is already released. Snapshot/reference storage is unowned.
   auto unit=j+1;if(unit==b.request.initial||unit==2*b.request.initial||unit==4*b.request.initial||unit==seg.end){Snapshot s;s.unit=unit;s.phase_boundary=unit==seg.end;s.whole_current=owner.current;s.whole_peak=owner.peak;s.whole_live=owner.live;s.counters=counters(*index);if constexpr(!std::is_same_v<T,Tlx>){auto stats=accounts(memory);for(unsigned k=0;k<4;++k){s.current[k]=std::to_string(stats[k].current);s.peak[k]=std::to_string(stats[k].peak);}}r.snapshots.push_back(std::move(s));}
#endif
  }
  const auto z=Clock::now();p.online_ns=ns(a,z);r.online_ns+=p.online_ns;r.phases.push_back(std::move(p));
 }
 if(index->values()!=b.whole.final||r.API_calls!=2*b.request.units+b.whole.queries||r.returned!=b.whole.returned)throw std::runtime_error("S2 final equality/counters");r.counters=counters(*index);
#ifdef INDEX_MEMORY
 if constexpr(!std::is_same_v<T,Tlx>){auto stats=accounts(memory);for(unsigned k=0;k<4;++k){r.account_current[k]=std::to_string(stats[k].current);r.account_peak[k]=std::to_string(stats[k].peak);}}
#endif
 {OwnerScope scope(owner);const auto a=Clock::now();index.reset();const auto z=Clock::now();r.destroy_ns=ns(a,z);}
#ifdef ADAPTIVE_ALLOC_TRACK
 r.owner_current_after_destroy=owner.current;r.owner_live_after_destroy=owner.live;r.owner_peak=owner.peak;if(owner.current||owner.live)throw std::runtime_error("S2 whole owner not zero");
#endif

#ifdef INDEX_MEMORY
 for(auto s:accounts(memory))if(s.current)throw std::runtime_error("S2 account not zero");
#endif
 r.total_ns=r.build_ns+r.online_ns;r.end=placement();if(pinned)require_placement(r.end);r.verified=true;return r;}
inline Result run(const Bundle& b,const std::string& method,bool pinned,bool exact=true){if(method=="M_LIST")return run_body<matched::Index<matched::Arm::List>>(b,pinned,exact);if(method=="M_EVENT_16")return run_body<matched::Index<matched::Arm::Event,16>>(b,pinned,exact);if(method=="R6")return run_body<pbadaptive::Index>(b,pinned,exact);if(method=="TLX")return run_body<Tlx>(b,pinned,exact);throw std::invalid_argument("S2 unknown method");}
}
