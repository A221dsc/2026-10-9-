#include "../../../adaptive_poolhbi/final/frozen_config.hpp"
#include "../../../adaptive_poolhbi/final/adaptive_poolhbi_final.hpp"
#include "../../../adaptive_poolhbi/final_experiments/legacy/pool_index.hpp"
#ifdef KERNEL_RED
#include "red_adapter.hpp"
#else
#include "../src/matched_index.hpp"
#ifdef KERNEL_DIAGNOSTIC
#include "../src/diagnostic_index.hpp"
#endif
#endif
#include "alloc_tracker.hpp"
#include <iostream>
#include <random>
#include <string>
#include <stdexcept>
#include <type_traits>

using pbadaptive::Record;
using pbadaptive::MemoryAccounts;
using pbadaptive::Domain;
using matched::Arm;
#if defined(KERNEL_DIAGNOSTIC) && !defined(KERNEL_RED)
template<Arm A,std::size_t T=0> using I=diagnostic::Index<A,T>;
#else
template<Arm A,std::size_t T=0> using I=matched::Index<A,T>;
#endif
// Test metadata only: SX02 calls the direct frozen production implementation.
struct FrozenR6Adapter : pbadaptive::Index {
    using pbadaptive::Index::Index;
    static constexpr Arm arm=Arm::Cost;
};
static_assert(sizeof(FrozenR6Adapter)==sizeof(pbadaptive::Index),"direct R6 adapter adds no fields");
constexpr Domain domain{std::uint64_t(1)<<40,4096};
static auto params() { return pbadaptive::load_frozen_config("R6").params; }
static void check(bool condition,const char* message) { if(!condition) throw std::runtime_error(message); }
static void near(double a,double b,const char* message) { check(std::abs(a-b)<=1e-8*std::max(1.0,std::abs(b)),message); }
static Record key(std::size_t slot,std::uint64_t row) { return {slot*domain.stride+row,row}; }
static std::vector<Record> initial(std::size_t count,std::size_t slots=1) {
    std::vector<Record> v; v.reserve(count*slots);
    for(std::size_t s=0;s<slots;++s) for(std::size_t r=1;r<=count;++r) v.push_back(key(s,r));
    return v;
}
template<class T> static void finish_epoch(T& x,std::size_t filler=4095) {
    const auto e=x.epoch();
    do { x.erase(key(filler,100000)); } while(x.epoch()==e);
}
template<class T> static void heat(T& x,std::size_t s,std::size_t n,std::size_t observations=200) {
    for(std::size_t j=0;j<observations;++j) {
        auto out=x.range(key(s,n/2).first,key(s,n/2).first+1);
        check(out.size()==1,"heat query exact output");
    }
}
template<class T> static void promote(T& x,std::size_t s,std::size_t n) {
    heat(x,s,n); x.erase(key(s,n+1)); finish_epoch(x);
    check(x.is_tree(s),"legal API promotion");
}
template<class T> static void exact(const T& x,const std::multiset<Record>& ref) {
    check(x.values()==std::vector<Record>(ref.begin(),ref.end()),"exact complete multiset");
    check(x.size()==ref.size(),"exact size");
}
static std::vector<Record> reference_range(const std::multiset<Record>& ref,std::uint64_t lo,std::uint64_t hi) {
    std::vector<Record> out; hi=std::min(hi,domain.end());
    if(lo>=hi) return out;
    for(auto it=ref.lower_bound({lo,0});it!=ref.end() && it->first<hi;++it) out.push_back(*it);
    return out;
}
template<class T> static void contents() {
    MemoryAccounts m; T x(domain,params(),m);
    std::multiset<Record> ref;
    for(Record r: {key(0,9),key(0,1),key(0,5),key(0,5),key(3,1),key(4095,2)}) {
        x.insert(r); ref.insert(r); exact(x,ref);
    }
    for(Record r: {key(0,1),key(0,5),key(0,99),key(4095,2),key(0,9),key(0,5)}) {
        const auto old=x.ops_in_epoch(); x.erase(r);
        auto it=ref.find(r); if(it!=ref.end()) ref.erase(it);
        exact(x,ref);
        if constexpr(T::arm==Arm::List) check(x.ops_in_epoch()==0,"LIST miss has no clock");
        else check(x.ops_in_epoch()==old+1,"successful erase/miss clocks once");
    }
    x.insert(key(0,5)); ref.insert(key(0,5)); x.erase(key(0,5).first);
    ref.erase(ref.find(key(0,5))); exact(x,ref);
    const auto old=x.ops_in_epoch(),e=x.epoch();
    for(auto bounds: {std::pair<std::uint64_t,std::uint64_t>{0,1}, {0,key(3,1).first},
                     {key(3,1).first,key(3,1).first+1},{0,domain.end()+4}, {domain.end()+1,domain.end()+2},{7,7}})
        check(x.range(bounds.first,bounds.second)==reference_range(ref,bounds.first,bounds.second),"half-open and clipped range");
    check(old==x.ops_in_epoch() && e==x.epoch(),"range never clocks");
    bool thrown=false; try { x.insert({domain.end(),0}); } catch(const std::out_of_range&) { thrown=true; }
    check(thrown,"invalid insert rejected");
    thrown=false; try { x.erase(domain.end()); } catch(const std::out_of_range&) { thrown=true; }
    check(thrown && old==x.ops_in_epoch() && e==x.epoch(),"invalid erase no clock"); exact(x,ref);
    thrown=false; try { T bad(Domain{0,1},params(),m); } catch(const std::invalid_argument&) { thrown=true; }
    check(thrown,"invalid domain rejected");
    MemoryAccounts bm; T bulk(domain,params(),bm);
    std::vector<Record> v{key(0,1),key(0,1),key(0,2),key(1,3)}; bulk.build(v);
    check(bulk.values()==v && bulk.epoch()==0 && bulk.ops_in_epoch()==0,"build full pair duplicates no observation");
    thrown=false; try { bulk.build(v); } catch(const std::logic_error&) { thrown=true; }
    check(thrown,"build requires fresh");
}
static void original_contents() {
    pubbench::PoolIndex<false> x(domain); std::multiset<Record> ref;
    auto v=initial(8,2); v.insert(v.begin()+3,v[3]); x.build(v); ref.insert(v.begin(),v.end()); exact(x,ref);
    for(auto r:{key(0,4),key(0,99),key(1,1)}) { x.erase(r.first); auto it=ref.find(r); if(it!=ref.end()) ref.erase(it); exact(x,ref); }
    x.insert(key(0,4)); ref.insert(key(0,4)); exact(x,ref);
    for(auto p: {std::pair<std::uint64_t,std::uint64_t>{0,key(1,1).first},{4,7},{0,domain.end()+1},{2,2}})
        check(x.range(p.first,p.second)==reference_range(ref,p.first,p.second),"Original half-open output");
    bool rejected=false; try{x.insert({domain.end(),0});}catch(const std::out_of_range&){rejected=true;}
    check(rejected,"Original invalid key rejected");
}
template<class T> static void random_test(std::uint64_t seed) {
    MemoryAccounts m; T x(domain,params(),m); auto v=initial(24,2); x.build(v);
    std::multiset<Record> ref(v.begin(),v.end()); std::mt19937_64 rng(seed);
    for(std::size_t step=0;step<100000;++step) {
        const auto op=rng()%5; const auto r=key(rng()%4,rng()%40+1);
        if(op==0 && ref.size()<96) { x.insert(r); ref.insert(r); }
        else if(op<=2) { x.erase(r); auto it=ref.find(r); if(it!=ref.end()) ref.erase(it); }
        else {
            auto lo=key(rng()%4,rng()%40).first,hi=key(rng()%4,rng()%40).first;
            if(lo>hi) std::swap(lo,hi);
            check(x.range(lo,hi)==reference_range(ref,lo,hi),"random exact query");
        }
        exact(x,ref);
    }
    std::cout<<"RANDOM arm="<<int(T::arm)<<" seed="<<seed<<" operations=100000 mismatches=0\n";
}

