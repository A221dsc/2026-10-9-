#pragma once
#include "../../../adaptive_poolhbi/final/adaptive_poolhbi_final.hpp"
#include "../../../adaptive_poolhbi/final/frozen_config.hpp"
#include "../../../adaptive_poolhbi/final_experiments/legacy/pool_index.hpp"
#include "matched_index.hpp"
#ifdef S0_EVENT_TRACE
#include "diagnostic_index.hpp"
#endif
namespace s1 {
template<class T,bool Original=false,bool List=false,bool Event=false,std::size_t Threshold=0>struct StaticAdapter {
 using Index=T;static constexpr bool original=Original,list=List,event=Event;static constexpr std::size_t threshold=Threshold;
 static T* construct(Domain d,pbadaptive::MemoryAccounts& memory){if constexpr(Original)return new T(d);else return new T(d,pbadaptive::load_frozen_config("R6").params,memory);}
 static std::uint64_t epoch(const T& x){if constexpr(Original)return 0;else return x.epoch();}
};
inline const std::vector<std::string>& registered_methods(){static const std::vector<std::string> v={"Original","M_LIST","M_OBSERVE_LIST","M_EVENT_8","M_EVENT_16","M_EVENT_32","M_EVENT_64","M_FIXED_128","M_FIXED_512","M_FIXED_2048","M_FIXED_8192","R6","M_NO_IDLE"};return v;}
inline void validate_method(const std::string& m){if(std::find(registered_methods().begin(),registered_methods().end(),m)==registered_methods().end())throw std::invalid_argument("unknown registered method");}
template<class Call>decltype(auto) native_dispatch(const std::string& m,Call&& call){using matched::Arm;
 if(m=="Original")return call.template operator()<StaticAdapter<pubbench::PoolIndex<false>,true>>();
 if(m=="M_LIST")return call.template operator()<StaticAdapter<matched::Index<Arm::List>,false,true>>();
 if(m=="M_OBSERVE_LIST")return call.template operator()<StaticAdapter<matched::Index<Arm::ObserveList>>>();
 if(m=="R6")return call.template operator()<StaticAdapter<pbadaptive::Index>>();
 if(m=="M_NO_IDLE")return call.template operator()<StaticAdapter<matched::Index<Arm::NoIdle>>>();
#define S1_STATIC_EVENT(N) if(m=="M_EVENT_" #N)return call.template operator()<StaticAdapter<matched::Index<Arm::Event,N>,false,false,true,N>>();
 S1_STATIC_EVENT(8) S1_STATIC_EVENT(16) S1_STATIC_EVENT(32) S1_STATIC_EVENT(64)
#undef S1_STATIC_EVENT
#define S1_STATIC_FIXED(N) if(m=="M_FIXED_" #N)return call.template operator()<StaticAdapter<matched::Index<Arm::Fixed,N>,false,false,false,N>>();
 S1_STATIC_FIXED(128) S1_STATIC_FIXED(512) S1_STATIC_FIXED(2048) S1_STATIC_FIXED(8192)
#undef S1_STATIC_FIXED
 throw std::invalid_argument("unknown static dispatch method");}
#ifdef S0_EVENT_TRACE
template<class Call>decltype(auto) diagnostic_dispatch(const std::string& m,Call&& call){using matched::Arm;
 if(m=="Original")return call.template operator()<StaticAdapter<pubbench::PoolIndex<false>,true>>();
 if(m=="M_LIST")return call.template operator()<StaticAdapter<diagnostic::Index<Arm::List>,false,true>>();
 if(m=="M_OBSERVE_LIST")return call.template operator()<StaticAdapter<diagnostic::Index<Arm::ObserveList>>>();
 if(m=="R6")return call.template operator()<StaticAdapter<diagnostic::Index<Arm::Cost>>>();
 if(m=="M_NO_IDLE")return call.template operator()<StaticAdapter<diagnostic::Index<Arm::NoIdle>>>();
#define S1_DIAG_EVENT(N) if(m=="M_EVENT_" #N)return call.template operator()<StaticAdapter<diagnostic::Index<Arm::Event,N>,false,false,true,N>>();
 S1_DIAG_EVENT(8) S1_DIAG_EVENT(16) S1_DIAG_EVENT(32) S1_DIAG_EVENT(64)
#undef S1_DIAG_EVENT
#define S1_DIAG_FIXED(N) if(m=="M_FIXED_" #N)return call.template operator()<StaticAdapter<diagnostic::Index<Arm::Fixed,N>,false,false,false,N>>();
 S1_DIAG_FIXED(128) S1_DIAG_FIXED(512) S1_DIAG_FIXED(2048) S1_DIAG_FIXED(8192)
#undef S1_DIAG_FIXED
 throw std::invalid_argument("unknown diagnostic dispatch method");}
#endif
struct ModeContract{bool native_forbidden,latency_only_trace,resource_three_macros;std::string active;};
inline ModeContract mode_contract(){
#if defined(INDEX_FAILURE_TEST)||defined(ADAPTIVE_ABLATION)||defined(ALLOCATION_FAILURE_INJECTION)||defined(GLOBAL_ALLOCATION_TRACKING)
#error Failure injection, ablation and unknown global trackers prohibited in driver
#endif
#if defined(ADAPTIVE_ALLOC_TRACK) && (!defined(INDEX_MEMORY)||!defined(S0_EVENT_TRACE))
#error Resource requires INDEX_MEMORY and S0_EVENT_TRACE together
#endif
#if defined(INDEX_MEMORY) && !defined(ADAPTIVE_ALLOC_TRACK)
#error Driver accounts require production global owner tracking
#endif
#ifdef ADAPTIVE_ALLOC_TRACK
 return {true,true,true,"resource"};
#elif defined(S0_EVENT_TRACE)
 return {true,true,true,"latency"};
#else
 return {true,true,true,"native"};
#endif
}
}
