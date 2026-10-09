#pragma once
#include <fstream>
#include <cstring>
namespace udriver {
struct CacheWriter {
    std::ofstream out;std::uint64_t checksum=phase_hash_basis;
    explicit CacheWriter(const std::string& file):out(std::filesystem::path(file),std::ios::binary){if(!out)throw std::runtime_error("cache output open failed");}
    void raw(const char* p,std::size_t n){out.write(p,static_cast<std::streamsize>(n));for(std::size_t j=0;j<n;++j)checksum=mix(checksum,static_cast<unsigned char>(p[j]));if(!out)throw std::runtime_error("cache output write failed");}
    void u64(std::uint64_t n){char bytes[8];for(unsigned j=0;j<8;++j)bytes[j]=char(n>>(8*j));raw(bytes,8);}
    void text(const std::string& t){u64(t.size());raw(t.data(),t.size());}
    void record(Record r){u64(r.first);u64(r.second);}
    void records(const std::vector<Record>& v){u64(v.size());for(auto r:v)record(r);}
    void finish(){auto c=checksum;u64(c);out.close();if(!out)throw std::runtime_error("cache close failed");}
};
struct CacheReader {
    std::ifstream in;std::uint64_t checksum=phase_hash_basis;
    explicit CacheReader(const std::string& f):in(std::filesystem::path(f),std::ios::binary){if(!in)throw std::runtime_error("cache input open failed");}
    void raw(char* p,std::size_t n){in.read(p,static_cast<std::streamsize>(n));if(!in)throw std::runtime_error("truncated trace cache");for(std::size_t j=0;j<n;++j)checksum=mix(checksum,static_cast<unsigned char>(p[j]));}
    std::uint64_t u64(){char b[8];raw(b,8);std::uint64_t v=0;for(unsigned j=0;j<8;++j)v|=std::uint64_t(static_cast<unsigned char>(b[j]))<<(8*j);return v;}
    std::size_t count(std::size_t max){auto n=u64();if(n>max)throw std::runtime_error("trace cache count exceeds schema bound");return static_cast<std::size_t>(n);}
    std::string text(){std::string s(count(4096),'\0');raw(s.data(),s.size());return s;}
    Record record(){auto key=u64(),row=u64();return {key,row};}
    std::vector<Record> records(){std::vector<Record> v(count(100000000));for(auto& r:v)r=record();return v;}
    void finish(){auto expected=checksum;auto stored=u64();if(expected!=stored)throw std::runtime_error("trace cache payload checksum mismatch");char c;if(in.get(c))throw std::runtime_error("trace cache trailing bytes");}
};
inline void write_cache(const std::string& file,const Bundle& b){
    if(std::filesystem::exists(file)||std::filesystem::exists(file+".tmp"))throw std::runtime_error("immutable cache destination already exists");
    CacheWriter w(file+".tmp");w.raw("APHTRC01",8);w.u64(1);w.u64(b.domain.stride);w.u64(b.domain.span);
    const auto& r=b.request;w.text(r.data);w.text(r.month);w.text(r.workload);w.text(r.dataset_sha);w.text(r.protocol_sha);
    w.u64(r.seed);w.u64(r.initial);w.u64(r.units);w.u64(r.days);w.u64(b.source_rows);w.u64(b.query_period);w.u64(b.cancel_period);w.u64(b.ordered);
    const auto& t=b.whole;
    for(auto n:{t.hash,t.returned,t.queries,t.start,t.initmax,t.tail_inserts,t.head_erases,t.initial_distinct_times,t.initial_nonempty_buckets,t.initial_max_bucket})w.u64(n);
    w.records(t.initial);w.records(t.final);w.u64(t.steps.size());
    for(const auto& s:t.steps){w.record(s.added);for(auto n:{s.erased,s.lo,s.hi,s.expected_hash,s.expected_count})w.u64(n);w.u64(s.query);}
    w.u64(b.segments.size());for(const auto& s:b.segments){w.text(s.name);for(auto n:{std::uint64_t(s.begin),std::uint64_t(s.end),std::uint64_t(s.query_period),std::uint64_t(s.cancel_period),std::uint64_t(s.shuffle_incoming),std::uint64_t(s.random_every_delete),s.queries,s.returned,s.query_hash,s.request_hash})w.u64(n);}
    w.finish();std::filesystem::rename(file+".tmp",file);
}
inline Bundle read_cache(const std::string& file){
    CacheReader r(file);char magic[8];r.raw(magic,8);if(std::memcmp(magic,"APHTRC01",8)||r.u64()!=1)throw std::runtime_error("unknown trace cache schema");
    Bundle b;b.domain.stride=r.u64();b.domain.span=r.u64();b.domain.validate();
    auto& q=b.request;q.data=r.text();q.month=r.text();q.workload=r.text();q.dataset_sha=r.text();q.protocol_sha=r.text();
    q.seed=static_cast<unsigned>(r.count(UINT_MAX));q.initial=r.count(100000000);q.units=r.count(100000000);q.days=r.u64();b.source_rows=r.u64();b.query_period=r.u64();b.cancel_period=r.u64();b.ordered=r.u64()!=0;
    auto& t=b.whole;
    for(auto p:{&t.hash,&t.returned,&t.queries,&t.start,&t.initmax,&t.tail_inserts,&t.head_erases,&t.initial_distinct_times,&t.initial_nonempty_buckets,&t.initial_max_bucket})*p=r.u64();
    t.initial=r.records();t.final=r.records();t.steps.resize(r.count(100000000));
    for(auto& s:t.steps){s.added=r.record();for(auto p:{&s.erased,&s.lo,&s.hi,&s.expected_hash,&s.expected_count})*p=r.u64();s.query=r.u64()!=0;}
    b.segments.resize(r.count(16));for(auto& s:b.segments){s.name=r.text();s.begin=r.count(100000000);s.end=r.count(100000000);s.query_period=r.count(100000000);s.cancel_period=r.count(100000000);s.shuffle_incoming=r.u64()!=0;s.random_every_delete=r.u64()!=0;s.queries=r.u64();s.returned=r.u64();s.query_hash=r.u64();s.request_hash=r.u64();}
    r.finish();
    if(t.initial.size()!=q.initial||t.final.size()!=q.initial||!std::is_sorted(t.initial.begin(),t.initial.end())||!std::is_sorted(t.final.begin(),t.final.end()))throw std::runtime_error("cache initial/final shape mismatch");
    auto hash=mix(phase_hash_basis,hash_records(t.initial));std::uint64_t queries=0,returned=0;
    for(const auto& s:t.steps){hash=phase_mix_step(hash,s);if(s.query){++queries;returned+=s.expected_count;}}
    if(mix(hash,hash_records(t.final))!=t.hash||queries!=t.queries||returned!=t.returned)throw std::runtime_error("cache full trace identity mismatch");
    std::size_t end=0;for(const auto& s:b.segments){
        if(s.begin!=end||s.end<=s.begin||s.end>t.steps.size()||!s.query_period)throw std::runtime_error("cache phase boundaries/query period invalid");
        std::uint64_t requests=phase_hash_basis,query_hash=phase_hash_basis,phase_queries=0,phase_returned=0;
        for(std::size_t j=s.begin;j<s.end;++j){const auto& step=t.steps[j];requests=phase_mix_step(requests,step);
            if(step.query!=((j-s.begin+1)%s.query_period==0))throw std::runtime_error("cache phase query schedule mismatch");
            if(step.query){query_hash=mix(query_hash,step.expected_hash);++phase_queries;phase_returned+=step.expected_count;}}
        if(requests!=s.request_hash||query_hash!=s.query_hash||phase_queries!=s.queries||phase_returned!=s.returned)throw std::runtime_error("cache phase request/query identity mismatch");
        end=s.end;
    }
    if(end!=t.steps.size())throw std::runtime_error("cache phases incomplete");
    return b;
}
}
