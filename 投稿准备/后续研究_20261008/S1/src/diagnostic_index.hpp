#pragma once
#ifndef S0_EVENT_TRACE
#error Diagnostic header requires S0_EVENT_TRACE; native must include matched_index.hpp only
#endif
#include "matched_index.hpp"
#include "../../../adaptive_poolhbi/final/adaptive_types.hpp"
#ifdef ADAPTIVE_ABLATION
#error Matched production policies require frozen non-ablation Params
#endif
#include <functional>
#include <limits>
namespace diagnostic {
using pbadaptive::Record; using pbadaptive::Domain; using pbadaptive::Params;
using pbadaptive::MemoryAccounts; using pbadaptive::Alloc; using pbadaptive::Op;
using matched::Arm;
// Diagnostic copy only. External TLS has no representation or policy fields.
enum class EventType { Promotion, ScheduledDemotion, Cleanup };
struct Event {
    std::uint64_t api_ordinal,epoch;
    std::size_t slot,n;
    EventType type;
    std::uint64_t body_ns;
};
using EventSink=void(*)(const Event&) noexcept;
inline thread_local EventSink event_sink=nullptr;
inline thread_local std::uint64_t api_ordinal=0;
struct ObservationCounters {
    std::uint64_t list_work=0,range_buffers=0,epoch_scans=0,candidate_visits=0;
};
inline thread_local ObservationCounters observation_counters{};
inline void reset_observation_counters() noexcept { observation_counters={}; }
inline void set_event_sink(EventSink sink) noexcept { event_sink=sink; }
inline void set_api_ordinal(std::uint64_t ordinal) noexcept { api_ordinal=ordinal; }

// Generated matched policies. Production R6 remains in its original header.
template<Arm A, std::size_t Threshold=0> class Index {
    static_assert(A!=Arm::Fixed || Threshold==128 || Threshold==512 || Threshold==2048 || Threshold==8192,"registered fixed threshold");
    static_assert(A!=Arm::Event || Threshold==8 || Threshold==16 || Threshold==32 || Threshold==64,"registered event threshold");
    struct Node { Record key; Node* prev=nullptr; Node* next=nullptr; };
    using Tree=std::multiset<Record,std::less<Record>,Alloc<Record>>;
    struct Adaptive {
        double gain=0;
        std::uint64_t last_sensitive=0,cooldown_until=0;
        bool in_cooldown=false,in_cand=false;
    };
    struct Bucket {
        Node* head=nullptr; Node* tail=nullptr; Tree* tree=nullptr;
        std::size_t n=0; Adaptive adaptive;
    };
    struct Chunk { Node* data; std::size_t count; };
    static_assert(sizeof(Node)==32,"v4 node layout");
    static_assert(sizeof(Adaptive)==32 && sizeof(Bucket)==64,"v4 bucket layout");
    Domain domain_; Params p_; MemoryAccounts& mem_;
    std::array<Bucket*,64> roots_{};
    std::vector<Bucket*,Alloc<Bucket*>> tree_list_,cand_,cooldown_list_;
    std::vector<Chunk,Alloc<Chunk>> chunks_;
    Node* free_=nullptr; Node* unused_=nullptr;
    std::size_t unused_count_=0,nodes_allocated_=0,size_=0,tree_count_=0;
    std::size_t peak_trees_=0,last_candidates_=0,max_candidates_=0;
    std::uint64_t epoch_=0,ops_=0,promotions_=0,scheduled_down_=0,cleanup_down_=0,total_down_=0;
    std::uint64_t gate_hits_=0,last_work_=0,total_work_=0,up_ns_=0,down_ns_=0,failures_=0;
    bool fresh_=true,building_=false;
    using Clock=std::chrono::steady_clock;
    static std::uint64_t elapsed(Clock::time_point t) noexcept {
        return static_cast<std::uint64_t>(std::chrono::duration_cast<std::chrono::nanoseconds>(Clock::now()-t).count());
    }
    Bucket& bucket(std::size_t slot) {
        if(slot>=4096) throw std::out_of_range("bucket slot");
        return roots_[slot/64][slot%64];
    }
    const Bucket& bucket(std::size_t slot) const {
        if(slot>=4096) throw std::out_of_range("bucket slot");
        return roots_[slot/64][slot%64];
    }
    static std::size_t cost_class(std::size_t n) noexcept {
        int log=0;
        for(std::size_t v=n>1?n-1:0;v;v>>=1) ++log;
        return static_cast<std::size_t>(std::min(std::max(log-7,0),9));
    }
    double conversion(const Bucket& b) const noexcept { return p_.conversion_base_ns+p_.conversion_ns_per_record*double(b.n); }
    bool cool(const Bucket& b) const noexcept { return !p_.cooldown_enabled || epoch_>=b.adaptive.cooldown_until; }
    bool resource_ok(const Bucket& b) const noexcept { return !p_.max_convert_records || b.n<=p_.max_convert_records; }
    bool paid(const Bucket& b) const noexcept {
        if constexpr(A==Arm::List || A==Arm::ObserveList) return false;
        else if constexpr(A==Arm::Fixed) return b.n>=Threshold;
        else if constexpr(A==Arm::Event) return b.adaptive.gain>=double(Threshold);
        else return b.adaptive.gain>=p_.payback*conversion(b);
    }
    bool eligible(const Bucket& b) const noexcept { return !b.tree && b.n>=p_.min_tree_size && cool(b) && paid(b); }
    void register_candidate(Bucket& b) {
        if constexpr(A!=Arm::List && A!=Arm::ObserveList) {
            if(!eligible(b)) return;
            ++gate_hits_;
            if(!b.adaptive.in_cand) { cand_.push_back(&b); b.adaptive.in_cand=true; }
        }
    }
    void observe_list(Bucket& b,Op op,std::uint64_t work,bool sensitive,bool structural) {
        if constexpr(A==Arm::List) observation_counters.list_work+=work;
        if constexpr(A!=Arm::List) {
            auto& a=b.adaptive;
            if(epoch_-a.last_sensitive>=p_.down_idle_epochs) a.gain=0;
            if constexpr(A==Arm::Fixed) a.gain=0;
            else if constexpr(A==Arm::Event) a.gain+=work>0?1.0:0.0;
            else a.gain+=p_.scan_ns_per_work*double(work)-p_.tree_cost[cost_class(b.n)][static_cast<std::size_t>(op)];
            total_work_+=work;
            if(sensitive) a.last_sensitive=epoch_;
            if(structural) register_candidate(b);
        }
    }
    void reset_conversion(Bucket& b) {
        auto& a=b.adaptive; a.gain=0; a.last_sensitive=epoch_;
        if(p_.cooldown_enabled) {
            a.cooldown_until=epoch_+2*p_.down_idle_epochs;
            if(!a.in_cooldown) { cooldown_list_.push_back(&b); a.in_cooldown=true; }
        }
    }
    static void swap_remove(std::vector<Bucket*,Alloc<Bucket*>>& list,Bucket* b) noexcept {
        auto it=std::find(list.begin(),list.end(),b);
        assert(it!=list.end()); *it=list.back(); list.pop_back();
    }
    void grow(std::size_t count) {
        Alloc<Node> alloc(mem_.pool); Node* data=alloc.allocate(count);
        std::size_t constructed=0;
        try {
            for(;constructed<count;++constructed) std::allocator_traits<Alloc<Node>>::construct(alloc,data+constructed);
            chunks_.push_back({data,count});
        } catch(...) {
            while(constructed) std::allocator_traits<Alloc<Node>>::destroy(alloc,data+--constructed);
            alloc.deallocate(data,count); throw;
        }
        unused_=data; unused_count_=count; nodes_allocated_+=count;
    }
    Node* node(Record key,Node* prev,Node* next) {
        Node* q;
        if(free_) { q=free_; free_=free_->next; }
        else {
            if(!unused_count_) grow(1024);
            q=unused_++; --unused_count_;
        }
        q->key=key; q->prev=prev; q->next=next; return q;
    }
    void recycle(Node* q) noexcept { q->next=free_; q->prev=nullptr; free_=q; }
    void recycle_chain(Node* q) noexcept { while(q) { auto next=q->next; recycle(q); q=next; } }
    static Node* lower(Bucket& b,Record key,std::uint64_t& work) noexcept {
        if(!b.head || b.tail->key<key) return nullptr;
        Node* left=b.head; Node* right=b.tail;
        for(;;) {
            if(!(left->key<key)) return left;
            if(right->key<key) return right->next;
            if(left==right) return left;
            if(left->next==right) return right;
            left=left->next; right=right->prev; work+=2;
        }
    }
    Tree* make_tree() {
        Alloc<Tree> alloc(mem_.manager); Tree* t=alloc.allocate(1);
        try { std::allocator_traits<Alloc<Tree>>::construct(alloc,t,std::less<Record>{},Alloc<Record>(mem_.tree)); }
        catch(...) { alloc.deallocate(t,1); throw; }
        return t;
    }
    void destroy_tree(Tree* t) noexcept {
        Alloc<Tree> alloc(mem_.manager);
        std::allocator_traits<Alloc<Tree>>::destroy(alloc,t); alloc.deallocate(t,1);
    }
    void emit_conversion(const Bucket& b,EventType type,std::uint64_t ns) const noexcept {
        if(!event_sink) return;
        for(std::size_t r=0;r<64;++r) for(std::size_t j=0;j<64;++j)
            if(roots_[r]+j==&b) { event_sink({api_ordinal,epoch_,r*64+j,b.n,type,ns}); return; }
    }
    void promote_bucket(Bucket& b) {
        const auto start=Clock::now(); Tree* stage=make_tree();
        try { for(Node* q=b.head;q;q=q->next) stage->insert(stage->end(),q->key); }
        catch(...) { destroy_tree(stage); throw; }
        recycle_chain(b.head); b.head=b.tail=nullptr; b.tree=stage;
        tree_list_.push_back(&b); ++tree_count_; peak_trees_=std::max(peak_trees_,tree_count_);
        reset_conversion(b); ++promotions_; const auto body_ns=elapsed(start); up_ns_+=body_ns; emit_conversion(b,EventType::Promotion,body_ns);
    }
    void demote_bucket(Bucket& b) {
        const auto start=Clock::now(); Node* head=nullptr; Node* tail=nullptr;
        try {
            for(const auto& key:*b.tree) {
                Node* q=node(key,tail,nullptr);
                if(tail) tail->next=q; else head=q;
                tail=q;
            }
        } catch(...) { recycle_chain(head); throw; }
        Tree* old=b.tree; b.tree=nullptr; b.head=head; b.tail=tail;
        swap_remove(tree_list_,&b); --tree_count_; destroy_tree(old);
        reset_conversion(b); ++scheduled_down_; ++total_down_; const auto body_ns=elapsed(start); down_ns_+=body_ns; emit_conversion(b,EventType::ScheduledDemotion,body_ns);
    }
    void cleanup_empty_tree(Bucket& b) noexcept {
        const auto start=Clock::now(); assert(b.tree && b.n==0 && b.tree->empty());
        Tree* old=b.tree; b.tree=nullptr;
        swap_remove(tree_list_,&b); --tree_count_; destroy_tree(old);
        reset_conversion(b); ++cleanup_down_; ++total_down_; const auto body_ns=elapsed(start); down_ns_+=body_ns; emit_conversion(b,EventType::Cleanup,body_ns);
    }
    bool better(const Bucket* a,const Bucket* b) const noexcept {
        if(!b) return true;
        if constexpr(A==Arm::Fixed) {
            if(a->n!=b->n) return a->n>b->n;
        } else if constexpr(A==Arm::Event) {
            if(a->adaptive.gain!=b->adaptive.gain) return a->adaptive.gain>b->adaptive.gain;
        } else {
            const double ra=a->adaptive.gain/conversion(*a),rb=b->adaptive.gain/conversion(*b);
            if(ra!=rb) return ra>rb;
            if(a->adaptive.gain!=b->adaptive.gain) return a->adaptive.gain>b->adaptive.gain;
        }
        return std::less<const Bucket*>{}(a,b);
    }
    void validate_bucket(const Bucket& b) const noexcept {
        assert(!(b.head && b.tree)); assert((b.head==nullptr)==(b.tail==nullptr));
        assert(b.tree==nullptr || b.n>0); assert(b.n!=0 || (!b.head && !b.tree)); (void)b;
    }
    void validate() const noexcept {
#ifndef NDEBUG
        assert(tree_count_==tree_list_.size() && tree_count_<=p_.tree_budget);
        assert(total_down_==scheduled_down_+cleanup_down_ && cand_.size()<=4096);
        std::size_t trees=0,candidates=0,cooling=0;
        for(auto root:roots_) for(std::size_t j=0;j<64;++j) {
            const auto& b=root[j]; validate_bucket(b);
            trees+=b.tree!=nullptr; candidates+=b.adaptive.in_cand; cooling+=b.adaptive.in_cooldown;
        }
        assert(trees==tree_list_.size() && candidates==cand_.size() && cooling==cooldown_list_.size());
        // Debug-only membership audit; no allocation, no persistent metadata.
        // Release management still scans O(K+|cooldown|+|cand|).
        for(auto it=tree_list_.begin();it!=tree_list_.end();++it) {
            assert((*it)->tree); assert(std::find(tree_list_.begin(),it,*it)==it);
        }
        for(auto it=cand_.begin();it!=cand_.end();++it) {
            assert((*it)->adaptive.in_cand); assert(std::find(cand_.begin(),it,*it)==it);
        }
        for(auto it=cooldown_list_.begin();it!=cooldown_list_.end();++it) {
            assert((*it)->adaptive.in_cooldown); assert(std::find(cooldown_list_.begin(),it,*it)==it);
        }
#endif
    }
    void process_epoch() {
        ++observation_counters.epoch_scans;
        validate(); // Audit live candidates before flags reset and table clear.
        last_candidates_=cand_.size(); max_candidates_=std::max(max_candidates_,last_candidates_);
        for(auto b:cand_) b->adaptive.in_cand=false;
        const std::size_t limit=1; constexpr bool demotion=A!=Arm::NoIdle;
        for(std::size_t successful=0;demotion && successful<limit;) {
            Bucket* idle=nullptr;
            for(auto b:tree_list_) if(epoch_-b->adaptive.last_sensitive>=p_.down_idle_epochs && cool(*b) && resource_ok(*b)) { idle=b; break; }
            if(!idle) break;
            try { demote_bucket(*idle); ++successful; }
            catch(const std::bad_alloc&) { ++failures_; break; }
        }
        for(std::size_t i=0;i<cooldown_list_.size();) {
            auto b=cooldown_list_[i];
            if(epoch_>=b->adaptive.cooldown_until) {
                b->adaptive.in_cooldown=false;
                cooldown_list_[i]=cooldown_list_.back(); cooldown_list_.pop_back();
            } else ++i;
        }
        for(std::size_t successful=0;successful<limit && tree_count_<p_.tree_budget;) {
            Bucket* best=nullptr;
            for(auto b:cand_) { ++observation_counters.candidate_visits; if(eligible(*b) && resource_ok(*b) && better(b,best)) best=b; }
            if(!best) break;
            try { promote_bucket(*best); ++successful; }
            catch(const std::bad_alloc&) { ++failures_; break; }
        }
        cand_.clear(); validate();
    }
    void structural_done() {
        fresh_=false;
        if constexpr(A!=Arm::List) if(++ops_==p_.epoch_size) {
            ops_=0; ++epoch_;
            if constexpr(A!=Arm::ObserveList) process_epoch();
        }
    }
    void free_buckets() noexcept {
        Alloc<Bucket> alloc(mem_.buckets);
        for(auto& root:roots_) if(root) {
            for(std::size_t j=0;j<64;++j) {
                if(root[j].tree) destroy_tree(root[j].tree);
                std::allocator_traits<Alloc<Bucket>>::destroy(alloc,root+j);
            }
            alloc.deallocate(root,64); root=nullptr;
        }
    }
public:
    static constexpr Arm arm=A;
    static constexpr std::size_t threshold=Threshold;
    static constexpr bool native_work_available=A!=Arm::List;
    Index(Domain domain,const Params& params,MemoryAccounts& memory)
        :domain_(domain),p_(params),mem_(memory),tree_list_(Alloc<Bucket*>(memory.manager)),
         cand_(Alloc<Bucket*>(memory.manager)),cooldown_list_(Alloc<Bucket*>(memory.manager)),chunks_(Alloc<Chunk>(memory.manager)) {
        domain_.validate();
        if(!p_.epoch_size || !p_.min_tree_size || !p_.down_idle_epochs || p_.tree_budget>4096 ||
           p_.down_idle_epochs>std::numeric_limits<std::uint64_t>::max()/2 ||
           !std::isfinite(p_.payback) || p_.payback<0 || !std::isfinite(p_.scan_ns_per_work) || p_.scan_ns_per_work<=0 ||
           !std::isfinite(p_.conversion_base_ns) || p_.conversion_base_ns<0 ||
           !std::isfinite(p_.conversion_ns_per_record) || p_.conversion_ns_per_record<=0)
            throw std::invalid_argument("invalid adaptive parameters");
        for(const auto& row:p_.tree_cost) for(double x:row)
            if(!std::isfinite(x) || x<=0) throw std::invalid_argument("invalid tree observation cost");
#ifdef ADAPTIVE_ABLATION
        if(!p_.scheduled_limit || p_.scheduled_limit>2 || !std::isfinite(p_.decay_factor) || p_.decay_factor<=0 || p_.decay_factor>1)
            throw std::invalid_argument("invalid ablation parameters");
#endif
        try {
            tree_list_.reserve(p_.tree_budget); cand_.reserve(4096); cooldown_list_.reserve(4096);
            Alloc<Bucket> alloc(mem_.buckets);
            for(auto& root:roots_) {
                root=alloc.allocate(64);
                for(std::size_t j=0;j<64;++j) std::allocator_traits<Alloc<Bucket>>::construct(alloc,root+j);
            }
        } catch(...) { free_buckets(); throw; }
    }
    Index(const Index&)=delete; Index& operator=(const Index&)=delete;
    ~Index() noexcept {
        free_buckets(); Alloc<Node> alloc(mem_.pool);
        for(auto c:chunks_) {
            for(std::size_t j=0;j<c.count;++j) std::allocator_traits<Alloc<Node>>::destroy(alloc,c.data+j);
            alloc.deallocate(c.data,c.count);
        }
    }
    void build(const std::vector<Record>& input) {
        if(!fresh_ || building_) throw std::logic_error("build requires a fresh index");
        if(!std::is_sorted(input.begin(),input.end())) throw std::invalid_argument("build must be sorted");
        for(const auto& key:input) domain_.slot(key.first);
        building_=true; fresh_=false;
        try {
            if(!input.empty()) grow(input.size());
            for(const auto& key:input) {
                auto& b=bucket(domain_.slot(key.first)); auto q=node(key,b.tail,nullptr);
                if(b.tail) b.tail->next=q; else b.head=q;
                b.tail=q; ++b.n; ++size_;
            }
        } catch(...) { building_=false; throw; }
        building_=false; validate();
    }
    void insert(Record key) {
        auto& b=bucket(domain_.slot(key.first)); std::uint64_t work=0;
        const bool tree=b.tree!=nullptr;
        bool sensitive=false;
        if constexpr(A!=Arm::List) sensitive=tree?!(key>*b.tree->rbegin()):(!b.tail || !(key>b.tail->key));
        if(tree) b.tree->insert(key);
        else {
            Node* pos=lower(b,key,work); Node* prev=pos?pos->prev:b.tail; Node* q=node(key,prev,pos);
            if(prev) prev->next=q; else b.head=q;
            if(pos) pos->prev=q; else b.tail=q;
        }
        ++b.n; ++size_;
        if(tree) { if(sensitive) b.adaptive.last_sensitive=epoch_; }
        else observe_list(b,Op::Insert,work,sensitive,true);
        if constexpr(A!=Arm::List) last_work_=work;
        validate_bucket(b); structural_done();
    }
    void erase(Record key) {
        auto& b=bucket(domain_.slot(key.first)); std::uint64_t work=0;
        const bool tree=b.tree!=nullptr;
        bool sensitive=false;
        if constexpr(A!=Arm::List) sensitive=tree?(key!=*b.tree->begin()):(!b.head || key!=b.head->key);
        if(tree) {
            auto it=b.tree->find(key);
            if(it!=b.tree->end()) { b.tree->erase(it); --b.n; --size_; }
            if(!b.n) cleanup_empty_tree(b);
            else if(sensitive) b.adaptive.last_sensitive=epoch_;
        } else {
            Node* q=lower(b,key,work);
            if(q && q->key==key) {
                if(q->prev) q->prev->next=q->next; else b.head=q->next;
                if(q->next) q->next->prev=q->prev; else b.tail=q->prev;
                recycle(q); --b.n; --size_;
            }
            observe_list(b,Op::Erase,work,sensitive,true);
        }
        if constexpr(A!=Arm::List) last_work_=work;
        validate_bucket(b); structural_done();
    }
    void erase(std::uint64_t code) { domain_.slot(code); erase(Record{code,code%domain_.stride}); }
    std::vector<Record> peek_range(std::uint64_t lo,std::uint64_t hi) const {
        std::vector<Record> output; hi=std::min(hi,domain_.end()); if(lo>=hi) return output;
        const auto first=domain_.slot(lo),last=domain_.slot(hi-1);
        for(auto i=first;i<=last;++i) {
            const auto& b=bucket(i);
            if(b.tree) for(auto it=b.tree->lower_bound({lo,0});it!=b.tree->end() && it->first<hi;++it) output.push_back(*it);
            else for(auto q=b.head;q;q=q->next) {
                if(q->key.first>=hi) break;
                if(q->key.first>=lo) output.push_back(q->key);
            }
        }
        return output;
    }
    std::vector<Record> range(std::uint64_t lo,std::uint64_t hi) {
        if constexpr(A==Arm::List) {
            std::vector<Record> output; hi=std::min(hi,domain_.end());
            if(lo>=hi) return output;
            const auto first=domain_.slot(lo),last=domain_.slot(hi-1);
            std::uint64_t diagnostic_work=0;
            for(auto i=first;i<=last;++i) {
                const auto& b=bucket(i);
                if(b.tree) {
                    auto it=b.tree->lower_bound({lo,0});
                    for(;it!=b.tree->end() && it->first<hi;++it) output.push_back(*it);
                } else {
                    auto q=b.head;
                    while(q && q->key.first<lo) { q=q->next; diagnostic_work+=2; }
                    for(;q && q->key.first<hi;q=q->next) output.push_back(q->key);
                }
            }
            observation_counters.list_work+=diagnostic_work;
            fresh_=false; return output;
        } else {
        std::vector<Record> output; hi=std::min(hi,domain_.end());
        if(lo>=hi) { last_work_=0; return output; }
        const auto first=domain_.slot(lo),last=domain_.slot(hi-1);
        ++observation_counters.range_buffers;
        std::array<std::uint64_t,4096> work{}; std::array<bool,4096> sensitive{};
        for(auto i=first;i<=last;++i) {
            const auto& b=bucket(i);
            if(b.tree) {
                auto it=b.tree->lower_bound({lo,0}); sensitive[i]=it!=b.tree->begin();
                for(;it!=b.tree->end() && it->first<hi;++it) output.push_back(*it);
            } else {
                sensitive[i]=b.head && lo>b.head->key.first; auto q=b.head;
                while(q && q->key.first<lo) { q=q->next; work[i]+=2; }
                for(;q && q->key.first<hi;q=q->next) output.push_back(q->key);
            }
        }
        std::uint64_t total=0;
        for(auto i=first;i<=last;++i) {
            auto& b=bucket(i);
            if(b.tree) { if(sensitive[i]) b.adaptive.last_sensitive=epoch_; }
            else observe_list(b,Op::Range,work[i],sensitive[i],false);
            total+=work[i];
        }
        last_work_=total; fresh_=false; return output;
            }
    }
    std::vector<Record> values() const {
        std::vector<Record> output; output.reserve(size_);
        for(auto root:roots_) for(std::size_t j=0;j<64;++j) {
            const auto& b=root[j];
            if(b.tree) output.insert(output.end(),b.tree->begin(),b.tree->end());
            else for(auto q=b.head;q;q=q->next) output.push_back(q->key);
        }
        return output;
    }
    std::size_t size() const noexcept { return size_; }
    std::size_t tree_count() const noexcept { return tree_count_; }
    std::size_t tree_buckets() const noexcept { return tree_count_; }
    std::size_t nodes_allocated() const noexcept { return nodes_allocated_; }
    std::size_t cand_size() const noexcept { return cand_.size(); }
    std::size_t tree_list_size() const noexcept { return tree_list_.size(); }
    std::size_t cooldown_list_size() const noexcept { return cooldown_list_.size(); }
    std::uint64_t epoch() const noexcept { return epoch_; }
    std::uint64_t ops_in_epoch() const noexcept { return ops_; }
    std::uint64_t promotions() const noexcept { return promotions_; }
    std::uint64_t scheduled_demotions() const noexcept { return scheduled_down_; }
    std::uint64_t cleanup_demotions() const noexcept { return cleanup_down_; }
    std::uint64_t total_demotions() const noexcept { return total_down_; }
    std::uint64_t gate_hits() const noexcept { return gate_hits_; }
    std::uint64_t last_work() const noexcept { return last_work_; }
    std::uint64_t total_avoidable_work() const noexcept { return total_work_; }
    std::size_t last_epoch_candidate_count() const noexcept { return last_candidates_; }
    std::size_t max_epoch_candidate_count() const noexcept { return max_candidates_; }
    std::uint64_t conversion_up_ns() const noexcept { return up_ns_; }
    std::uint64_t conversion_down_ns() const noexcept { return down_ns_; }
    std::uint64_t conversion_failures() const noexcept { return failures_; }
    std::size_t peak_tree_buckets() const noexcept { return peak_trees_; }
    const void* bucket_address_of(std::size_t slot) const { return &bucket(slot); }
    std::size_t bucket_size(std::size_t slot) const { return bucket(slot).n; }
    bool is_tree(std::size_t slot) const { return bucket(slot).tree!=nullptr; }
    double gain_ns_of(std::size_t slot) const { return bucket(slot).adaptive.gain; }
    std::uint64_t last_sensitive_epoch_of(std::size_t slot) const { return bucket(slot).adaptive.last_sensitive; }
    std::uint64_t cooldown_until_epoch_of(std::size_t slot) const { return bucket(slot).adaptive.cooldown_until; }
    bool in_cand_of(std::size_t slot) const { return bucket(slot).adaptive.in_cand; }
    std::size_t memory_bytes() const noexcept { return sizeof(Index)+mem_.current(); }
};
}
