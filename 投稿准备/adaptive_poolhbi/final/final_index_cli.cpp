#include "frozen_config.hpp"
#include "adaptive_poolhbi_final.hpp"
#include <charconv>
#include <iostream>
#include <sstream>
#include <string>
#include <limits>
using namespace pbadaptive;
namespace {
std::uint64_t unsigned_value(const std::string& text) {
    std::uint64_t value=0;
    auto parsed=std::from_chars(text.data(),text.data()+text.size(),value);
    if(text.empty() || parsed.ec!=std::errc{} || parsed.ptr!=text.data()+text.size()) throw std::invalid_argument("expected unsigned integer: "+text);
    return value;
}
std::uint64_t integer(std::istringstream& in) {
    std::string text; if(!(in>>text)) throw std::invalid_argument("missing unsigned integer");
    return unsigned_value(text);
}
void end_of_command(std::istringstream& in) {
    std::string extra; if(in>>extra) throw std::invalid_argument("unexpected trailing command token: "+extra);
}
std::string quoted(const std::string& text) {
    std::ostringstream out; out<<'"';
    for(unsigned char c:text) {
        if(c=='"' || c=='\\') out<<'\\'<<char(c);
        else if(c=='\n') out<<"\\n"; else if(c=='\r') out<<"\\r"; else if(c=='\t') out<<"\\t";
        else if(c<32) { const char* hex="0123456789abcdef"; out<<"\\u00"<<hex[c>>4]<<hex[c&15]; }
        else out<<char(c);
    }
    out<<'"'; return out.str();
}
void records(const char* command,const std::vector<Record>& values) {
    std::cout<<"{\"command\":\""<<command<<"\",\"records\":[";
    bool first=true; for(const auto& key:values) { if(!first) std::cout<<','; first=false; std::cout<<'['<<key.first<<','<<key.second<<']'; }
    std::cout<<"]}\n";
}
void stats(const Index& x,const MemoryAccounts& m) {
    std::cout<<"{\"command\":\"stats\",\"size\":"<<x.size()<<",\"epoch\":"<<x.epoch()<<",\"ops_in_epoch\":"<<x.ops_in_epoch()
        <<",\"tree_buckets\":"<<x.tree_buckets()<<",\"nodes_allocated\":"<<x.nodes_allocated()
        <<",\"promotions\":"<<x.promotions()<<",\"scheduled_demotions\":"<<x.scheduled_demotions()<<",\"cleanup_demotions\":"<<x.cleanup_demotions()<<",\"total_demotions\":"<<x.total_demotions()
        <<",\"gate_hits\":"<<x.gate_hits()<<",\"last_work\":"<<x.last_work()<<",\"total_avoidable_work\":"<<x.total_avoidable_work()
        <<",\"cand_size\":"<<x.cand_size()<<",\"tree_list_size\":"<<x.tree_list_size()<<",\"cooldown_list_size\":"<<x.cooldown_list_size()
        <<",\"last_epoch_candidate_count\":"<<x.last_epoch_candidate_count()<<",\"max_epoch_candidate_count\":"<<x.max_epoch_candidate_count()
        <<",\"conversion_up_ns\":"<<x.conversion_up_ns()<<",\"conversion_down_ns\":"<<x.conversion_down_ns()
        <<",\"conversion_failures\":"<<x.conversion_failures()<<",\"peak_tree_buckets\":"<<x.peak_tree_buckets()
        <<",\"memory_bytes\":"<<x.memory_bytes()<<",\"memory_current_bytes\":{\"pool\":"<<m.pool.current<<",\"buckets\":"<<m.buckets.current<<",\"tree\":"<<m.tree.current<<",\"manager\":"<<m.manager.current<<"}}\n";
}
void self_check(const FrozenConfig& configuration) {
    MemoryAccounts memory;
    {
        Index index(Domain{100,4096},configuration.params,memory);
        index.build({{10,1},{10,2},{20,3}});
        index.insert({15,4}); index.erase(Record{10,1});
        if(index.range(10,20)!=std::vector<Record>{{10,2},{15,4}} || index.values()!=std::vector<Record>{{10,2},{15,4},{20,3}} || index.size()!=3 || index.promotions()!=0)
            throw std::runtime_error("CLI API self-check mismatch");
    }
#ifdef INDEX_MEMORY
    if(memory.current()!=0) throw std::runtime_error("CLI API self-check allocator cleanup");
#endif
    std::cout<<"PASS CLI API self-check\n";
}
}
int main(int argc,char** argv) {
    try {
        std::string arm="R6"; bool fingerprint=false,selfcheck=false,stride_set=false,span_set=false;
        std::uint64_t stride=0,span=0;
        for(int i=1;i<argc;++i) {
            const std::string argument=argv[i];
            if(argument=="--fingerprint") fingerprint=true;
            else if(argument=="--self-check") selfcheck=true;
            else if(argument=="--config" || argument=="--stride" || argument=="--span") {
                if(++i>=argc) throw std::invalid_argument("missing value for "+argument);
                if(argument=="--config") arm=argv[i];
                else if(argument=="--stride") { stride=unsigned_value(argv[i]); stride_set=true; }
                else { span=unsigned_value(argv[i]); span_set=true; }
            } else if(argument=="--help") {
                std::cout<<"Options: --config R# (default R6), --fingerprint, --self-check, --stride N --span N\n"
                    <<"stdin, one command per line: build N code row [code row ...]; insert code row; erase code row; range lo hi; values; stats\n"
                    <<"build requires already sorted complete keys; range is half-open in code; erase removes one complete-key occurrence.\n";
                return 0;
            } else throw std::invalid_argument("unknown option: "+argument);
        }
        const auto configuration=load_frozen_config(arm);
        if(fingerprint && selfcheck) throw std::invalid_argument("choose one of --fingerprint and --self-check");
        if(fingerprint) { std::cout<<fingerprint_json(configuration)<<'\n'; return 0; }
        if(selfcheck) { self_check(configuration); return 0; }
        if(!stride_set || !span_set) throw std::invalid_argument("stdin API mode requires --stride N and --span N");
        MemoryAccounts memory; Index index(Domain{stride,span},configuration.params,memory);
        std::string line;
        while(std::getline(std::cin,line)) {
            std::istringstream in(line); std::string command; if(!(in>>command)) continue;
            if(command=="build") {
                const auto n=integer(in); if(n>std::numeric_limits<std::size_t>::max()) throw std::invalid_argument("build count overflow");
                std::vector<Record> input; input.reserve(static_cast<std::size_t>(n));
                for(std::uint64_t i=0;i<n;++i) { auto code=integer(in); auto row=integer(in); input.emplace_back(code,row); }
                end_of_command(in); index.build(input); std::cout<<"{\"command\":\"build\",\"size\":"<<index.size()<<"}\n";
            } else if(command=="insert" || command=="erase") {
                const auto code=integer(in),row=integer(in); end_of_command(in);
                if(command=="insert") index.insert({code,row}); else index.erase(Record{code,row});
                std::cout<<"{\"command\":\""<<command<<"\",\"size\":"<<index.size()<<"}\n";
            } else if(command=="range") {
                const auto lo=integer(in),hi=integer(in); end_of_command(in); records("range",index.range(lo,hi));
            } else if(command=="values") { end_of_command(in); records("values",index.values()); }
            else if(command=="stats") { end_of_command(in); stats(index,memory); }
            else throw std::invalid_argument("unknown stdin command: "+command);
        }
        if(std::cin.bad()) throw std::runtime_error("stdin read failure");
        return 0;
    } catch(const std::exception& error) { std::cerr<<"{\"error\":"<<quoted(error.what())<<"}\n"; return 1; }
}
