#pragma once
#include <algorithm>
#include <cstddef>
#include <cstdlib>
#include <new>
#include <cstdint>
#include <limits>
#include <stdexcept>
namespace s1::owner {
// Production requested-byte owner only. No fail-after field or injection path.
struct State{std::size_t current=0,peak=0,allocations=0,frees=0,live=0,references=1;};
inline thread_local std::size_t live_states=0;
inline State* make_state(){auto memory=std::malloc(sizeof(State));if(!memory)throw std::bad_alloc();++live_states;return new(memory)State;}
inline void release_state(State* state)noexcept{if(!--state->references){state->~State();std::free(state);--live_states;}}
// Allocation headers retain a control state, so exception-owned allocations may
// safely outlive the stack Owner on an invalid run. Control bytes are bookkeeping
// and never included in requested Index/output bytes.
struct Owner{State* state=make_state();std::size_t& current=state->current;std::size_t& peak=state->peak;std::size_t& allocations=state->allocations;std::size_t& frees=state->frees;std::size_t& live=state->live;~Owner(){release_state(state);}Owner()=default;Owner(const Owner&)=delete;Owner& operator=(const Owner&)=delete;};
inline thread_local Owner* active=nullptr;
struct Scope{Owner* previous;explicit Scope(Owner& o) noexcept:previous(active){active=&o;}~Scope(){active=previous;}Scope(const Scope&)=delete;};
struct Pause{Owner* previous;Pause()noexcept:previous(active){active=nullptr;}~Pause(){active=previous;}Pause(const Pause&)=delete;};
#ifdef ADAPTIVE_ALLOC_TRACK
struct alignas(std::max_align_t) Header{void* raw;std::size_t bytes;State* owner;};
inline void* allocate(std::size_t n,std::size_t alignment){alignment=std::max(alignment,alignof(Header));if(n>std::numeric_limits<std::size_t>::max()-sizeof(Header)-alignment)throw std::bad_alloc();void* raw=std::malloc(n+sizeof(Header)+alignment);if(!raw)throw std::bad_alloc();auto address=(reinterpret_cast<std::uintptr_t>(raw)+sizeof(Header)+alignment-1)&~(alignment-1);auto p=reinterpret_cast<Header*>(address)-1;p->raw=raw;p->bytes=n;p->owner=active?active->state:nullptr;if(p->owner){auto& o=*p->owner;o.current+=n;o.peak=std::max(o.peak,o.current);++o.allocations;++o.live;++o.references;}return reinterpret_cast<void*>(address);}
inline void release(void* raw)noexcept{if(!raw)return;auto p=static_cast<Header*>(raw)-1;if(p->owner){auto& o=*p->owner;if(o.current<p->bytes||!o.live)std::abort();o.current-=p->bytes;++o.frees;--o.live;release_state(p->owner);}std::free(p->raw);}
#endif
}
#ifdef ADAPTIVE_ALLOC_TRACK
void* operator new(std::size_t n){return s1::owner::allocate(n,alignof(std::max_align_t));}
void* operator new[](std::size_t n){return s1::owner::allocate(n,alignof(std::max_align_t));}
void operator delete(void* p)noexcept{s1::owner::release(p);}
void operator delete[](void* p)noexcept{s1::owner::release(p);}
void operator delete(void* p,std::size_t)noexcept{s1::owner::release(p);}
void operator delete[](void* p,std::size_t)noexcept{s1::owner::release(p);}
void* operator new(std::size_t n,std::align_val_t a){return s1::owner::allocate(n,std::size_t(a));}
void* operator new[](std::size_t n,std::align_val_t a){return s1::owner::allocate(n,std::size_t(a));}
void operator delete(void* p,std::align_val_t)noexcept{s1::owner::release(p);}
void operator delete[](void* p,std::align_val_t)noexcept{s1::owner::release(p);}
void operator delete(void* p,std::size_t,std::align_val_t)noexcept{s1::owner::release(p);}
void operator delete[](void* p,std::size_t,std::align_val_t)noexcept{s1::owner::release(p);}
void* operator new(std::size_t n,const std::nothrow_t&)noexcept{try{return::operator new(n);}catch(...){return nullptr;}}
void* operator new[](std::size_t n,const std::nothrow_t&)noexcept{try{return::operator new[](n);}catch(...){return nullptr;}}
void operator delete(void* p,const std::nothrow_t&)noexcept{s1::owner::release(p);}
void operator delete[](void* p,const std::nothrow_t&)noexcept{s1::owner::release(p);}
#endif
