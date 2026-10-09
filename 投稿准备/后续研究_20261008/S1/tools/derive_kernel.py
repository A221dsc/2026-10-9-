"""Mechanical, audited S0 policy derivation from immutable production R6.
Only whitespace and namespace/template type names are normalized for comparison.
Conditionals, statement order, expression text and all actual differences remain.
"""
import argparse, difflib, hashlib, json, pathlib, re
ROOT=pathlib.Path(__file__).resolve().parents[1]
SOURCE=ROOT.parent.parent/'adaptive_poolhbi'/'final'/'adaptive_poolhbi_final.hpp'
def digest(s):return hashlib.sha256(s.encode('utf8')).hexdigest()
def region(source,name,occurrence=0):
    # Function token selected at a declaration line, then brace balanced.
    matches=list(re.finditer(r'^    [^\n]*\b'+re.escape(name)+r'\([^\n]*',source,re.M))
    if not matches: raise ValueError('function not found '+name)
    start=matches[occurrence].start(); op=source.index('{',matches[occurrence].start())
    depth=0
    for j in range(op,len(source)):
        if source[j]=='{':depth+=1
        elif source[j]=='}':
            depth-=1
            if depth==0:return start,j+1,source[start:j+1]
    raise ValueError('unbalanced '+name)
def normalized(text):
    return re.sub(r'\s+','',text.replace('pbadaptive::','').replace('matched::','').replace('diagnostic::',''))
