#pragma once
#include "s2_inputs.hpp"
#include <cctype>
namespace s2 {
// S2.cache.v1 is a flat object of strings, unsigned integers and booleans.
// Reject unsupported values, duplicate keys and non-JSON number syntax.
struct MetaValue {
 enum class Kind { String, Number, Boolean };
 Kind kind;std::string text;
 std::string string()const{if(kind!=Kind::String)throw std::runtime_error("S2 metadata string type");return text;}
 std::uint64_t number()const{if(kind!=Kind::Number)throw std::runtime_error("S2 metadata integer type");return udriver::strict_u64(text);}
 bool boolean()const{if(kind!=Kind::Boolean)throw std::runtime_error("S2 metadata boolean type");return text=="true";}
};
using Metadata=std::map<std::string,MetaValue>;
class MetaReader {
 const std::string& text_;std::size_t at_=0;
 void space(){while(at_<text_.size()&&(text_[at_]==' '||text_[at_]=='\r'||text_[at_]=='\n'||text_[at_]=='\t'))++at_;}
 char peek()const{if(at_==text_.size())throw std::runtime_error("S2 JSON truncated");return text_[at_];}
 char get(){auto c=peek();++at_;return c;}
 unsigned hex4(){unsigned cp=0;for(unsigned j=0;j<4;++j){auto c=get();unsigned n;if(c>='0'&&c<='9')n=c-'0';else if(c>='a'&&c<='f')n=c-'a'+10;else if(c>='A'&&c<='F')n=c-'A'+10;else throw std::runtime_error("S2 JSON unicode escape");cp=16*cp+n;}return cp;}
 static void utf8(std::string& s,unsigned cp){if(cp<0x80)s+=char(cp);else if(cp<0x800){s+=char(0xc0|(cp>>6));s+=char(0x80|(cp&63));}else if(cp<0x10000){s+=char(0xe0|(cp>>12));s+=char(0x80|((cp>>6)&63));s+=char(0x80|(cp&63));}else{s+=char(0xf0|(cp>>18));s+=char(0x80|((cp>>12)&63));s+=char(0x80|((cp>>6)&63));s+=char(0x80|(cp&63));}}
 std::string string(){if(get()!='"')throw std::runtime_error("S2 JSON string expected");std::string s;for(;;){auto c=get();if(c=='"')return s;if(static_cast<unsigned char>(c)<32)throw std::runtime_error("S2 JSON control character");if(c!='\\')s+=c;else{c=get();switch(c){case '"':case '\\':case '/':s+=c;break;case 'b':s+='\b';break;case 'f':s+='\f';break;case 'n':s+='\n';break;case 'r':s+='\r';break;case 't':s+='\t';break;case 'u':{auto cp=hex4();if(cp>=0xd800&&cp<=0xdbff){if(get()!='\\'||get()!='u')throw std::runtime_error("S2 JSON surrogate pair");auto low=hex4();if(low<0xdc00||low>0xdfff)throw std::runtime_error("S2 JSON low surrogate");cp=0x10000+((cp-0xd800)<<10)+low-0xdc00;}else if(cp>=0xdc00&&cp<=0xdfff)throw std::runtime_error("S2 JSON unpaired surrogate");utf8(s,cp);break;}default:throw std::runtime_error("S2 JSON escape");}}if(s.size()>4096)throw std::runtime_error("S2 metadata string bound");}}
 MetaValue value(){space();if(peek()=='"')return {MetaValue::Kind::String,string()};auto start=at_;if(peek()>='0'&&peek()<='9'){++at_;if(text_[start]=='0'&&at_<text_.size()&&std::isdigit(static_cast<unsigned char>(text_[at_])))throw std::runtime_error("S2 JSON leading zero");while(at_<text_.size()&&std::isdigit(static_cast<unsigned char>(text_[at_])))++at_;auto n=text_.substr(start,at_-start);udriver::strict_u64(n);return {MetaValue::Kind::Number,n};}for(auto literal:{"true","false"}){auto n=std::strlen(literal);if(text_.compare(at_,n,literal)==0){at_+=n;return {MetaValue::Kind::Boolean,literal};}}throw std::runtime_error("S2 metadata unsupported JSON value");}
public:
 explicit MetaReader(const std::string& text):text_(text){}
 Metadata parse(){Metadata m;space();if(get()!='{')throw std::runtime_error("S2 metadata object required");space();if(peek()=='}'){++at_;}else for(;;){space();auto key=string();space();if(get()!=':')throw std::runtime_error("S2 JSON colon");if(!m.emplace(key,value()).second)throw std::runtime_error("S2 JSON duplicate key");space();auto c=get();if(c=='}')break;if(c!=',')throw std::runtime_error("S2 JSON object separator");}space();if(at_!=text_.size())throw std::runtime_error("S2 JSON trailing bytes");return m;}
};
inline Metadata read_metadata(const std::filesystem::path& p){std::ifstream in(p,std::ios::binary);if(!in)throw std::runtime_error("S2 metadata unavailable");if(std::filesystem::file_size(p)>65536)throw std::runtime_error("S2 metadata size bound");std::string text((std::istreambuf_iterator<char>(in)),{});if(in.bad())throw std::runtime_error("S2 metadata read failed");return MetaReader(text).parse();}
inline void validate_metadata(const Metadata& m,const Bundle& b,const std::string& cache_sha,const std::string& longest_sha){
 const std::set<std::string> keys={"schema","case_id","profile","seed","N","U","Umax","horizon","start","stride","span","source_rows","source_sha","protocol_sha","cache_sha","longest_cache_sha","initial_sha","final_sha","trace_hash","query_hash","source_bundle_sha","queries","returned","API_calls","engineering_only"};
 if(m.size()!=keys.size())throw std::runtime_error("S2 metadata field count");for(const auto& item:m)if(!keys.count(item.first))throw std::runtime_error("S2 metadata unknown field");
 auto str=[&](const char* k,const std::string& expected){if(m.at(k).string()!=expected)throw std::runtime_error(std::string("S2 metadata string mismatch: ")+k);};
 auto number=[&](const char* k,std::uint64_t expected){if(m.at(k).number()!=expected)throw std::runtime_error(std::string("S2 metadata number mismatch: ")+k);};
 str("schema","S2.cache.v1");str("case_id",b.request.workload);str("profile",b.request.month.substr(3));str("source_sha",source_sha);str("protocol_sha",protocol_sha);str("source_bundle_sha",source_bundle_sha);str("cache_sha",cache_sha);str("longest_cache_sha",longest_sha);str("initial_sha",record_sha(b.whole.initial));str("final_sha",record_sha(b.whole.final));
 number("seed",b.request.seed);number("N",b.request.initial);number("U",b.request.units);number("Umax",4*b.request.initial);number("horizon",b.request.units/b.request.initial);number("start",b.whole.start);number("stride",b.domain.stride);number("span",b.domain.span);number("source_rows",b.source_rows);number("trace_hash",b.whole.hash);number("query_hash",query_hash(b));number("queries",b.whole.queries);number("returned",b.whole.returned);number("API_calls",2*b.request.units+b.whole.queries);
 if(m.at("engineering_only").boolean()!=(b.request.month=="S2:engineering"))throw std::runtime_error("S2 metadata engineering/profile mismatch");
}
// Hash every serialized Bundle field using SHA256. The reference prefix is
// rebuilt from h4, including final state, counters and original phase names.
inline std::string bundle_identity(const Bundle& b){s1::SHA256 h;auto text=[&](const std::string& s){h.u64(s.size());h.update(s.data(),s.size());};auto records=[&](const std::vector<Record>& v){h.u64(v.size());for(auto r:v){h.u64(r.first);h.u64(r.second);}};h.u64(b.domain.stride);h.u64(b.domain.span);const auto& r=b.request;for(const auto* s:{&r.data,&r.month,&r.workload,&r.dataset_sha,&r.protocol_sha})text(*s);for(auto n:{std::uint64_t(r.seed),std::uint64_t(r.initial),std::uint64_t(r.units),r.days,b.source_rows,b.query_period,b.cancel_period,std::uint64_t(b.ordered)})h.u64(n);const auto& t=b.whole;for(auto n:{t.hash,t.returned,t.queries,t.start,t.initmax,t.tail_inserts,t.head_erases,t.initial_distinct_times,t.initial_nonempty_buckets,t.initial_max_bucket})h.u64(n);records(t.initial);records(t.final);h.u64(t.steps.size());for(const auto& s:t.steps){for(auto n:{s.added.first,s.added.second,s.erased,s.lo,s.hi,s.expected_hash,s.expected_count,std::uint64_t(s.query)})h.u64(n);}h.u64(b.segments.size());for(const auto& s:b.segments){text(s.name);for(auto n:{std::uint64_t(s.begin),std::uint64_t(s.end),std::uint64_t(s.query_period),std::uint64_t(s.cancel_period),std::uint64_t(s.shuffle_incoming),std::uint64_t(s.random_every_delete),s.queries,s.returned,s.query_hash,s.request_hash})h.u64(n);}return h.finish();}
struct VerifiedCache {
 Bundle bundle;
 std::vector<std::pair<std::filesystem::path,std::string>> bindings;
 std::string metadata_sha,longest_cache_sha,longest_metadata_sha;
};
inline void reverify_cache(const VerifiedCache& v){for(const auto& binding:v.bindings)s1::require_sha(binding.first,binding.second);}
inline VerifiedCache verify_cache(const std::filesystem::path& path,const std::string& expected_sha,bool engineering){
 VerifiedCache v;auto cache=std::filesystem::canonical(path);if(cache.filename()!=L"cache.bin")throw std::runtime_error("S2 cache filename required");auto meta=cache.parent_path()/"cache.meta.json";auto longest=cache.parent_path().parent_path()/"h4"/"cache.bin";auto longest_meta=longest.parent_path()/"cache.meta.json";
 auto bind=[&](const std::filesystem::path& p,const std::string& sha){s1::require_sha(p,sha);v.bindings.push_back({p,sha});};
 bind(protocol_path(),protocol_sha);bind(cache,expected_sha);v.metadata_sha=s1::sha_file(meta);bind(meta,v.metadata_sha);v.bundle=read_cache(cache);
 if((v.bundle.request.month=="S2:engineering")!=engineering)throw std::runtime_error("S2 engineering flag/profile mismatch");if(cache.parent_path().filename()!=std::filesystem::path("h"+std::to_string(v.bundle.request.units/v.bundle.request.initial)))throw std::runtime_error("S2 cache horizon directory mismatch");
 v.longest_cache_sha=s1::sha_file(longest);bind(longest,v.longest_cache_sha);v.longest_metadata_sha=s1::sha_file(longest_meta);bind(longest_meta,v.longest_metadata_sha);
 validate_metadata(read_metadata(meta),v.bundle,expected_sha,v.longest_cache_sha);
 if(cache==std::filesystem::canonical(longest)){if(v.bundle.request.units!=4*v.bundle.request.initial)throw std::runtime_error("S2 longest horizon required");validate_metadata(read_metadata(longest_meta),v.bundle,v.longest_cache_sha,v.longest_cache_sha);}
 else {auto h4=read_cache(longest);if(h4.request.units!=4*h4.request.initial)throw std::runtime_error("S2 h4 length mismatch");validate_metadata(read_metadata(longest_meta),h4,v.longest_cache_sha,v.longest_cache_sha);auto expected=prefix(h4,v.bundle.request.units);if(bundle_identity(expected)!=bundle_identity(v.bundle))throw std::runtime_error("S2 cache is not the bound h4 true prefix");}
 if(v.bundle.request.data.empty())throw std::runtime_error("S2 source projection path missing");bind(std::filesystem::u8path(v.bundle.request.data),source_sha);reverify_cache(v);return v;
}
}
