#include <iostream>
#if __has_include("../src/s2_inputs.hpp")
#include "../src/s2_run.hpp"
#if __has_include("../src/s2_cli.hpp")
#include "../src/s2_cli.hpp"
#define S2_CLI_EXISTS 1
#endif
#define CHECK(x) do { if(!(x)) throw std::runtime_error(#x); } while(false)
template<class F> void rejects(F f){bool rejected=false;try{f();}catch(const std::exception&){rejected=true;}CHECK(rejected);}
template<class T>void halfopen(){pbadaptive::MemoryAccounts mem;{T index(s2::domain,pbadaptive::load_frozen_config("R6").params,mem);index.build({{10,10},{20,20},{30,30}});CHECK(index.range(20,30)==std::vector<s2::Record>({{20,20}}));CHECK(index.range(20,20).empty());CHECK(index.range(31,40).empty());CHECK(index.range(30,20).empty());}}
int main(){try{
 using namespace s2;
 halfopen<Tlx>();halfopen<matched::Index<matched::Arm::List>>();halfopen<matched::Index<matched::Arm::Event,16>>();halfopen<pbadaptive::Index>();
#ifndef S2_SOURCE_BUNDLE_SHA
 throw std::runtime_error("S2 source bundle identity is not bound to the compiler invocation");
#else
 CHECK(std::string(S2_SOURCE_BUNDLE_SHA).size()==64);CHECK(binary_sha().size()==64);CHECK(source_bundle_sha==std::string(S2_SOURCE_BUNDLE_SHA));
#endif
#ifndef S2_CLI_EXISTS
 throw std::runtime_error("S2 CLI parameter and protected-option validation is missing");
#else
 rejects([&]{parse({"run","--epoch","512"});});rejects([&]{parse({"prepare","--seed","102001","--seed","102002"});});rejects([&]{parse({"run","--method","TLX","--method","R6"});});rejects([&]{parse({"describe","--unused","x"});});
#endif
 std::vector<Record> source;for(std::uint64_t i=1;i<=5000;++i)source.push_back({(i/5)*domain.stride+i,i});
 for(auto id:{"L01","L02","L03"}){
  auto longest=generate(source,id,102001,"engineering",768,"test-protocol");
  if(std::string(id)=="L03"){CHECK(longest.segments[0].cancel_period==256);CHECK(longest.segments[1].cancel_period==0);CHECK(longest.segments[2].cancel_period==256);}
  CHECK(longest.request.units==3072);validate_bundle(longest,false);
  for(std::size_t h:{1,2,4}){
   auto b=prefix(longest,768*h);validate_bundle(b,false);CHECK(b.whole.initial==longest.whole.initial);
   for(std::size_t j=0;j<b.whole.steps.size();++j)CHECK(udriver::phase_mix_step(1,b.whole.steps[j])==udriver::phase_mix_step(1,longest.whole.steps[j]));
   for(auto m:{"M_LIST","M_EVENT_16","R6","TLX"}){auto r=run(b,m,false);CHECK(r.verified);
#ifdef ADAPTIVE_ALLOC_TRACK
    CHECK(r.owner_current_after_destroy==0);CHECK(r.owner_live_after_destroy==0);CHECK(r.owner_peak>0);
#else
    CHECK(owner_value(r.owner_current_after_destroy)=="NA");CHECK(owner_value(r.owner_live_after_destroy)=="NA");CHECK(owner_value(r.owner_peak)=="NA");
#endif
   }
  }
  bool erased_new=false;for(auto st:longest.whole.steps)if(st.erased>longest.whole.initial.back().first)erased_new=true;CHECK(erased_new);
  auto bad=longest;bad.request.units--;rejects([&]{validate_bundle(bad,false);});
  bad=longest;bad.domain.stride--;rejects([&]{validate_bundle(bad,false);});
  bad=longest;bad.whole.steps[0].erased=0;rejects([&]{validate_bundle(bad,false);});
  auto path=std::filesystem::path("s2_test_cache.bin");std::filesystem::remove(path);write_cache(path,longest);auto recovered=read_cache(path,false);CHECK(recovered.whole.hash==longest.whole.hash);rejects([&]{read_cache(path);});{std::fstream corrupt(path,std::ios::binary|std::ios::in|std::ios::out);corrupt.put('X');}rejects([&]{read_cache(path,false);});std::filesystem::remove(path);
  if(std::string(id)=="L03"){auto b=prefix(longest,1536);CHECK(b.segments.size()==2);CHECK(b.segments[1].begin==1024);CHECK(b.segments[1].queries==64);CHECK(prefix(longest,768).segments.size()==1);}
 }
 Fenwick f(8);for(std::size_t j:{1,3,6})f.add(j,1);CHECK(f.select(0)==1);CHECK(f.select(1)==3);CHECK(f.select(2)==6);f.add(3,-1);CHECK(f.select(1)==6);rejects([&]{f.select(2);});
 std::map<std::uint64_t,std::uint64_t> ref{{10,1},{20,2},{30,3}};CHECK(ref_range(ref,20,30)==std::vector<Record>({{20,2}}));CHECK(ref_range(ref,20,20).empty());CHECK(ref_range(ref,31,40).empty());
 rejects([&]{validate_profile("final",102001);});rejects([&]{validate_profile("engineering",100001);});rejects([&]{generate(source,"L04",102001,"engineering",768,"test-protocol");});
 source[1].second=source[0].second;rejects([&]{generate(source,"L01",102001,"engineering",768,"test-protocol");});
 std::cout<<"PASS S2 current-live, prefix, cadence, four-method, owner, malformed identity\n";return 0;
 }catch(const std::exception& e){std::cerr<<"FAIL "<<e.what()<<'\n';return 1;}}
#else
int main(){std::cerr<<"FAIL S2 current-live generator and four-method driver are missing\n";return 1;}
#endif
