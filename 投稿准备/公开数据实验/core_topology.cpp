// core_topology -- list logical processors grouped by physical core, with the
// Windows hybrid efficiency class, plus a fixed-kernel throughput probe.
//
// Purpose: this machine is 20 logical / 14 physical (6 P-cores x 2 + 8 E-cores).
// Allocating a benchmark run to an E-core inflates wall time far more than any
// effect the study is trying to measure, so the pinned harness must target a
// P-core logical processor. EfficiencyClass is the authoritative answer; the
// timing probe is printed alongside so the classification can be eyeballed.
//
// Usage: core_topology [--iters N]     (default N = 400000000)

#include <windows.h>

#include <algorithm>
#include <chrono>
#include <cstdio>
#include <cstdlib>
#include <string>
#include <vector>

namespace {

struct Core {
    unsigned logical;        // logical processor index (== affinity mask bit)
    unsigned efficiency;     // 0 = E-core, >=1 = P-core (Windows convention)
    double ns_per_iter;
    unsigned long long mask;
};

// The real Windows ABI for PROCESSOR_RELATIONSHIP starts with
//   BYTE Flags; BYTE EfficiencyClass; BYTE Reserved[20]; WORD GroupCount; ...
// MinGW-w64's header folds EfficiencyClass into Reserved[21] (same size, same
// offsets), so the field is not nameable there. This shadow struct restores the
// documented layout; a static_assert plus a runtime cross-check below confirm
// the two disagree only in that one field.
struct ProcessorRelationshipAbi {
    BYTE flags;
    BYTE efficiency_class;
    BYTE reserved[20];
    WORD group_count;
    GROUP_AFFINITY group_mask[1];
};
static_assert(sizeof(ProcessorRelationshipAbi) == sizeof(PROCESSOR_RELATIONSHIP),
              "PROCESSOR_RELATIONSHIP size differs from the documented ABI");

// Fixed integer kernel; the value is irrelevant, only the arithmetic density.
unsigned long long kernel(long long iters) {
    unsigned long long x = 0x243F6A8885A308D3ULL;
    unsigned long long y = 0;
    for (long long i = 0; i < iters; ++i) {
        x ^= x << 13;
        x ^= x >> 7;
        x ^= x << 17;
        y += x;
    }
    return y;
}

double time_kernel(long long iters) {
    volatile unsigned long long sink = kernel(iters / 8);  // warm up
    (void)sink;
    const auto a = std::chrono::steady_clock::now();
    sink = kernel(iters);
    const auto b = std::chrono::steady_clock::now();
    (void)sink;
    const double ns =
        static_cast<double>(std::chrono::duration_cast<std::chrono::nanoseconds>(b - a).count());
    return ns / static_cast<double>(iters);
}

}  // namespace

int main(int argc, char** argv) {
    long long iters = 400000000LL;
    for (int i = 1; i < argc; ++i) {
        const std::string k = argv[i];
        if (k == "--iters" && i + 1 < argc) {
            iters = std::atoll(argv[++i]);
        } else {
            std::fprintf(stderr, "unknown option %s\n", k.c_str());
            return 2;
        }
    }

    DWORD buffer_size = 0;
    GetLogicalProcessorInformationEx(RelationProcessorCore, nullptr, &buffer_size);
    if (buffer_size == 0) {
        std::fprintf(stderr, "GetLogicalProcessorInformationEx failed (%lu)\n", GetLastError());
        return 3;
    }
    std::vector<char> buffer(buffer_size);
    if (!GetLogicalProcessorInformationEx(
            RelationProcessorCore,
            reinterpret_cast<PSYSTEM_LOGICAL_PROCESSOR_INFORMATION_EX>(buffer.data()),
            &buffer_size)) {
        std::fprintf(stderr, "GetLogicalProcessorInformationEx failed (%lu)\n", GetLastError());
        return 3;
    }

    std::vector<Core> cores;
    for (DWORD offset = 0; offset < buffer_size;) {
        auto* entry = reinterpret_cast<PSYSTEM_LOGICAL_PROCESSOR_INFORMATION_EX>(
            buffer.data() + offset);
        if (entry->Relationship == RelationProcessorCore) {
            const auto& rel = entry->Processor;
            const auto* abi = reinterpret_cast<const ProcessorRelationshipAbi*>(&rel);
            // If the shadow layout were wrong these two would not agree.
            if (abi->flags != rel.Flags || abi->group_count != rel.GroupCount) {
                std::fprintf(stderr,
                             "core_topology: PROCESSOR_RELATIONSHIP ABI mismatch; refusing to "
                             "guess core types\n");
                return 4;
            }
            for (WORD g = 0; g < rel.GroupCount; ++g) {
                const auto& group = rel.GroupMask[g];
                for (unsigned bit = 0; bit < 8 * sizeof(KAFFINITY); ++bit) {
                    if (((group.Mask >> bit) & 1ULL) == 0) continue;
                    // Group 0 on this machine; the global logical index is the
                    // mask bit, which is also what SetProcessAffinityMask takes.
                    if (group.Group != 0) continue;
                    Core c;
                    c.logical = bit;
                    c.efficiency = abi->efficiency_class;
                    c.ns_per_iter = 0.0;
                    c.mask = 1ULL << bit;
                    cores.push_back(c);
                }
            }
        }
        offset += entry->Size;
    }
    std::sort(cores.begin(), cores.end(),
              [](const Core& a, const Core& b) { return a.logical < b.logical; });

    DWORD_PTR process_mask = 0, system_mask = 0;
    GetProcessAffinityMask(GetCurrentProcess(), &process_mask, &system_mask);

    std::printf("logical,efficiency_class,kind,ns_per_iter,mask_hex\n");
    DWORD_PTR p_mask = 0, e_mask = 0;
    unsigned p_count = 0, e_count = 0;
    for (auto& c : cores) {
        if ((system_mask & c.mask) == 0) continue;  // not schedulable
        // Pin to this core for the probe; time_kernel reports steady-state cost
        // only, so process startup and scheduling are excluded.
        SetProcessAffinityMask(GetCurrentProcess(), static_cast<DWORD_PTR>(c.mask));
        c.ns_per_iter = time_kernel(iters);
        const bool is_p = c.efficiency >= 1;
        std::printf("%u,%u,%s,%.4f,0x%llx\n", c.logical, c.efficiency, is_p ? "P" : "E",
                    c.ns_per_iter, static_cast<unsigned long long>(c.mask));
        if (is_p) {
            p_mask |= c.mask;
            ++p_count;
        } else {
            e_mask |= c.mask;
            ++e_count;
        }
    }
    SetProcessAffinityMask(GetCurrentProcess(), process_mask);  // restore

    std::printf("# physical_cores=%zu  P_logical=%u (mask 0x%llx)  E_logical=%u (mask 0x%llx)\n",
                cores.size(), p_count, static_cast<unsigned long long>(p_mask), e_count,
                static_cast<unsigned long long>(e_mask));
    std::printf("# suggested_single_core_mask=0x%llx\n",
                static_cast<unsigned long long>(p_mask ? (p_mask & (~p_mask + 1)) : process_mask));
    return 0;
}
