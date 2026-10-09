#pragma once
#include <algorithm>
#include <cstddef>
#include <cstdlib>
#include <limits>
#include <new>
// Test-only independent global requested-byte owner, never compiled into native.
// Fixed event storage deliberately avoids recording allocations of its own.
namespace kernel_alloc {
struct Entry { std::size_t bytes; bool allocation; };
inline thread_local bool active=false;
inline thread_local long long fail_after=-1;
inline thread_local std::size_t current=0,peak=0,allocations=0,frees=0,used=0;
inline thread_local Entry entries[262144];
struct alignas(std::max_align_t) Header { std::size_t bytes; bool owned; };
inline void reset() {
    if(current) std::abort();
    peak=allocations=frees=used=0; fail_after=-1;
}
inline void* allocate(std::size_t n) {
    if(fail_after==0) throw std::bad_alloc();
    if(fail_after>0) --fail_after;
    if(n>std::numeric_limits<std::size_t>::max()-sizeof(Header)) throw std::bad_alloc();
    auto* h=static_cast<Header*>(std::malloc(std::max(n,std::size_t(1))+sizeof(Header)));
    if(!h) throw std::bad_alloc();
    h->bytes=n; h->owned=active;
    if(active) {
        current+=n; peak=std::max(peak,current); ++allocations;
        if(used==262144) std::abort(); entries[used++]={n,true};
    }
    return h+1;
}
inline void release(void* p) noexcept {
    if(!p) return;
    auto* h=static_cast<Header*>(p)-1;
    if(h->owned) {
        if(current<h->bytes || used==262144) std::abort();
        current-=h->bytes; ++frees; entries[used++]={h->bytes,false};
    }
    std::free(h);
}
}
#if defined(ADAPTIVE_ALLOC_TRACK) || defined(INDEX_FAILURE_TEST)
void* operator new(std::size_t n) { return kernel_alloc::allocate(n); }
void* operator new[](std::size_t n) { return kernel_alloc::allocate(n); }
void operator delete(void* p) noexcept { kernel_alloc::release(p); }
void operator delete[](void* p) noexcept { kernel_alloc::release(p); }
void operator delete(void* p,std::size_t) noexcept { kernel_alloc::release(p); }
void operator delete[](void* p,std::size_t) noexcept { kernel_alloc::release(p); }
#endif