static void sx01() {
    check(sizeof(Record)==16,"Record=16");
#define SIZE(A,T) check(sizeof(matched::Index<Arm::A,T>)==sizeof(pbadaptive::Index) && sizeof(I<Arm::A,T>)==sizeof(pbadaptive::Index),"native and diagnostic Index layout size");
    SIZE(List,0) SIZE(ObserveList,0) SIZE(Fixed,128) SIZE(Fixed,512) SIZE(Fixed,2048) SIZE(Fixed,8192)
    SIZE(Event,8) SIZE(Event,16) SIZE(Event,32) SIZE(Event,64) SIZE(Cost,0) SIZE(NoIdle,0)
#undef SIZE
    std::cout<<"LAYOUT Record="<<sizeof(Record)<<" Index="<<sizeof(pbadaptive::Index)<<" Node=32 Adaptive=32 Bucket=64\n";
#ifdef ADAPTIVE_ALLOC_TRACK
    auto sequence=[](auto* dummy) {
        using T=std::remove_pointer_t<decltype(dummy)>; MemoryAccounts m;
        kernel_alloc::reset(); kernel_alloc::active=true;
        { T x(domain,params(),m); kernel_alloc::active=false;
          check(kernel_alloc::allocations==67,"constructor exactly 3 reserves and 64 roots"); }
        check(kernel_alloc::current==0 && m.current()==0,"constructor destructor owns all allocations");
        std::array<std::size_t,67> sizes{}; std::size_t i=0;
        for(std::size_t j=0;j<kernel_alloc::used;++j) if(kernel_alloc::entries[j].allocation) sizes[i++]=kernel_alloc::entries[j].bytes;
        return sizes;
    };
    const auto seq=sequence(static_cast<pbadaptive::Index*>(nullptr));
    check(seq[0]==32*sizeof(void*) && seq[1]==4096*sizeof(void*) && seq[2]==4096*sizeof(void*),"reserve byte/order");
    for(std::size_t j=3;j<67;++j) check(seq[j]==4096,"root request bytes");
#define SEQ(A,T) check(sequence(static_cast<I<Arm::A,T>*>(nullptr))==seq,"matched constructor allocation sequence");
    SEQ(List,0) SEQ(ObserveList,0) SEQ(Fixed,128) SEQ(Fixed,512) SEQ(Fixed,2048) SEQ(Fixed,8192)
    SEQ(Event,8) SEQ(Event,16) SEQ(Event,32) SEQ(Event,64) SEQ(Cost,0) SEQ(NoIdle,0)
#undef SEQ
#endif
}
static void sx02() {
    contents<FrozenR6Adapter>();
    std::cout<<"SX02 direct_frozen_R6_complete_contents PASS\n";
    contents<I<Arm::List>>(); contents<I<Arm::ObserveList>>(); contents<I<Arm::Fixed,128>>();
    contents<I<Arm::Event,16>>(); contents<I<Arm::Cost>>(); contents<I<Arm::NoIdle>>(); original_contents();
}
static void sx04() {
    MemoryAccounts m; I<Arm::List> x(domain,params(),m); x.build(initial(256));
#if defined(KERNEL_DIAGNOSTIC) && !defined(KERNEL_RED)
    diagnostic::reset_observation_counters();
#endif
    heat(x,0,256); for(std::size_t j=0;j<1024;++j) x.erase(key(0,128));
    check(x.total_avoidable_work()==0 && x.last_work()==0,"M_LIST work accounting disabled; native exported NA");
    check(x.gain_ns_of(0)==0 && x.last_sensitive_epoch_of(0)==0,"M_LIST no credit or sensitivity");
    check(x.epoch()==0 && x.ops_in_epoch()==0 && x.cand_size()==0 && x.tree_count()==0,"M_LIST no clock/candidates/conversion");
#if defined(KERNEL_DIAGNOSTIC) && !defined(KERNEL_RED)
    check(diagnostic::observation_counters.list_work>0 && diagnostic::observation_counters.range_buffers==0 && diagnostic::observation_counters.epoch_scans==0 && diagnostic::observation_counters.candidate_visits==0,"LIST diagnostic external W while native arrays/scans absent");
    std::cout<<"diagnostic_external_list_work="<<diagnostic::observation_counters.list_work<<"\n";
#endif
    std::cout<<"native_work_available=false native_work=NA\n";
}
static std::size_t klass(std::size_t n) { std::size_t c=0,v=n>1?n-1:0; while(v){++c;v>>=1;} return std::min<std::size_t>(c>7?c-7:0,9); }
static void sx05() {
    for(auto n:{0u,1u,127u,128u,129u,255u,256u,257u,511u,512u,513u,32768u,32769u,65536u,65537u,131072u}) {
        MemoryAccounts m; I<Arm::ObserveList> x(domain,params(),m); x.build(initial(n));
        const double tc=params().tree_cost[klass(n)][2];
        x.range(0,1); near(x.gain_ns_of(0),-tc,"zero-work negative intercept and class");
        for(std::size_t prefix:{n/4,n/2}) {
            const double old=x.gain_ns_of(0);
            const auto lo=prefix?key(0,prefix).first:0;
            x.range(lo,lo+1); const auto w=prefix?2*(prefix-1):0;
            check(x.last_work()==w,"exact prefix W");
            near(x.gain_ns_of(0)-old,params().scan_ns_per_work*w-tc,"full precision slope/intercept");
        }
        check(x.epoch()==0 && x.cand_size()==0,"Observe range no clock/candidate");
    }
    MemoryAccounts m; I<Arm::ObserveList> x(domain,params(),m); x.build(initial(256)); heat(x,0,256);
    for(std::size_t j=0;j<512;++j) x.erase(key(0,128));
    check(x.epoch()==1 && x.ops_in_epoch()==0,"Observe exact512 clock");
    check(x.cand_size()==0 && x.last_epoch_candidate_count()==0 && x.max_epoch_candidate_count()==0 && x.promotions()==0,"Observe no management scan or conversion");
#if defined(KERNEL_DIAGNOSTIC) && !defined(KERNEL_RED)
    diagnostic::reset_observation_counters();
    x.range(2,3); x.range(4,4); finish_epoch(x);
    check(diagnostic::observation_counters.range_buffers==1 && diagnostic::observation_counters.epoch_scans==0 && diagnostic::observation_counters.candidate_visits==0,"Observe retains buffers but does not call process_epoch");
#endif
}
template<std::size_t Theta> static void event_boundary() {
    MemoryAccounts m; I<Arm::Event,Theta> x(domain,params(),m); x.build(initial(256));
    x.range(0,1); check(x.gain_ns_of(0)==0,"Event W0 adds zero, no negative intercept");
    for(std::size_t j=1;j<Theta;++j) x.range(128,129);
    check(x.gain_ns_of(0)==Theta-1,"Event each positive observation adds exactly1");
    x.erase(key(0,257)); check(x.cand_size()==0,"Event below threshold no candidate");
    x.range(64,65); check(x.gain_ns_of(0)==Theta && x.cand_size()==0,"range reaches theta but does not register");
    x.erase(key(0,257)); check(x.cand_size()==1,"structural touch registers theta");
    finish_epoch(x); check(x.is_tree(0) && x.gain_ns_of(0)==0,"Event promoted without PAYBACK and reset");
    x.range(128,129); x.erase(key(0,257)); check(x.gain_ns_of(0)==0,"TREE never accumulates events");
    MemoryAccounts m2; I<Arm::Event,Theta> y(domain,params(),m2); y.build(initial(8192));
    for(std::size_t j=0;j<Theta;++j) y.range(2,3);
    y.erase(key(0,8193)); finish_epoch(y); check(y.is_tree(0),"Event no size-scaled PAYBACK");
    MemoryAccounts m3; I<Arm::Event,Theta> z(domain,params(),m3); z.build(initial(256));
    z.range(2,3); const auto low=z.last_work(); z.range(128,129);
    check(z.gain_ns_of(0)==2 && z.last_work()>low,"same events different positive W");
    for(std::size_t j=0;j<4;++j) finish_epoch(z);
    z.range(128,129); check(z.gain_ns_of(0)==1,"Event lazy idle reset before new event");
}
static void sx06() { event_boundary<8>(); event_boundary<16>(); event_boundary<32>(); event_boundary<64>(); }
template<std::size_t H> static void fixed_boundary() {
    constexpr auto n=H<128?128:H; MemoryAccounts m; I<Arm::Fixed,H> x(domain,params(),m); x.build(initial(n-1));
    x.range(2,3); check(x.gain_ns_of(0)==0,"Fixed gain always zero");
    x.erase(key(0,n+1)); check(x.cand_size()==0,"Fixed n below h not eligible");
    x.insert(key(0,n)); check(x.cand_size()==1 && x.bucket_size(0)==n,"Fixed operation-after n boundary");
    finish_epoch(x); check(x.is_tree(0),"Fixed exact h promotes without credit");
    MemoryAccounts rm; I<Arm::Fixed,H> r(domain,params(),rm); r.build(initial(n));
    r.range(2,3); check(r.cand_size()==0,"Fixed range never registers");
    r.erase(key(0,n+1)); check(r.cand_size()==1,"Fixed registered eligible bucket");
    r.erase(key(0,n)); finish_epoch(r);
    check(!r.is_tree(0) && r.cand_size()==0 && r.last_epoch_candidate_count()==1,"Fixed candidate size revalidation");
}
static void sx07() { fixed_boundary<128>(); fixed_boundary<512>(); fixed_boundary<2048>(); fixed_boundary<8192>(); }
template<class T> static void ranking(bool tie) {
    MemoryAccounts m; T x(domain,params(),m); auto v=initial(256,3);
    if(!tie && T::arm==Arm::Fixed) for(std::size_t r=257;r<=384;++r) v.insert(std::lower_bound(v.begin(),v.end(),key(1,r)),key(1,r));
    x.build(v);
    for(std::size_t s=0;s<3;++s) {
        heat(x,s,256,(!tie && s==1)?220:200);
        x.erase(key(s,500)); x.erase(key(s,500)); check(x.cand_size()==s+1,"candidate exact dedup");
    }
    check(x.cand_size()==3 && x.max_epoch_candidate_count()<=4096,"candidate bounded");
    std::size_t best=0;
    for(std::size_t s=1;s<3;++s) {
        bool better=false,equal=false;
        if constexpr(T::arm==Arm::Fixed) { better=x.bucket_size(s)>x.bucket_size(best); equal=x.bucket_size(s)==x.bucket_size(best); }
        else if constexpr(T::arm==Arm::Event) { better=x.gain_ns_of(s)>x.gain_ns_of(best); equal=x.gain_ns_of(s)==x.gain_ns_of(best); }
        else {
            const double a=x.gain_ns_of(s)/x.bucket_size(s),b=x.gain_ns_of(best)/x.bucket_size(best);
            better=a>b || (a==b && x.gain_ns_of(s)>x.gain_ns_of(best)); equal=a==b && x.gain_ns_of(s)==x.gain_ns_of(best);
        }
#if defined(KERNEL_DIAGNOSTIC) && !defined(KERNEL_RED)
        if(equal) better=std::less<const void*>{}(x.bucket_address_of(s),x.bucket_address_of(best));
#else
        (void)equal;
#endif
        if(better) best=s;
    }
    finish_epoch(x); check(x.tree_count()==1 && x.last_epoch_candidate_count()==3,"one promotion with3 candidates");
#if defined(KERNEL_DIAGNOSTIC) && !defined(KERNEL_RED)
    check(x.is_tree(best),"exact score then std::less bucket address ranking");
    for(std::size_t s=0;s<3;++s) std::cout<<"TIE arm="<<int(T::arm)<<" slot="<<s<<" address="<<x.bucket_address_of(s)<<" tree="<<x.is_tree(s)<<"\n";
#else
    if(!tie) check(x.is_tree(best),"different score exact ranking");
#endif
    check(x.cand_size()==0,"candidate table clear");
}
static void sx08() {
    ranking<I<Arm::Fixed,128>>(false); ranking<I<Arm::Fixed,128>>(true);
    ranking<I<Arm::Event,16>>(false); ranking<I<Arm::Event,16>>(true);
    ranking<I<Arm::Cost>>(false); ranking<I<Arm::Cost>>(true);
}
// External, test-only audit. Every actual API is checked; only conversion APIs
// are logged. No fields/hooks are added to Index and owner tracking is inactive.
template<class T> class ApiAudit {
    struct Snapshot {
        std::uint64_t epoch,ops,up,scheduled,cleanup,total;
        std::size_t trees;
    };
    T& x_; const char* fixture_;
    std::uint64_t ordinal_=0,quota_epoch_=0,epoch_up_=0,epoch_scheduled_=0,conversion_apis_=0;
    Snapshot snapshot() const {
        return {x_.epoch(),x_.ops_in_epoch(),x_.promotions(),x_.scheduled_demotions(),
                x_.cleanup_demotions(),x_.total_demotions(),x_.tree_count()};
    }
    template<class F> void api(const char* kind,bool structural,F&& operation) {
        const auto before=snapshot(); ++ordinal_; operation(); const auto after=snapshot();
        check(before.total==before.scheduled+before.cleanup && after.total==after.scheduled+after.cleanup,"SX09 each API demotion identity");
        check(after.up>=before.up && after.scheduled>=before.scheduled && after.cleanup>=before.cleanup && after.total>=before.total,"SX09 each API counter monotonicity");
        const auto up=after.up-before.up,scheduled=after.scheduled-before.scheduled;
        const auto cleanup=after.cleanup-before.cleanup,total=after.total-before.total;
        check(total==scheduled+cleanup,"SX09 each API exact scheduled/cleanup delta attribution");
        check(after.epoch==before.epoch+(structural && before.ops==511),"SX09 actual API epoch boundary");
        check(after.ops==(structural?(before.ops+1)%512:before.ops),"SX09 each API exact structural clock");
        check((up==0 && scheduled==0) || (structural && after.epoch==before.epoch+1 && after.ops==0),"SX09 promotion/scheduled belongs to actual boundary API");
        check(cleanup<=1 && (cleanup==0 || kind[0]=='e'),"SX09 cleanup belongs to one actual erase API");
        if(quota_epoch_!=after.epoch) { quota_epoch_=after.epoch; epoch_up_=epoch_scheduled_=0; }
        epoch_up_+=up; epoch_scheduled_+=scheduled;
        check(epoch_up_<=1 && epoch_scheduled_<=1,"SX09 every epoch at most one promotion and scheduled demotion");
        check(after.trees<=32 && after.trees+scheduled+cleanup==before.trees+up,"SX09 each API tree budget/count reconciliation");
        if(up || scheduled || cleanup) {
            ++conversion_apis_;
            std::cout<<"SX09_API fixture="<<fixture_<<" arm="<<int(T::arm)<<" api="<<ordinal_
                     <<" kind="<<kind<<" epoch_before="<<before.epoch<<" epoch_after="<<after.epoch
                     <<" ops_before="<<before.ops<<" ops_after="<<after.ops<<" promotion_delta="<<up
                     <<" scheduled_delta="<<scheduled<<" cleanup_delta="<<cleanup<<" total_down_delta="<<total<<"\n";
        }
    }
public:
    ApiAudit(T& x,const char* fixture):x_(x),fixture_(fixture),quota_epoch_(x.epoch()) {
        check(!kernel_alloc::active,"SX09 external audit runs outside owner tracking");
    }
    void erase(Record r) { api("erase",true,[&]{x_.erase(r);}); }
    void range(std::uint64_t lo,std::uint64_t hi,std::size_t expected) {
        api("range",false,[&]{auto out=x_.range(lo,hi);check(out.size()==expected,"SX09 audited range exact output");});
    }
    void heat(std::size_t slot,std::size_t n,std::size_t observations=200) {
        for(std::size_t j=0;j<observations;++j) range(key(slot,n/2).first,key(slot,n/2).first+1,1);
    }
    void finish_epoch(std::size_t filler=4095) {
        const auto epoch=x_.epoch(); do {erase(key(filler,100000));} while(x_.epoch()==epoch);
    }
    void promote(std::size_t slot,std::size_t n) {
        heat(slot,n);erase(key(slot,n+1));finish_epoch();check(x_.is_tree(slot),"SX09 audited legal promotion");
    }
    void summary() const {
        std::cout<<"SX09_AUDIT fixture="<<fixture_<<" arm="<<int(T::arm)<<" checked_APIs="<<ordinal_
                 <<" conversion_APIs="<<conversion_apis_<<" promotions="<<x_.promotions()
                 <<" scheduled="<<x_.scheduled_demotions()<<" cleanup="<<x_.cleanup_demotions()
                 <<" total_down="<<x_.total_demotions()<<"\n";
    }
};
template<class T> static void budget() {
    MemoryAccounts m; T x(domain,params(),m); x.build(initial(128,33)); ApiAudit<T> audit(x,"budget");
    for(std::size_t round=0;round<33;++round) {
        const auto up=x.promotions(),down=x.scheduled_demotions();
        for(std::size_t s=0;s<33;++s) { audit.heat(s,128); audit.erase(key(s,129)); }
        audit.finish_epoch();
        check(x.promotions()-up<=1 && x.scheduled_demotions()-down<=1,"epoch1up1scheduled");
        check(x.tree_count()<=32 && x.total_demotions()==x.scheduled_demotions()+x.cleanup_demotions(),"K32 and demotion equation");
    }
    check(x.tree_count()==32 && x.promotions()==32 && x.scheduled_demotions()==0,"budget full no hot eviction");
    audit.summary();
}
template<class T> static void cleanup_quota() {
    MemoryAccounts m; T x(domain,params(),m); x.build(initial(128,3)); ApiAudit<T> audit(x,"cleanup_quota");
    for(std::size_t s=0;s<3;++s) { for(std::size_t t=0;t<s;++t) audit.range(key(t,64).first,key(t,64).first+1,1); audit.promote(s,128); }
    while(x.epoch()<10) {
        audit.range(64,65,1); audit.range(key(1,64).first,key(1,64).first+1,1); audit.finish_epoch();
    }
    check(x.is_tree(0) && x.is_tree(1) && x.is_tree(2),"three trees survive to quota fixture");
    const auto sched=x.scheduled_demotions(),clean=x.cleanup_demotions();
    for(std::size_t s=0;s<2;++s) for(std::size_t r=1;r<=128;++r) {
        const auto before=x.cleanup_demotions(),epoch=x.epoch(); audit.erase(key(s,r));
        check(x.cleanup_demotions()==before+(r==128),"SX09 each final erase independently adds exactly one cleanup");
        check(x.epoch()==epoch && x.scheduled_demotions()==sched,"SX09 two actual cleanup erases do not use scheduled quota");
    }
    check(x.cleanup_demotions()==clean+2,"multiple immediate cleanup in same epoch"); audit.finish_epoch();
    if constexpr(T::arm==Arm::NoIdle) check(x.scheduled_demotions()==sched,"NoIdle no nonexistent demotion branch");
    else check(x.scheduled_demotions()==sched+1,"scheduled still has quota after two cleanups");
    check(x.total_demotions()==x.scheduled_demotions()+x.cleanup_demotions(),"cleanup exact equation");
    audit.summary();
}
static void sx09() {
    budget<I<Arm::Fixed,128>>(); budget<I<Arm::Event,16>>(); budget<I<Arm::Cost>>(); budget<I<Arm::NoIdle>>();
    cleanup_quota<I<Arm::Fixed,128>>(); cleanup_quota<I<Arm::Event,16>>(); cleanup_quota<I<Arm::Cost>>(); cleanup_quota<I<Arm::NoIdle>>();
}
template<class T> static void idle_and_cool() {
    MemoryAccounts m; T x(domain,params(),m); const auto v=initial(256); x.build(v); promote(x,0,256);
    check(x.epoch()==1 && x.cooldown_until_epoch_of(0)==9,"promotion C8");
    for(std::size_t j=0;j<100;++j) x.range(128,129);
    check(x.epoch()==1 && x.ops_in_epoch()==0,"only ranges stop clock");
    while(x.epoch()<8) { finish_epoch(x); check(x.is_tree(0),"tree cannot demote before cool8"); }
    finish_epoch(x);
    check(!x.is_tree(0) && x.scheduled_demotions()==1 && x.bucket_size(0)==256,"idle nonempty scheduled demotion at cool end");
    check(x.values()==v && x.cooldown_until_epoch_of(0)==17,"demotion preserves content C8");
    while(x.epoch()<17) {
        heat(x,0,256); x.erase(key(0,257)); check(x.cand_size()==0,"re-promotion prohibited before cool end"); finish_epoch(x);
        check(!x.is_tree(0),"cooling stays LIST");
    }
    heat(x,0,256); x.erase(key(0,257)); check(x.cand_size()==1,"eligible at cooldown end after legal touch");
    finish_epoch(x); check(x.is_tree(0) && x.promotions()==2 && x.values()==v,"demotion then lawful candidate re-entry/re-promotion");
}
static void sx10() { idle_and_cool<I<Arm::Cost>>(); idle_and_cool<I<Arm::Event,16>>(); idle_and_cool<I<Arm::Fixed,128>>(); }
static void noidle_cleanup_and_reupgrade() {
    MemoryAccounts m; I<Arm::NoIdle> x(domain,params(),m); const auto v=initial(256); x.build(v); promote(x,0,256);
    while(x.epoch()<9) finish_epoch(x);
    check(x.is_tree(0) && x.scheduled_demotions()==0,"SX11 NoIdle tree survives idle until actual cleanup");
    const auto cleanup_epoch=x.epoch();
    for(std::size_t row=1;row<=256;++row) x.erase(key(0,row));
    check(!x.is_tree(0) && x.size()==0 && x.cleanup_demotions()==1 && x.total_demotions()==1 && x.scheduled_demotions()==0,"SX11 NoIdle actual empty-tree cleanup");
    const auto cooldown=x.cooldown_until_epoch_of(0);
    check(cooldown==cleanup_epoch+8,"SX11 NoIdle cleanup starts exact C8");
    for(std::size_t row=1;row<=256;++row) {
        x.insert(key(0,row));
        check(x.epoch()<cooldown && x.cand_size()==0 && !x.is_tree(0) && x.promotions()==1,"SX11 NoIdle refill remains blocked inside C8");
    }
    check(x.bucket_size(0)==256 && x.values()==v,"SX11 NoIdle refill above min preserves complete records");
    while(x.epoch()<cooldown) {
        heat(x,0,256); x.erase(key(0,257));
        check(x.cand_size()==0 && !x.is_tree(0),"SX11 NoIdle heated structural touch cannot register before C8");
        finish_epoch(x);
        check(!x.is_tree(0) && x.promotions()==1 && x.cand_size()==0,"SX11 NoIdle C8 expiry alone does not register/promote");
    }
    heat(x,0,256); check(x.cand_size()==0,"SX11 NoIdle range at C8 end only observes");
    x.erase(key(0,257)); check(x.cand_size()==1,"SX11 NoIdle legal structure at C8 end registers candidate");
    finish_epoch(x);
    check(x.is_tree(0) && x.promotions()==2 && x.cleanup_demotions()==1 && x.scheduled_demotions()==0 && x.values()==v,"SX11 NoIdle cleanup then legal re-promotion");
    std::cout<<"SX11 NoIdle_cleanup_reupgrade PASS cleanup_epoch="<<cleanup_epoch<<" cooldown_end="<<cooldown<<" reupgrade_epoch="<<x.epoch()<<" promotions="<<x.promotions()<<" cleanup="<<x.cleanup_demotions()<<" scheduled="<<x.scheduled_demotions()<<"\n";
}
static void sx11() { noidle_cleanup_and_reupgrade(); sx10(); }
static void sx12() {
    MemoryAccounts a,b,c; pbadaptive::Index r(domain,params(),a); I<Arm::Cost> d(domain,params(),b); I<Arm::NoIdle> n(domain,params(),c);
    auto v=initial(256); r.build(v); d.build(v); n.build(v);
    for(std::size_t j=0;j<200;++j) { r.range(128,129); d.range(128,129); n.range(128,129); }
    r.erase(key(0,257)); d.erase(key(0,257)); n.erase(key(0,257));
    finish_epoch(r); finish_epoch(d); finish_epoch(n);
    check(r.is_tree(0) && d.is_tree(0) && n.is_tree(0),"no-tie all promote");
    for(std::size_t epoch=1;epoch<5;++epoch) {
        r.range(128,129); d.range(128,129); n.range(128,129); finish_epoch(r); finish_epoch(d); finish_epoch(n);
        check(r.values()==d.values() && d.values()==n.values(),"no-idle full content trajectory");
        check(r.epoch()==d.epoch() && r.promotions()==d.promotions() && r.total_avoidable_work()==d.total_avoidable_work() && r.scheduled_demotions()==d.scheduled_demotions(),"R6 diagnostic Cost identical counters no tie");
        check(n.epoch()==d.epoch() && n.promotions()==d.promotions() && n.tree_count()==d.tree_count() && n.nodes_allocated()==d.nodes_allocated() && n.total_avoidable_work()==d.total_avoidable_work() && n.gate_hits()==d.gate_hits() && n.cand_size()==d.cand_size() && n.cooldown_until_epoch_of(0)==d.cooldown_until_epoch_of(0),"NoIdle no-idle path identical policy/counter trajectory");
        near(r.gain_ns_of(0),d.gain_ns_of(0),"R6 Cost exact credit");
    }
    while(r.epoch()<13) { finish_epoch(r); finish_epoch(d); finish_epoch(n); }
    check(!r.is_tree(0) && !d.is_tree(0) && n.is_tree(0) && n.scheduled_demotions()==0,"NoIdle unique ordinary demotion off");
    for(std::size_t row=1;row<=256;++row) n.erase(key(0,row));
    check(!n.is_tree(0) && n.cleanup_demotions()==1 && n.total_demotions()==1,"NoIdle retains empty cleanup");
    n.insert(key(0,1)); n.insert(key(0,2)); n.range(2,3);
    const auto cool=n.cooldown_until_epoch_of(0); check(cool>=21,"NoIdle cleanup still C8");
    for(std::size_t j=0;j<4;++j) finish_epoch(n);
    n.range(0,1); near(n.gain_ns_of(0),-params().tree_cost[0][2],"NoIdle retains lazy idle credit reset");
}
#ifdef INDEX_FAILURE_TEST
template<class T> static void promotion_failure(bool manager,int prefix) {
    MemoryAccounts m; T x(domain,params(),m); auto v=initial(256); x.build(v); heat(x,0,256);
    x.erase(key(0,257)); while(x.ops_in_epoch()<511) x.erase(key(4095,1));
    const auto gain=x.gain_ns_of(0); const auto last=x.last_sensitive_epoch_of(0),cool=x.cooldown_until_epoch_of(0);
    auto& account=manager?m.manager:m.tree; account.fail_after=prefix;
    const auto bytes=m.current(); x.erase(key(0,257)); account.fail_after=-1;
    check(x.epoch()==1 && x.ops_in_epoch()==0 && x.conversion_failures()==1,"conversion preparation failure does not roll structural epoch back");
    check(!x.is_tree(0) && x.values()==v && x.cand_size()==0,"failed promotion preserves LIST contents and clears candidates");
    const double expected=T::arm==Arm::Fixed?0:T::arm==Arm::Event?gain:gain-params().tree_cost[1][1];
    near(x.gain_ns_of(0),expected,"failed promotion credit only reflects completed content observation");
    check(x.last_sensitive_epoch_of(0)==last && x.cooldown_until_epoch_of(0)==cool && m.current()==bytes,"failed promotion leaves sensitivity/cooldown/account unchanged");
    promote(x,0,256); check(x.promotions()==1,"failed promotion legal retry");
}
template<class T> static void demotion_failure(int successful_grows) {
    MemoryAccounts m; T x(domain,params(),m); auto v=initial(2048); x.build(v); promote(x,0,2048);
    // Consume every recycled node using sub-min-size cold buckets, preventing any second tree.
    for(std::size_t r=0;r<2048;++r) x.insert(key(1+r/127,1+r%127));
    while(x.epoch()<8) finish_epoch(x);
    while(x.ops_in_epoch()<511) x.erase(key(4095,1));
    const auto old=x.values(); const auto capacity=x.nodes_allocated(); const auto gain=x.gain_ns_of(0); const auto sensitive=x.last_sensitive_epoch_of(0),cool=x.cooldown_until_epoch_of(0);
    m.pool.fail_after=successful_grows; x.erase(key(4095,1)); m.pool.fail_after=-1;
    check(x.epoch()==9 && x.conversion_failures()==1 && x.is_tree(0) && x.values()==old,"failed demotion preserves TREE content at advanced epoch");
    check(x.nodes_allocated()==capacity+1024*successful_grows,"successful pool grow before failed demotion may remain");
    near(x.gain_ns_of(0),gain,"failed demotion credit unchanged");
    check(x.last_sensitive_epoch_of(0)==sensitive && x.cooldown_until_epoch_of(0)==cool,"failed demotion sensitivity/cooldown unchanged");
    finish_epoch(x); check(!x.is_tree(0) && x.scheduled_demotions()==1 && x.values()==old,"failed demotion legal retry");
}
static void sx13() {
#define FAIL(A,T) promotion_failure<I<Arm::A,T>>(true,0); promotion_failure<I<Arm::A,T>>(false,0); promotion_failure<I<Arm::A,T>>(false,7);
    FAIL(Fixed,128) FAIL(Event,16) FAIL(NoIdle,0) FAIL(Cost,0)
#undef FAIL
    demotion_failure<I<Arm::Fixed,128>>(0); demotion_failure<I<Arm::Fixed,128>>(1);
    demotion_failure<I<Arm::Event,16>>(0); demotion_failure<I<Arm::Event,16>>(1);
    demotion_failure<I<Arm::Cost>>(0); demotion_failure<I<Arm::Cost>>(1);
    // NoIdle has no ordinary demotion branch: never inject or claim it was tested.
}
template<class T> static void failures() {
    for(int prefix=0;prefix<67;++prefix) {
        MemoryAccounts m; kernel_alloc::reset(); kernel_alloc::active=true; kernel_alloc::fail_after=prefix;
        bool caught=false; try { T x(domain,params(),m); } catch(const std::bad_alloc&) {caught=true;}
        kernel_alloc::fail_after=-1; kernel_alloc::active=false;
        check(caught && kernel_alloc::current==0 && m.current()==0,"each actual constructor allocation prefix releases owners");
    }
    MemoryAccounts m; T x(domain,params(),m); m.pool.fail_after=0;
    bool caught=false; try{x.insert(key(0,1));}catch(const std::bad_alloc&){caught=true;} m.pool.fail_after=-1;
    check(caught && x.size()==0 && x.epoch()==0 && x.ops_in_epoch()==0 && x.gain_ns_of(0)==0,"first content grow failure no clock/observation");
    m.manager.fail_after=0; caught=false; try{x.insert(key(0,1));}catch(const std::bad_alloc&){caught=true;}m.manager.fail_after=-1;
    check(caught && m.pool.current==0 && x.nodes_allocated()==0 && x.size()==0,"grow chunks allocation rollback");
    x.insert(key(0,1));
    for(std::size_t r=2;r<=1024;++r) x.insert(key(0,r));
    const auto before=x.values(); const auto oldops=x.ops_in_epoch(),olde=x.epoch(),oldwork=x.total_avoidable_work(); const auto gain=x.gain_ns_of(0);
    m.pool.fail_after=0; caught=false;try{x.insert(key(0,1025));}catch(const std::bad_alloc&){caught=true;}m.pool.fail_after=-1;
    check(caught && x.values()==before && x.ops_in_epoch()==oldops && x.epoch()==olde && x.total_avoidable_work()==oldwork && x.gain_ns_of(0)==gain,"pool exhaustion insert failure no commit/clock/observation");
    // Actual std::vector output failures at several successfully allocated prefixes.
    for(int prefix=0;prefix<4;++prefix) {
        const auto g=x.gain_ns_of(0); const auto sens=x.last_sensitive_epoch_of(0),work=x.total_avoidable_work(),last=x.last_work();
        kernel_alloc::fail_after=prefix; caught=false;
        try{auto out=x.range(128,512); (void)out;}catch(const std::bad_alloc&){caught=true;}
        kernel_alloc::fail_after=-1;
        check(caught && x.gain_ns_of(0)==g && x.last_sensitive_epoch_of(0)==sens && x.total_avoidable_work()==work && x.last_work()==last,"partial output failure commits no observation");
        check(x.values()==before && x.ops_in_epoch()==oldops && x.epoch()==olde,"output failure content/clock unchanged");
    }
    MemoryAccounts bm; T b(domain,params(),bm); bm.pool.fail_after=0; caught=false;
    try{b.build(initial(128));}catch(const std::bad_alloc&){caught=true;}bm.pool.fail_after=-1;
    check(caught && b.size()==0 && b.epoch()==0 && b.ops_in_epoch()==0 && b.nodes_allocated()==0,"bulk initial pool failure");
}
static void sx14() { failures<I<Arm::List>>();failures<I<Arm::ObserveList>>();failures<I<Arm::Fixed,8192>>();failures<I<Arm::Event,64>>();failures<I<Arm::NoIdle>>(); }
#endif
#ifdef ADAPTIVE_ALLOC_TRACK
template<class T> static void owner() {
    auto v=initial(256); MemoryAccounts m; kernel_alloc::reset(); kernel_alloc::active=true;
    {
        T x(domain,params(),m); x.build(v);
        check(kernel_alloc::current==m.current(),"four independent accounts sum equals global live Index heap");
        check(m.buckets.current==4096*64 && m.pool.current==256*32 && m.manager.current>0,"bucket pool manager account requests");
        if constexpr(T::arm!=Arm::List && T::arm!=Arm::ObserveList) {
            heat(x,0,256); x.erase(key(0,257)); finish_epoch(x); check(m.tree.current>0,"independent tree account");
        }
        check(kernel_alloc::current==m.current(),"promotion persistent owner equality");
        const auto persistent=m.current();
        {
            auto output=x.range(0,257);
            check(output.size()==256 && kernel_alloc::current==persistent+output.capacity()*sizeof(Record),"whole current includes output requested bytes simultaneously");
            check(kernel_alloc::peak>=kernel_alloc::current,"whole peak includes temporary output");
        }
        check(kernel_alloc::current==m.current(),"output destructor returns to persistent bytes");
        check(x.memory_bytes()==sizeof(T)+m.current(),"memory_bytes includes stack Index plus accounts");
    }
    kernel_alloc::active=false;
    check(kernel_alloc::current==0 && m.current()==0 && kernel_alloc::allocations==kernel_alloc::frees,"Index destruction owner zero");
    for(const auto* a:{&m.pool,&m.buckets,&m.tree,&m.manager}) check(a->current==0 && a->allocations==a->frees,"each account destruction independently zero");
    std::size_t live=0,peak=0;
    for(std::size_t j=0;j<kernel_alloc::used;++j) {
        const auto e=kernel_alloc::entries[j]; if(e.allocation)live+=e.bytes;else live-=e.bytes; peak=std::max(peak,live);
    }
    check(live==0 && peak==kernel_alloc::peak,"whole peak exact event replay, never account peak sum");
    check(kernel_alloc::peak>m.pool.peak+m.buckets.peak+m.tree.peak+m.manager.peak,"temporary output demonstrates whole peak differs from sum of four peaks");
}
static void sx15() {
    owner<I<Arm::List>>();owner<I<Arm::ObserveList>>();owner<I<Arm::Fixed,128>>();owner<I<Arm::Event,16>>();owner<I<Arm::Cost>>();owner<I<Arm::NoIdle>>();
    struct NativeR6 : pbadaptive::Index { using pbadaptive::Index::Index; static constexpr Arm arm_value() {return Arm::Cost;} };
    // Direct frozen production R6 is also independently owned; no new R6 fields/getters.
    MemoryAccounts native; auto nv=initial(256); kernel_alloc::reset();kernel_alloc::active=true;
    { NativeR6 r(domain,params(),native);r.build(nv);promote(r,0,256);check(kernel_alloc::current==native.current(),"native R6 owner/account equality"); }
    kernel_alloc::active=false;check(kernel_alloc::current==0 && native.current()==0,"native R6 destructor owner zero");
    auto v=initial(256); kernel_alloc::reset(); kernel_alloc::active=true;
    { pubbench::PoolIndex<false> x(domain); x.build(v); auto out=x.range(0,257); check(kernel_alloc::current>0 && out==v,"Original independent whole owner; four accounts NA"); }
    kernel_alloc::active=false; check(kernel_alloc::current==0,"Original destruction zero");
}
#endif
static int run(const std::string& id) {
    try {
        if(id=="SX01")sx01();else if(id=="SX02")sx02();else if(id=="SX04")sx04();else if(id=="SX05")sx05();
        else if(id=="SX06")sx06();else if(id=="SX07")sx07();else if(id=="SX08")sx08();else if(id=="SX09")sx09();
        else if(id=="SX10")sx10();else if(id=="SX11")sx11();else if(id=="SX12")sx12();
#ifdef INDEX_FAILURE_TEST
        else if(id=="SX13")sx13();else if(id=="SX14")sx14();
#endif
#ifdef ADAPTIVE_ALLOC_TRACK
        else if(id=="SX15")sx15();
#endif
        else {std::cout<<id<<" SKIP requires dedicated mode\n";return 0;}
        std::cout<<id<<" PASS\n";return 0;
    } catch(const std::exception& e) { kernel_alloc::fail_after=-1; kernel_alloc::active=false; std::cout<<id<<" FAIL assertion: "<<e.what()<<"\n";return 1; }
}
int main(int argc,char** argv) {
    if(argc==4 && std::string(argv[1])=="--random") {
        try {
            const std::string a=argv[2]; const auto seed=std::stoull(argv[3]);
            if(a=="List")random_test<I<Arm::List>>(seed);else if(a=="ObserveList")random_test<I<Arm::ObserveList>>(seed);
            else if(a=="Fixed")random_test<I<Arm::Fixed,512>>(seed);else if(a=="Event")random_test<I<Arm::Event,16>>(seed);
            else if(a=="NoIdle")random_test<I<Arm::NoIdle>>(seed);else throw std::invalid_argument("random arm");
            std::cout<<"SX03 PASS\n";return 0;
        }catch(const std::exception& e){std::cout<<"SX03 FAIL assertion: "<<e.what()<<"\n";return 1;}
    }
    if(argc==3 && std::string(argv[1])=="--case") return run(argv[2]);
    int failures=0;for(auto id:{"SX01","SX02","SX04","SX05","SX06","SX07","SX08","SX09","SX10","SX11","SX12","SX13","SX14","SX15"})failures+=run(id);
    return failures?1:0;
}
