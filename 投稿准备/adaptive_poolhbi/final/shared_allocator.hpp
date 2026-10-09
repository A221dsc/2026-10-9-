#pragma once
#include <cstdint>
#include <utility>
#include <stdexcept>
#include <limits>
namespace pubbench {
using Record=std::pair<std::uint64_t,std::uint64_t>;
using Key=Record;
struct Domain {
 std::uint64_t stride,span;
 void validate()const{if(!stride||!span||(__uint128_t)stride*span>std::numeric_limits<std::uint64_t>::max())throw std::invalid_argument("invalid or overflowing time domain");}
 std::uint64_t end()const{return stride*span;}
 std::size_t slot(std::uint64_t code)const{if(code>=end())throw std::out_of_range("outside calendar domain");return (std::size_t)((__uint128_t)(code/stride)*4096/span);}
};
}
#pragma once
#include <array>
#include <vector>
#include <set>
#include <utility>
#include <cstdint>
#include <memory>
#include <algorithm>
#include <cassert>
#include <cmath>
#include <chrono>
#include <fstream>
#include <sstream>
#include <stdexcept>
namespace pbpolicy {
using Key=pubbench::Record;
enum class Mode{List,Fixed,FirstTouch,Cost,Count,Occupancy,Monitor,AllTree,Gated,EndpointGated};
struct MemoryStats{std::size_t current=0,peak=0,allocations=0,frees=0;
#ifdef INDEX_FAILURE_TEST
 std::int64_t fail_after=-1;
#endif
};
template<class T> struct Alloc {
 using value_type=T;using is_always_equal=std::false_type;
 using propagate_on_container_move_assignment=std::true_type;
 template<class U>struct rebind{using other=Alloc<U>;};
 MemoryStats* s=nullptr;Alloc()=default;explicit Alloc(MemoryStats& x):s(&x){}
 template<class U>Alloc(const Alloc<U>& a):s(a.s){}
 T* allocate(std::size_t n){if(!s)throw std::logic_error("missing allocation context");
#ifdef INDEX_FAILURE_TEST
 if(s->fail_after==0)throw std::bad_alloc();if(s->fail_after>0)--s->fail_after;
#endif
 auto p=std::allocator<T>{}.allocate(n);
#ifdef INDEX_MEMORY
 s->current+=n*sizeof(T);s->peak=std::max(s->peak,s->current);++s->allocations;
#endif
 return p;}
 void deallocate(T* p,std::size_t n)noexcept{
#ifdef INDEX_MEMORY
 assert(s&&s->current>=n*sizeof(T));s->current-=n*sizeof(T);++s->frees;
#endif
 std::allocator<T>{}.deallocate(p,n);}
 template<class U>bool operator==(const Alloc<U>& a)const{return s==a.s;}
 template<class U>bool operator!=(const Alloc<U>& a)const{return s!=a.s;}
};
}