def derive():
    original=SOURCE.read_text(encoding='utf8');s=original;changes=[]
    def replace_once(old,new,label):
        nonlocal s
        if s.count(old)!=1:raise ValueError(f'{label}: expected one token block, got {s.count(old)}')
        s=s.replace(old,new);changes.append({'label':label,'before':old,'after':new})
    def function(name,new):
        nonlocal s
        a,b,old=region(s,name);s=s[:a]+new+s[b:];changes.append({'label':name,'before':old,'after':new})
    replace_once('#include "adaptive_types.hpp"','#include "../../../adaptive_poolhbi/final/adaptive_types.hpp"\n#ifdef ADAPTIVE_ABLATION\n#error Matched production policies require frozen non-ablation Params\n#endif','include immutable types and reject ablation')
    replace_once('namespace pbadaptive {','namespace matched {\nusing pbadaptive::Record; using pbadaptive::Domain; using pbadaptive::Params;\nusing pbadaptive::MemoryAccounts; using pbadaptive::Alloc; using pbadaptive::Op;\nenum class Arm { List, ObserveList, Fixed, Event, Cost, NoIdle };','namespace and frozen type aliases')
    replace_once('class Index {','template<Arm A, std::size_t Threshold=0> class Index {\n    static_assert(A!=Arm::Fixed || Threshold==128 || Threshold==512 || Threshold==2048 || Threshold==8192,"registered fixed threshold");\n    static_assert(A!=Arm::Event || Threshold==8 || Threshold==16 || Threshold==32 || Threshold==64,"registered event threshold");','compile-time policy, no instance fields')
    function('paid','''    bool paid(const Bucket& b) const noexcept {
        if constexpr(A==Arm::List || A==Arm::ObserveList) return false;
        else if constexpr(A==Arm::Fixed) return b.n>=Threshold;
        else if constexpr(A==Arm::Event) return b.adaptive.gain>=double(Threshold);
        else return b.adaptive.gain>=p_.payback*conversion(b);
    }''')
    function('register_candidate','''    void register_candidate(Bucket& b) {
        if constexpr(A!=Arm::List && A!=Arm::ObserveList) {
            if(!eligible(b)) return;
            ++gate_hits_;
            if(!b.adaptive.in_cand) { cand_.push_back(&b); b.adaptive.in_cand=true; }
        }
    }''')
    function('observe_list','''    void observe_list(Bucket& b,Op op,std::uint64_t work,bool sensitive,bool structural) {
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
    }''')
    replace_once('left=left->next; right=right->prev; work+=2;','left=left->next; right=right->prev; if constexpr(A!=Arm::List) work+=2;','LIST same lower content traversal without W')
    function('better','''    bool better(const Bucket* a,const Bucket* b) const noexcept {
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
    }''')
    replace_once('''        std::size_t limit=1; bool demotion=true;
#ifdef ADAPTIVE_ABLATION
        limit=p_.scheduled_limit; demotion=p_.demotion_enabled;
#endif''','''        const std::size_t limit=1; constexpr bool demotion=A!=Arm::NoIdle;''','NoIdle only ordinary demotion disabled')
    replace_once('''#ifdef ADAPTIVE_ABLATION
        if(p_.decay_factor!=1) for(auto root:roots_) for(std::size_t j=0;j<64;++j)
            if(!root[j].tree) root[j].adaptive.gain*=p_.decay_factor;
#endif
''','','remove impossible ablation-only decay block')
    function('structural_done','''    void structural_done() {
        fresh_=false;
        if constexpr(A!=Arm::List) if(++ops_==p_.epoch_size) {
            ops_=0; ++epoch_;
            if constexpr(A!=Arm::ObserveList) process_epoch();
        }
    }''')
    replace_once('''        const bool sensitive=tree?!(key>*b.tree->rbegin()):(!b.tail || !(key>b.tail->key));''','''        bool sensitive=false;
        if constexpr(A!=Arm::List) sensitive=tree?!(key>*b.tree->rbegin()):(!b.tail || !(key>b.tail->key));''','LIST insert sensitivity disabled')
    replace_once('''        const bool sensitive=tree?(key!=*b.tree->begin()):(!b.head || key!=b.head->key);''','''        bool sensitive=false;
        if constexpr(A!=Arm::List) sensitive=tree?(key!=*b.tree->begin()):(!b.head || key!=b.head->key);''','LIST erase sensitivity disabled')
    # Both insert/erase post-content observer commits. Record each exact occurrence.
    old='        last_work_=work; validate_bucket(b); structural_done();'
    if s.count(old)!=2:raise ValueError('structural work commits count')
    s=s.replace(old,'        if constexpr(A!=Arm::List) last_work_=work;\n        validate_bucket(b); structural_done();')
    changes.append({'label':'LIST both structural work commits','before':old,'after':'if constexpr(A!=Arm::List) last_work_=work; validate_bucket(b); structural_done();','occurrences':2})
    a,b,old=region(s,'range')
    # Original observation branch is retained verbatim. A LIST-only content loop
    # follows the exact original while-prefix/output traversal; no peek substitution.
    branch=old.replace('    std::vector<Record> range(std::uint64_t lo,std::uint64_t hi) {','',1).rsplit('}',1)[0]
    new='''    std::vector<Record> range(std::uint64_t lo,std::uint64_t hi) {
        if constexpr(A==Arm::List) {
            std::vector<Record> output; hi=std::min(hi,domain_.end());
            if(lo>=hi) return output;
            const auto first=domain_.slot(lo),last=domain_.slot(hi-1);
            for(auto i=first;i<=last;++i) {
                const auto& b=bucket(i);
                if(b.tree) {
                    auto it=b.tree->lower_bound({lo,0});
                    for(;it!=b.tree->end() && it->first<hi;++it) output.push_back(*it);
                } else {
                    auto q=b.head;
                    while(q && q->key.first<lo) q=q->next;
                    for(;q && q->key.first<hi;q=q->next) output.push_back(q->key);
                }
            }
            fresh_=false; return output;
        } else {'''+branch+'''        }
    }'''
    s=s[:a]+new+s[b:];changes.append({'label':'LIST range only observation removal','before':old,'after':new})
    replace_once('public:\n    Index(Domain','public:\n    static constexpr Arm arm=A;\n    static constexpr std::size_t threshold=Threshold;\n    static constexpr bool native_work_available=A!=Arm::List;\n    Index(Domain','compile-time metadata only')
    s=s.replace('// v4 main method. Comparison switches exist only in ADAPTIVE_ABLATION builds.','// Generated matched policies. Production R6 remains in its original header.')
    return original,s,changes

