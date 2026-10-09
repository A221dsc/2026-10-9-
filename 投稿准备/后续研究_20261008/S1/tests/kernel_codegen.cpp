#include "../src/matched_index.hpp"
using matched::Record;
using matched::Arm;
extern "C" __attribute__((noinline)) void list_range(matched::Index<Arm::List>* x,std::vector<Record>* out,std::uint64_t lo,std::uint64_t hi) {
    *out=x->range(lo,hi);
}
extern "C" __attribute__((noinline)) void observe_range(matched::Index<Arm::ObserveList>* x,std::vector<Record>* out,std::uint64_t lo,std::uint64_t hi) {
    *out=x->range(lo,hi);
}
extern "C" __attribute__((noinline)) void list_insert(matched::Index<Arm::List>* x,Record r) {x->insert(r);}
extern "C" __attribute__((noinline)) void list_erase(matched::Index<Arm::List>* x,Record r) {x->erase(r);}
