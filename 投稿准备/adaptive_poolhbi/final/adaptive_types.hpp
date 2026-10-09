#pragma once
#include "shared_allocator.hpp"
#include <array>
#include <cmath>

namespace pbadaptive {
using Record = pubbench::Record;
using Domain = pubbench::Domain;
using MemoryStats = pbpolicy::MemoryStats;
template<class T> using Alloc = pbpolicy::Alloc<T>;
enum class Op { Insert=0, Erase=1, Range=2 };
enum class Signal { ActualWork, Off, EventCount, BinaryWork };
struct MemoryAccounts {
    MemoryStats pool, buckets, tree, manager;
    std::size_t current() const { return pool.current+buckets.current+tree.current+manager.current; }
};
struct Params {
    std::size_t epoch_size=512, min_tree_size=128, down_idle_epochs=4, tree_budget=32;
    std::size_t max_convert_records=0;
    double payback=2.0, scan_ns_per_work=1.1427456845204484;
    double conversion_base_ns=0, conversion_ns_per_record=31.412726323575615;
    std::array<std::array<double,3>,10> tree_cost{};
    bool cooldown_enabled=true;
    bool tree_cost_provisional=true;
#ifdef ADAPTIVE_ABLATION
    Signal signal=Signal::ActualWork;
    bool demotion_enabled=true, gain_clip=false;
    double decay_factor=1.0;
    std::size_t scheduled_limit=1;
#endif
    Params() {
        for(std::size_t c=0;c<10;++c)
            tree_cost[c].fill(30+5*std::log2(128.0*double(std::uint64_t(1)<<c)+1));
    }
};
}
