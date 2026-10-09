#pragma once
#include "legacy/generators.hpp"
#include <string>
#include <filesystem>
#include <regex>
namespace udriver {
struct Request {
    std::string data, month="synthetic", workload="ordered_sparse", dataset_sha, protocol_sha;
    unsigned seed=71001;
    std::size_t initial=262144, units=32768;
    std::uint64_t days=31;
};
struct Bundle {
    Trace whole;
    std::vector<PhaseSegment> segments;
    Domain domain{};
    Request request;
    std::uint64_t source_rows=0, query_period=0, cancel_period=0;
    bool ordered=true;
};
inline std::uint64_t strict_u64(const std::string& value,int base=10){
    std::size_t begin=0;int radix=10;
    if(base==0&&value.size()>2&&value[0]=='0'&&(value[1]=='x'||value[1]=='X')){begin=2;radix=16;}
    if(value.size()==begin||!std::all_of(value.begin()+begin,value.end(),[&](unsigned char c){return(c>='0'&&c<='9')||(radix==16&&((c>='a'&&c<='f')||(c>='A'&&c<='F')));}))throw std::invalid_argument("unsigned integer requires complete canonical digits");
    std::size_t consumed=0;auto n=std::stoull(value,&consumed,radix);if(consumed!=value.size())throw std::invalid_argument("unsigned integer has trailing input");return n;
}
inline bool drift(const std::string& w) { return w=="sparse_dense_sparse"||w=="dense_sparse"||w=="sparse_shuffle_sparse"; }
inline bool main_workload(const std::string& w) {
    return w=="ordered_sparse"||w=="ordered_medium"||w=="ordered_dense"||w=="shuffled_churn"||w=="file_order_sparse"||w=="ordered_sparse_cancel";
}
inline Bundle generate(const std::vector<Record>& physical,const std::vector<Record>& sorted,Domain d,const Request& request) {
    Bundle b; b.domain=d;b.request=request;b.source_rows=physical.size();
    if(drift(request.workload)) {
        auto p=make_phase_trace(sorted,d,request.workload,request.seed,request.initial,request.units);
        b.whole=std::move(p.whole);b.segments=std::move(p.segments);b.ordered=request.workload!="sparse_shuffle_sparse";
    } else {
        if(main_workload(request.workload)) {
            b.whole=make_trace(physical,sorted,d,request.workload,request.seed,request.initial,request.units);
            b.query_period=request.workload=="ordered_dense"?1:(request.workload=="ordered_medium"||request.workload=="shuffled_churn"?8:256);
            b.cancel_period=request.workload=="ordered_sparse_cancel"?256:0;
            b.ordered=request.workload!="shuffled_churn"&&request.workload!="file_order_sparse";
        } else {
            std::smatch match;const std::regex pattern("^grid_n([0-9]+)_q([0-9]+)_c([0-9]+)$");
            if(!std::regex_match(request.workload,match,pattern))throw std::invalid_argument("unknown workload: "+request.workload);
            auto n=strict_u64(match[1].str());b.query_period=strict_u64(match[2].str());b.cancel_period=strict_u64(match[3].str());
            if(n!=request.initial)throw std::invalid_argument("grid N disagrees with --initial");
            b.whole=make_boundary_trace(sorted,d,request.seed,request.initial,request.units,b.query_period,b.cancel_period);
        }
        PhaseSegment s;s.name=request.workload;s.begin=0;s.end=b.whole.steps.size();s.query_period=b.query_period;s.cancel_period=b.cancel_period;
        s.queries=b.whole.queries;s.returned=b.whole.returned;
        for(const auto& step:b.whole.steps){s.request_hash=phase_mix_step(s.request_hash,step);if(step.query)s.query_hash=mix(s.query_hash,step.expected_hash);}
        b.segments.push_back(s);
    }
    return b;
}
inline void write_cache(const std::string&,const Bundle&);
inline Bundle read_cache(const std::string&);
inline void validate_adapter(const std::string&,const Bundle&);
inline std::vector<std::string> methods();
}
#include "trace_cache.hpp"