DIAGNOSTIC_API='''
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
'''
def diagnostic(s):
    d=s.replace('#pragma once','#pragma once\n#ifndef S0_EVENT_TRACE\n#error Diagnostic header requires S0_EVENT_TRACE; native must include matched_index.hpp only\n#endif\n#include "matched_index.hpp"',1)
    d=d.replace('namespace matched {','namespace diagnostic {',1)
    d=d.replace('enum class Arm { List, ObserveList, Fixed, Event, Cost, NoIdle };','using matched::Arm;'+DIAGNOSTIC_API,1)
    # Pure diagnostic counter / successful conversion notifications, separately diffed.
    d=d.replace('if constexpr(A!=Arm::List) work+=2;','work+=2;',1)
    d=d.replace('''        if constexpr(A!=Arm::List) {
            auto& a=b.adaptive;''','''        if constexpr(A==Arm::List) observation_counters.list_work+=work;
        if constexpr(A!=Arm::List) {
            auto& a=b.adaptive;''',1)
    d=d.replace('''    void process_epoch() {
        validate();''','''    void process_epoch() {
        ++observation_counters.epoch_scans;
        validate();''',1)
    d=d.replace('for(auto b:cand_) if(eligible(*b) && resource_ok(*b) && better(b,best)) best=b;',
                'for(auto b:cand_) { ++observation_counters.candidate_visits; if(eligible(*b) && resource_ok(*b) && better(b,best)) best=b; }',1)
    d=d.replace('std::array<std::uint64_t,4096> work{}; std::array<bool,4096> sensitive{};',
                '++observation_counters.range_buffers;\n        std::array<std::uint64_t,4096> work{}; std::array<bool,4096> sensitive{};',1)
    # M_LIST separate counting requires only an ephemeral scalar, never two arrays.
    d=d.replace('''            const auto first=domain_.slot(lo),last=domain_.slot(hi-1);
            for(auto i=first;i<=last;++i) {''','''            const auto first=domain_.slot(lo),last=domain_.slot(hi-1);
            std::uint64_t diagnostic_work=0;
            for(auto i=first;i<=last;++i) {''',1)
    d=d.replace('while(q && q->key.first<lo) q=q->next;','while(q && q->key.first<lo) { q=q->next; diagnostic_work+=2; }',1)
    d=d.replace('''            fresh_=false; return output;''','''            observation_counters.list_work+=diagnostic_work;
            fresh_=false; return output;''',1)
    emit='''    void emit_conversion(const Bucket& b,EventType type,std::uint64_t ns) const noexcept {
        if(!event_sink) return;
        for(std::size_t r=0;r<64;++r) for(std::size_t j=0;j<64;++j)
            if(roots_[r]+j==&b) { event_sink({api_ordinal,epoch_,r*64+j,b.n,type,ns}); return; }
    }
'''
    d=d.replace('    void promote_bucket(Bucket& b) {',emit+'    void promote_bucket(Bucket& b) {',1)
    for old,new in [
      ('reset_conversion(b); ++promotions_; up_ns_+=elapsed(start);','reset_conversion(b); ++promotions_; const auto body_ns=elapsed(start); up_ns_+=body_ns; emit_conversion(b,EventType::Promotion,body_ns);'),
      ('reset_conversion(b); ++scheduled_down_; ++total_down_; down_ns_+=elapsed(start);','reset_conversion(b); ++scheduled_down_; ++total_down_; const auto body_ns=elapsed(start); down_ns_+=body_ns; emit_conversion(b,EventType::ScheduledDemotion,body_ns);'),
      ('reset_conversion(b); ++cleanup_down_; ++total_down_; down_ns_+=elapsed(start);','reset_conversion(b); ++cleanup_down_; ++total_down_; const auto body_ns=elapsed(start); down_ns_+=body_ns; emit_conversion(b,EventType::Cleanup,body_ns);')]:
        if d.count(old)!=1:raise ValueError('diagnostic conversion marker')
        d=d.replace(old,new,1)
    d=d.replace('    std::size_t bucket_size(std::size_t slot) const {','    const void* bucket_address_of(std::size_t slot) const { return &bucket(slot); }\n    std::size_t bucket_size(std::size_t slot) const {',1)
    return d
def main():
    ap=argparse.ArgumentParser();ap.add_argument('--tag',required=True);ap.add_argument('--check',action='store_true');a=ap.parse_args()
    if not re.fullmatch('[A-Za-z0-9_-]+',a.tag):raise SystemExit('invalid tag')
    original,s,changes=derive();d=diagnostic(s)
    evidence=ROOT/'artifacts'/'kernel'/a.tag;evidence.mkdir(parents=True,exist_ok=False)
    invariant=['elapsed','bucket','cost_class','conversion','cool','resource_ok','eligible','reset_conversion','swap_remove','grow','node','recycle','recycle_chain','make_tree','destroy_tree','promote_bucket','demote_bucket','cleanup_empty_tree','validate_bucket','validate','free_buckets','Index','build','peek_range','values']
    rows=[]
    for name in invariant:
        _,_,before=region(original,name);_,_,after=region(s,name)
        rows.append({'function':name,'original_normalized_sha256':digest(normalized(before)),'matched_normalized_sha256':digest(normalized(after)),'equal':normalized(before)==normalized(after)})
    for name,occurrence,label in [('bucket',1,'const bucket'),('Index',2,'destructor')]:
        _,_,before=region(original,name,occurrence);_,_,after=region(s,name,occurrence)
        rows.append({'function':label,'original_normalized_sha256':digest(normalized(before)),'matched_normalized_sha256':digest(normalized(after)),'equal':normalized(before)==normalized(after)})
    # Exact member/type declarations before the first function: retain byte-identical
    # ordered declarations; only template declaration/static_assert is excluded.
    def declarations(text):return text[text.index('    struct Node'):text.index('    static std::uint64_t elapsed')]
    layout_equal=declarations(original)==declarations(s)
    proof={'schema':'S1.derivation.v1','source_path':str(SOURCE),'source_sha256':hashlib.sha256(SOURCE.read_bytes()).hexdigest(),
           'normalization':'namespace qualifications and whitespace only; no conditional/statement/expression removal',
           'member_declarations_exact_equal':layout_equal,'invariant_functions':rows,'replacements':changes,
           'native_sha256':digest(s),'diagnostic_sha256':digest(d),'diagnostic_changes':'external TLS counters, output-success W, conversion-success event notifications, bucket address accessor; no new Index fields'}
    (evidence/'derivation.json').write_text(json.dumps(proof,ensure_ascii=False,indent=2),encoding='utf8')
    (evidence/'native.diff').write_text(''.join(difflib.unified_diff(original.splitlines(True),s.splitlines(True),fromfile='frozen_R6',tofile='matched')),encoding='utf8')
    (evidence/'diagnostic_hooks.diff').write_text(''.join(difflib.unified_diff(s.splitlines(True),d.splitlines(True),fromfile='matched_native',tofile='diagnostic_copy')),encoding='utf8')
    if not layout_equal or not all(row['equal'] for row in rows):raise SystemExit('invariant reconciliation failed')
    (ROOT/'src').mkdir(exist_ok=True)
    if a.check:
        if (ROOT/'src'/'matched_index.hpp').read_text(encoding='utf8')!=s or (ROOT/'src'/'diagnostic_index.hpp').read_text(encoding='utf8')!=d:raise SystemExit('generated headers drift')
    else:
        (ROOT/'src'/'matched_index.hpp').write_text(s,encoding='utf8',newline='\n')
        (ROOT/'src'/'diagnostic_index.hpp').write_text(d,encoding='utf8',newline='\n')
    print(json.dumps({'invariant_functions':len(rows),'all_equal':True,'fields_equal':True,'check_only':a.check,'evidence':str(evidence)},ensure_ascii=False))
if __name__=='__main__':main()
