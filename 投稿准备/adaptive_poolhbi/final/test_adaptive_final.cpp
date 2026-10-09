#include "adaptive_poolhbi_final.hpp"
#include <algorithm>
#include <array>
#include <cmath>
#include <cstddef>
#include <cstdlib>
#include <cstring>
#include <iostream>
#include <limits>
#include <new>
#include <random>
#include <set>
#include <string>
#include <vector>

// Independent injection: this is the actual standard vector output allocation,
// not an index allocator or a manufactured conversion failure.
namespace global_alloc {
long long fail_after = -1;
bool audit = false;
std::size_t attempts = 0, first_request = 0, last_request = 0;
#ifdef ADAPTIVE_ALLOC_TRACK
bool track = false;
std::size_t current = 0, peak = 0, allocations = 0;
struct alignas(std::max_align_t) Header { std::size_t bytes; bool tracked; };
#endif
void* allocate(std::size_t n) {
    if (audit) { if (attempts == 0) first_request = n; last_request = n; ++attempts; }
    if (fail_after == 0) throw std::bad_alloc();
    if (fail_after > 0) --fail_after;
    n = std::max(n, std::size_t(1));
#ifdef ADAPTIVE_ALLOC_TRACK
    if (n > std::numeric_limits<std::size_t>::max() - sizeof(Header)) throw std::bad_alloc();
    auto* h = static_cast<Header*>(std::malloc(n + sizeof(Header)));
    if (!h) throw std::bad_alloc();
    h->bytes = n; h->tracked = track;
    if (track) { current += n; peak = std::max(peak, current); ++allocations; }
    return h + 1;
#else
    auto* p = std::malloc(n);
    if (!p) throw std::bad_alloc();
    return p;
#endif
}
void release(void* p) noexcept {
    if (!p) return;
#ifdef ADAPTIVE_ALLOC_TRACK
    auto* h = static_cast<Header*>(p) - 1;
    if (h->tracked) current -= h->bytes;
    std::free(h);
#else
    std::free(p);
#endif
}
}
void* operator new(std::size_t n) { return global_alloc::allocate(n); }
void* operator new[](std::size_t n) { return global_alloc::allocate(n); }
void operator delete(void* p) noexcept { global_alloc::release(p); }
void operator delete[](void* p) noexcept { global_alloc::release(p); }
void operator delete(void* p, std::size_t) noexcept { global_alloc::release(p); }
void operator delete[](void* p, std::size_t) noexcept { global_alloc::release(p); }

namespace formal {
using pbadaptive::Domain;
using pbadaptive::Index;
using pbadaptive::MemoryAccounts;
using pbadaptive::Params;
using pbadaptive::Record;
constexpr std::uint64_t stride = 1000000;
const Domain domain{stride, 4096};
std::uint64_t checks = 0;
void check(bool ok, const char* message) { ++checks; if (!ok) throw std::runtime_error(message); }
void near(double actual, double expected, const char* message) {
    check(std::isfinite(actual) && std::abs(actual - expected) <= 1e-9 * std::max(1.0, std::abs(expected)), message);
}
template<class E, class F> void throws(F f, const char* message) {
    bool caught = false;
    try { f(); } catch (const E&) { caught = true; }
    check(caught, message);
}
std::uint64_t base(std::size_t slot) { return stride * slot; }
Record key(std::size_t slot, std::uint64_t offset, std::uint64_t row = 0) { return {base(slot) + offset, row}; }
std::vector<Record> seed(std::size_t slot, std::size_t n = 8) {
    std::vector<Record> out;
    for (std::size_t j = 0; j < n; ++j) out.push_back(key(slot, 2 * j, j));
    return out;
}
std::vector<Record> seeds(std::initializer_list<std::size_t> slots, std::size_t n = 8) {
    std::vector<Record> out;
    for (auto s : slots) { auto part = seed(s, n); out.insert(out.end(), part.begin(), part.end()); }
    return out;
}
Params fixture(std::size_t epoch_size = 32, bool cooldown = false) {
    Params p;
    p.epoch_size = epoch_size; p.min_tree_size = 8; p.down_idle_epochs = 4;
    p.tree_budget = 32; p.scan_ns_per_work = 1; p.conversion_base_ns = 0;
    p.conversion_ns_per_record = .25; p.payback = 2; p.cooldown_enabled = cooldown;
    for (auto& row : p.tree_cost) row.fill(.125);
    return p;
}
// All progress uses successful public operations, including a valid missing erase.
void next_epoch(Index& x) {
    auto e = x.epoch();
    while (x.epoch() == e) x.erase(key(4095, 900000, 777));
}
void advance(Index& x, std::uint64_t epoch) { while (x.epoch() < epoch) next_epoch(x); }
void qualify(Index& x, std::size_t slot) {
    x.range(base(slot) + 12, base(slot) + 16);
    x.range(base(slot) + 12, base(slot) + 16);
    x.erase(key(slot, 900000, 888));
}
void promote(Index& x, std::size_t slot) {
    qualify(x, slot); check(x.in_cand_of(slot), "normal API failed to register eligible LIST");
    next_epoch(x); check(x.is_tree(slot), "normal API failed to promote eligible LIST");
}
struct BucketState {
    std::size_t n; bool tree, cand; double gain; std::uint64_t sensitive, cooldown;
};
BucketState state(const Index& x, std::size_t s) {
    return {x.bucket_size(s), x.is_tree(s), x.in_cand_of(s), x.gain_ns_of(s),
            x.last_sensitive_epoch_of(s), x.cooldown_until_epoch_of(s)};
}
void same(const BucketState& a, const BucketState& b, const char* message) {
    check(a.n == b.n && a.tree == b.tree && a.cand == b.cand && a.gain == b.gain &&
          a.sensitive == b.sensitive && a.cooldown == b.cooldown, message);
}
void stable(const Index& x, const MemoryAccounts& m) {
    std::size_t n = 0, trees = 0, candidates = 0;
    for (std::size_t s = 0; s < 4096; ++s) {
        n += x.bucket_size(s); trees += x.is_tree(s); candidates += x.in_cand_of(s);
        check(!x.is_tree(s) || x.bucket_size(s) > 0, "stable empty TREE");
    }
    check(n == x.size(), "bucket sizes disagree with size");
    check(trees == x.tree_count() && trees == x.tree_buckets() && trees == x.tree_list_size(), "tree membership mismatch");
    check(candidates == x.cand_size(), "candidate flags disagree with membership");
    check(x.total_demotions() == x.scheduled_demotions() + x.cleanup_demotions(), "demotion identity");
    check(x.max_epoch_candidate_count() <= 4096, "candidate upper bound");
#ifdef INDEX_MEMORY
    check(m.pool.current == x.nodes_allocated() * 32, "pool account differs from 32-byte nodes");
    check(m.buckets.current == 4096 * 64, "eager 64-byte buckets");
    check(x.memory_bytes() == sizeof(Index) + m.current(), "total memory double counts capacity");
#else
    (void)m;
#endif
}
void released(const MemoryAccounts& m) {
    check(m.pool.current == 0 && m.buckets.current == 0 && m.tree.current == 0 && m.manager.current == 0,
          "destructor or failed preparation leaked an allocation class");
}
void compare(const Index& x, const std::multiset<Record>& ref, const MemoryAccounts& m) {
    check(x.size() == ref.size(), "differential size");
    check(x.values() == std::vector<Record>(ref.begin(), ref.end()), "differential complete values");
    stable(x, m);
}
std::vector<Record> expected_range(const std::multiset<Record>& ref, std::uint64_t lo, std::uint64_t hi) {
    hi = std::min(hi, domain.end());
    if (lo >= hi) return {};
    return {ref.lower_bound({lo, 0}), ref.lower_bound({hi, 0})};
}

void T5() {
    MemoryAccounts m; Params p = fixture(128); p.min_tree_size = 100000;
    for (std::size_t c = 0; c < 10; ++c) p.tree_cost[c] = {{3.0 + c, 5.0 + c, 7.0 + c}};
    Index x(domain, p, m); x.build(seed(0));
    check(x.total_avoidable_work() == 0 && x.ops_in_epoch() == 0, "build observed work");
    x.insert(key(0, 100, 1)); check(x.last_work() == 0, "tail append work"); near(x.gain_ns_of(0), -3, "insert zero-work intercept");
    x.erase(key(0, 0, 0)); check(x.last_work() == 0, "head erase work"); near(x.gain_ns_of(0), -8, "erase zero-work intercept");
    x.range(0, 101); check(x.last_work() == 0, "full range output has work"); near(x.gain_ns_of(0), -15, "range zero-work intercept");
    auto gain = x.gain_ns_of(0); auto work = x.total_avoidable_work();
    x.insert(key(0, 5, 99)); check(x.last_work() == 4, "dual-end loop advances count two");
    near(x.gain_ns_of(0) - gain, p.scan_ns_per_work * 4 - 3, "insert work slope");
    gain = x.gain_ns_of(0); x.erase(key(0, 5, 99)); check(x.last_work() == 4, "erase dual-end work");
    near(x.gain_ns_of(0) - gain, 4 - 5, "erase work slope");
    gain = x.gain_ns_of(0); x.range(6, 101); check(x.last_work() == 4, "range two per skipped record");
    near(x.gain_ns_of(0) - gain, 4 - 7, "range work slope");
    check(x.total_avoidable_work() == work + 12, "actual work cumulative");
    auto before = state(x, 0); auto accumulated = x.total_avoidable_work();
    x.values(); x.peek_range(4, 100); x.size(); same(before, state(x, 0), "read-only observers alter state");
    check(x.total_avoidable_work() == accumulated, "read-only observers add work");
    x.range(10, 10); check(x.last_work() == 0, "empty range last_work"); same(before, state(x, 0), "empty range observation");
    x.range(domain.end() + 1, domain.end() + 10); same(before, state(x, 0), "out-of-domain empty range observation");
    // class uses post-operation n and signed subtraction, with a non-flat op table.
    MemoryAccounts m2; Index y(domain, p, m2); y.build(seed(0, 128));
    y.insert(key(0, 300, 0)); near(y.gain_ns_of(0), -4, "class(129) after insert");
    auto gy = y.gain_ns_of(0); y.erase(key(0, 0, 0)); check(y.last_work() == 0, "head erase zero work at class boundary");
    near(y.gain_ns_of(0) - gy, -5, "class(128) after erase");
    MemoryAccounts mt; Index t(domain, fixture(), mt); t.build(seed(0)); promote(t, 0);
    auto wt = t.total_avoidable_work(); auto st = state(t, 0);
    t.range(12, 16); check(t.last_work() == 0 && t.total_avoidable_work() == wt, "TREE invented work");
    near(t.gain_ns_of(0), st.gain, "TREE accumulated gain");
    t.insert(key(0, 5, 999)); check(t.last_work() == 0 && t.total_avoidable_work() == wt, "TREE insert invented work");
    t.erase(key(0, 5, 999)); check(t.last_work() == 0 && t.total_avoidable_work() == wt, "TREE erase invented work");
    near(t.gain_ns_of(0), st.gain, "TREE updates accumulated gain"); stable(t, mt);
}

void T9() {
    MemoryAccounts large; Params p; Index x(domain, p, large); x.build(seed(0, 45089));
    check(x.range(90176, 90178).size() == 1, "giant scan must completely materialize its tail record");
    check(x.last_work() == 90176, "45089-record giant scan work");
    x.erase(key(0, 900000, 777)); check(!x.in_cand_of(0), "single giant scan repaid default conversion");
    next_epoch(x); check(x.promotions() == 0 && !x.is_tree(0), "single giant scan promoted");
    MemoryAccounts small; Index y(domain, p, small); y.build(seed(0, 128));
    double expected = 0; const double cost = p.tree_cost[0][2];
    for (std::size_t e = 0; e < 51; ++e) {
        check(y.range(254, 256).size() == 1, "128 tail range must completely materialize output");
        expected += p.scan_ns_per_work * 254 - cost;
        near(y.gain_ns_of(0), expected, "128 materialized range gain per operation"); check(y.last_work() == 254, "128 tail range skip work");
        check(y.cand_size() == 0, "range alone registered candidate");
        y.erase(key(0, 900000, 777)); expected -= p.tree_cost[0][1];
        near(y.gain_ns_of(0), expected, "128 zero-work touch gain per operation");
        check(y.last_work() == 0, "128 structure touch must have zero work");
        check(y.in_cand_of(0) == (e == 50) && y.gate_hits() == (e == 50 ? 1 : 0), "default PAYBACK crossing epoch");
        next_epoch(y);
        if (e < 50) { near(y.gain_ns_of(0), expected, "boundary altered target gain"); check(!y.is_tree(0), "default promotion before epoch 51"); }
        else { near(y.gain_ns_of(0), 0, "successful promotion did not reset gain"); check(y.is_tree(0), "default eligible candidate not promoted at epoch 51"); }
    }
    check(y.epoch() == 51 && y.promotions() == 1 && y.total_avoidable_work() == 51 * 254,
          "51 epoch default actual-work PAYBACK trajectory");
}

void T10() {
    MemoryAccounts m; Params p = fixture(32, true); Index x(domain, p, m); x.build(seed(0)); promote(x, 0);
    auto initial_epoch = x.epoch(); auto work = x.total_avoidable_work(); advance(x, initial_epoch + 200);
    check(!x.is_tree(0) && x.promotions() == 1 && x.scheduled_demotions() == 1 &&
          x.cleanup_demotions() == 0 && x.total_demotions() == 1, "200 idle epochs did not demote once");
    check(x.total_avoidable_work() == work, "idle demotion clears/adds target work"); stable(x, m);
}

void T11() {
    // Default price: one huge range cannot buy a slot; a small repeatedly sensitive LIST can.
    MemoryAccounts m; Params p; p.tree_budget = 1; Index x(domain, p, m);
    auto v = seed(0, 128); auto big = seed(1, 45089); v.insert(v.end(), big.begin(), big.end()); x.build(v);
    x.range(base(1) + 90177, base(1) + 90178); x.erase(key(1, 900000, 777));
    for (int j = 0; j < 64; ++j) x.range(255, 256);
    x.erase(key(0, 900000, 777)); check(x.in_cand_of(0) && !x.in_cand_of(1), "PAYBACK gate for differently sized buckets");
    next_epoch(x); check(x.is_tree(0) && !x.is_tree(1) && x.tree_count() == 1, "K=1 chooses paid small bucket");
    // Primary key: absolute gain and repayment ratio must disagree.
    auto q = fixture(); q.tree_budget = 1;
    // A fresh unequal-size fixture avoids letting gain-only ordering pass.
    MemoryAccounts unequal; Index ratio(domain, q, unequal);
    auto unequal_seed = seed(0, 8); auto sixteen = seed(1, 16);
    unequal_seed.insert(unequal_seed.end(), sixteen.begin(), sixteen.end()); ratio.build(unequal_seed);
    qualify(ratio, 0); ratio.range(base(1) + 30, base(1) + 32); ratio.erase(key(1, 900000, 777));
    auto g0 = ratio.gain_ns_of(0), g1 = ratio.gain_ns_of(1);
    near(g0, 23.625, "ratio small gain fixture"); near(g1, 29.75, "ratio large gain fixture");
    check(g1 > g0 && g0 / (q.conversion_ns_per_record * 8) > g1 / (q.conversion_ns_per_record * 16),
          "gain and ratio must select opposite buckets");
    check(ratio.cand_size() == 2, "unequal-size candidates not both qualified");
    next_epoch(ratio); check(ratio.is_tree(0) && !ratio.is_tree(1), "primary repayment-ratio ranking");
    // Secondary key: exactly equal binary-representable ratios, unequal gain.
    MemoryAccounts gain_tie; Index tie(domain, q, gain_tie); tie.build(unequal_seed);
    tie.range(12, 16); tie.erase(key(0, 900000, 777));
    tie.range(base(1) + 12, base(1) + 32); tie.range(base(1) + 12, base(1) + 32);
    tie.erase(key(1, 900000, 777)); tie.erase(key(1, 900000, 777));
    near(tie.gain_ns_of(0), 11.75, "tie small gain fixture"); near(tie.gain_ns_of(1), 23.5, "tie large gain fixture");
    check(tie.gain_ns_of(0) / 2 == tie.gain_ns_of(1) / 4 && tie.cand_size() == 2, "exact ratio tie fixture");
    next_epoch(tie); check(tie.is_tree(1) && !tie.is_tree(0), "ratio tie must rank larger gain first");
    // Tertiary key: slots 8/9 are adjacent elements of the same eager Bucket
    // array. std::less<Bucket*> therefore orders 8 first, even if 9 registered first.
    MemoryAccounts address_tie; Index address(domain, q, address_tie); address.build(seeds({8, 9}));
    qualify(address, 9); qualify(address, 8);
    check(address.gain_ns_of(8) == address.gain_ns_of(9) && address.cand_size() == 2, "exact gain/address tie fixture");
    next_epoch(address); check(address.is_tree(8) && !address.is_tree(9), "gain tie must use Bucket pointer ordering");
    MemoryAccounts zero; q.tree_budget = 0; Index z(domain, q, zero); z.build(seed(0)); qualify(z, 0);
    check(z.gate_hits() > 0 && z.cand_size() == 1, "K=0 must still count gate and candidate");
    next_epoch(z); check(z.promotions() == 0 && z.last_epoch_candidate_count() == 1, "K=0 entry sample");
    MemoryAccounts expensive; q.tree_budget = 1; q.payback = 100; Index w(domain, q, expensive); w.build(seed(0)); qualify(w, 0);
    check(!w.in_cand_of(0) && w.gate_hits() == 0, "PAYBACK multiplier ignored"); next_epoch(w); check(w.promotions() == 0, "unpaid promotion");
    MemoryAccounts capped; q = fixture(); q.max_convert_records = 7; Index c(domain, q, capped); c.build(seed(0)); qualify(c, 0);
    next_epoch(c); check(c.promotions() == 0 && c.last_epoch_candidate_count() == 1, "max_convert_records failed");
}

void T12() {
    MemoryAccounts m; auto p = fixture(64); Index x(domain, p, m); x.build(seed(0));
    next_epoch(x); check(x.last_epoch_candidate_count() == 0 && x.max_epoch_candidate_count() == 0, "zero candidate entry not sampled");
    qualify(x, 0); auto hits = x.gate_hits();
    for (int j = 0; j < 12; ++j) x.erase(key(0, 900000, 777));
    check(x.cand_size() == 1 && x.gate_hits() == hits + 12, "candidate dedup suppresses gate hits");
    next_epoch(x); check(x.last_epoch_candidate_count() == 1 && x.max_epoch_candidate_count() == 1 &&
                         x.cand_size() == 0 && !x.in_cand_of(0), "candidate clear flags/sample");
    next_epoch(x); check(x.last_epoch_candidate_count() == 0 && x.max_epoch_candidate_count() == 1, "max entry sample not cumulative"); stable(x, m);
}

void promote_failure(bool tree_nodes, std::int64_t prefix) {
#ifdef INDEX_FAILURE_TEST
    MemoryAccounts m;
    {
        Index x(domain, fixture(), m); x.build(seed(0)); qualify(x, 0);
        auto content = x.values(); auto before = state(x, 0); auto epoch = x.epoch(); auto ops = x.ops_in_epoch();
        if (tree_nodes) m.tree.fail_after = prefix; else m.manager.fail_after = prefix;
        next_epoch(x); m.tree.fail_after = m.manager.fail_after = -1;
        check(x.epoch() == epoch + 1 && x.ops_in_epoch() == 0 && ops > 0, "conversion failure rolled back boundary");
        check(x.values() == content && !x.is_tree(0) && x.promotions() == 0 && x.conversion_failures() == 1,
              "promote preparation did not fail transactionally");
        near(x.gain_ns_of(0), before.gain, "failed promotion changed gain");
        check(x.last_sensitive_epoch_of(0) == before.sensitive && x.cooldown_until_epoch_of(0) == before.cooldown &&
              x.tree_list_size() == 0 && x.cooldown_list_size() == 0 && x.cand_size() == 0 && !x.in_cand_of(0), "failed promotion membership/reset");
        check(m.tree.current == 0, "partial tree node/object leak");
        qualify(x, 0); next_epoch(x); check(x.is_tree(0) && x.promotions() == 1, "failed promotion cannot retry"); stable(x, m);
    }
    released(m);
#else
    (void)tree_nodes; (void)prefix; throw std::runtime_error("INDEX_FAILURE_TEST required");
#endif
}
void T13() {
    promote_failure(false, 0); // Real Tree object, manager allocator.
    promote_failure(true, 0);  // First multiset node.
    promote_failure(true, 3);  // Nonempty partial multiset preparation must release nodes.
#ifdef INDEX_FAILURE_TEST
    MemoryAccounts m;
    {
        auto p = fixture(32, true); Index x(domain, p, m); x.build(seed(0)); promote(x, 0);
        auto cool = x.cooldown_until_epoch_of(0);
        // Promotion recycled LIST cells. Consume *all* free and unused cells in
        // another LIST; demote must now reach real pool.grow, not an invented hook.
        auto capacity = x.nodes_allocated();
        for (std::size_t j = 0; j < capacity; ++j) {
            x.insert(key(2, j % stride, j));
            // A large initial pool may cross many epochs. Keep the target
            // sensitive via a real TREE path until the last free cell is consumed.
            x.erase(key(0, 900000, 777));
        }
        check(x.is_tree(0) && x.bucket_size(2) == x.nodes_allocated(), "demote failure fixture lost TREE or did not exhaust pool");
        auto eligible_epoch = std::max(cool, x.last_sensitive_epoch_of(0) + p.down_idle_epochs);
        advance(x, eligible_epoch - 1); auto content = x.values(); auto before = state(x, 0);
        auto down = x.total_demotions(); auto manager_current = m.manager.current;
        m.pool.fail_after = 0; next_epoch(x); m.pool.fail_after = -1;
        check(x.epoch() == eligible_epoch && x.ops_in_epoch() == 0 && x.is_tree(0) && x.values() == content,
              "demote failure content/representation/boundary");
        check(x.conversion_failures() == 1 && x.total_demotions() == down && x.scheduled_demotions() == 0,
              "failed demote counted success");
        near(x.gain_ns_of(0), before.gain, "failed demote gain");
        check(x.cooldown_until_epoch_of(0) == before.cooldown && x.last_sensitive_epoch_of(0) == before.sensitive &&
              x.tree_list_size() == 1 && x.cooldown_list_size() == 0 && x.cand_size() == 0,
              "failed demote or normal expiry membership");
        check(m.manager.current == manager_current, "failed demote allocated persistent manager storage");
        next_epoch(x); check(!x.is_tree(0) && x.scheduled_demotions() == 1, "failed demote cannot retry"); stable(x, m);
    }
    released(m);
    MemoryAccounts content_mem;
    {
        Index x(domain, fixture(), content_mem); auto before = x.values();
        content_mem.pool.fail_after = 0; throws<std::bad_alloc>([&]{ x.insert(key(0, 2)); }, "content insert failure not thrown");
        content_mem.pool.fail_after = -1;
        check(x.values() == before && x.epoch() == 0 && x.ops_in_epoch() == 0 && x.total_avoidable_work() == 0 &&
              x.last_work() == 0 && x.gain_ns_of(0) == 0, "failed content allocation observed or advanced");
    }
    released(content_mem);
#else
    throw std::runtime_error("INDEX_FAILURE_TEST required");
#endif
    MemoryAccounts range_mem;
    {
        Index x(domain, fixture(), range_mem); x.build(seeds({0, 2}));
        x.range(12, base(2) + 16); auto a = state(x, 0), b = state(x, 1), c = state(x, 2);
        auto total = x.total_avoidable_work(), last = x.last_work(), ops = x.ops_in_epoch(), epoch = x.epoch();
        auto gates = x.gate_hits(); auto candidates = x.cand_size();
        auto tree_members = x.tree_list_size(), cooldown_members = x.cooldown_list_size();
        auto unchanged_global = [&] {
            check(x.gate_hits() == gates && x.cand_size() == candidates && x.tree_list_size() == tree_members &&
                  x.cooldown_list_size() == cooldown_members, "failed range changed gate or manager membership");
        };
        bool failed = false; global_alloc::fail_after = 0;
        try { x.range(10, base(2) + 16); } catch (const std::bad_alloc&) { failed = true; }
        global_alloc::fail_after = -1; check(failed, "real range output allocation did not fail");
        same(a, state(x, 0), "range failure partially observed first bucket"); same(b, state(x, 1), "range failure observed empty bucket");
        same(c, state(x, 2), "range failure partially observed last bucket");
        check(x.total_avoidable_work() == total && x.last_work() == last && x.ops_in_epoch() == ops && x.epoch() == epoch,
              "range output failure committed observation");
        unchanged_global();
        check(x.range(10, base(2) + 16).size() == 11, "range allocation retry");
        // The first LIST has no output but nonzero work; output allocation is
        // in the later LIST after an empty intervening bucket has been crossed.
        std::array<BucketState, 4096> before{};
        for (std::size_t s = 0; s < 4096; ++s) before[s] = state(x, s);
        total = x.total_avoidable_work(); last = x.last_work(); ops = x.ops_in_epoch(); epoch = x.epoch();
        gates = x.gate_hits(); candidates = x.cand_size(); tree_members = x.tree_list_size(); cooldown_members = x.cooldown_list_size();
        failed = false; global_alloc::fail_after = 0;
        try { x.range(16, base(2) + 16); } catch (const std::bad_alloc&) { failed = true; }
        global_alloc::fail_after = -1; check(failed, "later-bucket range output allocation must fail");
        for (std::size_t s = 0; s < 4096; ++s) same(before[s], state(x, s), "cross-empty-bucket range failure partially observed");
        check(x.total_avoidable_work() == total && x.last_work() == last && x.ops_in_epoch() == ops && x.epoch() == epoch,
              "later-bucket output failure committed global observation");
        unchanged_global();
        // Probe only actual output allocations, then fail every real prefix.
        // Prefix >=1 reaches later vector growth after the one-record first
        // bucket with the normal push_back implementation. A legal single
        // reserve has no invented subsequent failure point.
        global_alloc::attempts = 0; global_alloc::audit = true;
        auto probe = x.range(14, base(2) + 16);
        global_alloc::audit = false; auto output_allocations = global_alloc::attempts;
        check(probe.size() == 9 && output_allocations > 0, "range output allocation probe");
        for (std::size_t prefix = 0; prefix < output_allocations; ++prefix) {
            for (std::size_t s = 0; s < 4096; ++s) before[s] = state(x, s);
            total = x.total_avoidable_work(); last = x.last_work(); ops = x.ops_in_epoch(); epoch = x.epoch();
            gates = x.gate_hits(); candidates = x.cand_size(); tree_members = x.tree_list_size(); cooldown_members = x.cooldown_list_size();
            global_alloc::attempts = 0; global_alloc::audit = true; global_alloc::fail_after = static_cast<long long>(prefix);
            failed = false;
            try { x.range(14, base(2) + 16); } catch (const std::bad_alloc&) { failed = true; }
            global_alloc::fail_after = -1; global_alloc::audit = false;
            check(failed && global_alloc::attempts == prefix + 1, "actual output allocation prefix did not fail");
            for (std::size_t s = 0; s < 4096; ++s) same(before[s], state(x, s), "later vector growth failure partially observed a bucket");
            check(x.total_avoidable_work() == total && x.last_work() == last && x.ops_in_epoch() == ops && x.epoch() == epoch,
                  "later vector growth output failure committed global observation");
            unchanged_global();
        }
        check(x.range(14, base(2) + 16).size() == 9, "later output allocation retry");
        std::cout << "T13_range_actual_output_allocations=" << output_allocations
                  << " later_prefix_failure_points=" << output_allocations - 1 << '\n';
        stable(x, range_mem);
    }
    released(range_mem);
}

void mixed(std::uint64_t random_seed, MemoryAccounts& m) {
    auto p = fixture(64, true); p.min_tree_size = 16; p.tree_budget = 8;
    Index x(domain, p, m); std::multiset<Record> ref; std::mt19937_64 rng(random_seed);
    constexpr std::size_t count = 1000000; // Formal default, never reduced by an environment variable.
    for (std::size_t j = 0; j < count; ++j) {
        auto r = rng(); auto s = std::size_t((r >> 8) % 32); auto offset = std::uint64_t((r >> 20) % 256) * 2;
        Record k = key(s, offset, (r >> 40) % 4); auto op = r % 100;
        if (op < 43) { x.insert(k); ref.insert(k); }
        else if (op < 86) {
            x.erase(k); auto it = ref.find(k); if (it != ref.end()) ref.erase(it);
        } else if (op < 90) {
            // Wrapper must remove exactly {code, code % stride}, not all equal-code records.
            x.erase(k.first); auto it = ref.find({k.first, k.first % stride}); if (it != ref.end()) ref.erase(it);
        } else {
            auto lo = base(s) + ((r >> 32) % 520), hi = lo + ((r >> 48) % 3000001);
            check(x.range(lo, hi) == expected_range(ref, lo, hi), "million-op half-open range differential");
        }
        if (j % 8192 == 0) {
            compare(x, ref, m);
            auto lo = base((j / 8192) % 32) + 127;
            check(x.range(lo, lo + stride * 3) == expected_range(ref, lo, lo + stride * 3), "periodic materialized range");
            check(x.peek_range(lo, lo + stride * 3) == expected_range(ref, lo, lo + stride * 3), "periodic read-only range");
        }
    }
    compare(x, ref, m); check(x.range(0, domain.end() + 1) == std::vector<Record>(ref.begin(), ref.end()), "final full domain range");
}
void T14() { MemoryAccounts m; mixed(0x14f4a351ULL, m); released(m); }

void T15() {
    MemoryAccounts m; auto p = fixture(64); p.down_idle_epochs = 2; Index x(domain, p, m); x.build(seeds({0, 1, 2, 3}));
    for (auto s : {0, 1, 2, 3}) qualify(x, s);
    check(x.cand_size() == 4, "multi-bucket fixture not registered");
    auto up = x.promotions(), down = x.scheduled_demotions(); next_epoch(x);
    check(x.promotions() - up == 1 && x.scheduled_demotions() - down <= 1 && x.last_epoch_candidate_count() == 4, "single scheduled promotion quota");
    for (std::size_t s = 0; s < 4; ++s) check(!x.in_cand_of(s), "clear left candidate flag");
    for (int e = 0; e < 8; ++e) {
        for (std::size_t s = 0; s < 4; ++s) if (!x.is_tree(s)) qualify(x, s);
        up = x.promotions(); down = x.scheduled_demotions(); next_epoch(x);
        check(x.promotions() - up <= 1 && x.scheduled_demotions() - down <= 1, "ordinary per-epoch quotas");
        for (std::size_t s = 0; s < 4; ++s) check(!x.in_cand_of(s), "repeat clear left flag");
        stable(x, m);
    }
    check(x.scheduled_demotions() > 0 && x.promotions() > 4, "demoted LIST never registered again");
}

void T16() {
    MemoryAccounts m; auto p = fixture(64, true); Index x(domain, p, m); x.build(seeds({0, 1})); promote(x, 0); promote(x, 1);
    for (std::size_t j = 0; j < 7; ++j) { x.erase(key(0, 2 * j, j)); x.erase(key(1, 2 * j, j)); }
    auto epoch = x.epoch(), ops = x.ops_in_epoch(), clean = x.cleanup_demotions(), down = x.scheduled_demotions(), total = x.total_demotions();
    auto pool = m.pool.allocations, trees = x.tree_count(), coolmembers = x.cooldown_list_size();
#ifdef INDEX_FAILURE_TEST
    m.pool.fail_after = m.tree.fail_after = m.manager.fail_after = 0;
#endif
    x.erase(key(0, 14, 7)); x.erase(key(1, 14, 7));
#ifdef INDEX_FAILURE_TEST
    m.pool.fail_after = m.tree.fail_after = m.manager.fail_after = -1;
#endif
    check(x.epoch() == epoch && x.ops_in_epoch() == ops + 2 && x.cleanup_demotions() == clean + 2 &&
          x.total_demotions() == total + 2 && x.scheduled_demotions() == down, "two same-epoch cleanups counted as ordinary quota");
    check(x.tree_count() == trees - 2 && x.tree_list_size() == 0 && x.cooldown_list_size() == coolmembers && m.pool.allocations == pool,
          "empty-tree cleanup allocated or duplicated cooldown membership");
    for (auto s : {0, 1}) {
        check(!x.is_tree(s) && x.bucket_size(s) == 0 && x.gain_ns_of(s) == 0 && x.last_sensitive_epoch_of(s) == epoch &&
              x.cooldown_until_epoch_of(s) == epoch + 2 * p.down_idle_epochs, "cleanup stable/reset/cooldown");
    }
    // A boundary cleanup leaves the full ordinary demotion quota available.
    MemoryAccounts mb; auto q = fixture(32); q.down_idle_epochs = 2; Index y(domain, q, mb); y.build(seeds({0, 1})); promote(y, 0); promote(y, 1);
    for (std::size_t j = 0; j < 7; ++j) y.erase(key(0, 2 * j, j));
    y.erase(key(0, 900000, 777)); next_epoch(y); // sensitive refresh keeps the one-record target TREE alive.
    check(y.is_tree(0) && y.is_tree(1), "boundary fixture lost a TREE early");
    while (y.ops_in_epoch() < q.epoch_size - 1) y.erase(key(4095, 900000, 777));
    auto eb = y.epoch(); auto db = y.scheduled_demotions(); auto cb = y.cleanup_demotions(); auto tb = y.total_demotions();
    y.erase(key(0, 14, 7));
    check(y.epoch() == eb + 1 && y.ops_in_epoch() == 0 && y.cleanup_demotions() == cb + 1 &&
          y.scheduled_demotions() == db + 1 && y.total_demotions() == tb + 2, "boundary cleanup consumed ordinary demotion slot");
    check(!y.is_tree(0) && !y.is_tree(1), "boundary cleanup plus ordinary demotion representations"); stable(y, mb);
    // Refill a cleaned bucket through insert; its newly refreshed C remains binding.
    for (auto k : seed(0)) x.insert(k);
    qualify(x, 0); check(!x.in_cand_of(0), "cleanup refill bypassed cooldown");
    advance(x, x.cooldown_until_epoch_of(0)); qualify(x, 0); check(x.in_cand_of(0), "refilled LIST cannot register after cooldown");
    next_epoch(x); check(x.is_tree(0) && x.promotions() == 3, "cleanup refill cannot promote again"); stable(x, m);
}

void T17() {
    MemoryAccounts m; Index x(domain, fixture(128), m); x.build(seeds({0, 2, 4}));
    std::array<BucketState, 4096> before{};
    for (std::size_t s = 0; s < 4096; ++s) before[s] = state(x, s);
    x.insert(key(2, 5, 999));
    for (std::size_t s = 0; s < 4096; ++s) if (s != 2) same(before[s], state(x, s), "nonboundary insert changed another bucket");
    for (std::size_t s = 0; s < 4096; ++s) before[s] = state(x, s);
    x.erase(key(2, 5, 999));
    for (std::size_t s = 0; s < 4096; ++s) if (s != 2) same(before[s], state(x, s), "nonboundary erase changed another bucket");
    for (std::size_t s = 0; s < 4096; ++s) before[s] = state(x, s);
    auto e = x.epoch(), ops = x.ops_in_epoch(); x.range(base(0) + 12, base(2) + 16);
    check(x.epoch() == e && x.ops_in_epoch() == ops, "range advances epoch");
    for (std::size_t s = 3; s < 4096; ++s) same(before[s], state(x, s), "range observed outside spanned slots");
    near(x.gain_ns_of(1) - before[1].gain, -.125, "empty LIST range must commit zero-work intercept");
    check(x.last_sensitive_epoch_of(1) == before[1].sensitive && !x.in_cand_of(1), "empty LIST range sensitive/registers");
    promote(x, 4); next_epoch(x); auto st = state(x, 4); auto w = x.total_avoidable_work();
    x.range(base(4), base(4) + 16);
    check(x.last_sensitive_epoch_of(4) == st.sensitive, "TREE begin range refreshes sensitive time");
    x.range(base(4) + 12, base(4) + 16); near(x.gain_ns_of(4), st.gain, "TREE range gain side effect");
    check(x.total_avoidable_work() == w && x.last_sensitive_epoch_of(4) == x.epoch(), "TREE range sensitive truth value");
    auto sensitive = x.last_sensitive_epoch_of(4); x.range(base(4), base(4) + 16);
    check(x.last_sensitive_epoch_of(4) == sensitive, "TREE begin range refreshes sensitive time"); stable(x, m);
}

void T18() {
#ifdef ADAPTIVE_ALLOC_TRACK
    check(global_alloc::current == 0, "tracking must start without outstanding tracked blocks");
    global_alloc::track = true; global_alloc::peak = 0; global_alloc::allocations = 0;
#endif
    MemoryAccounts m; mixed(0x18c725b1ULL, m); released(m);
    // The same independent owner tracker also covers partial prepare and both directions.
    promote_failure(true, 3); promote_failure(false, 0);
    MemoryAccounts conversion;
    {
        auto p = fixture(32, true); Index x(domain, p, conversion);
#ifdef ADAPTIVE_ALLOC_TRACK
        check(global_alloc::current == conversion.current(), "constructor independent allocation total differs from four accounts");
#endif
        x.build(seed(0)); promote(x, 0);
#ifdef ADAPTIVE_ALLOC_TRACK
        check(global_alloc::current == conversion.current(), "promotion independent allocation total differs from four accounts");
#endif
        advance(x, x.cooldown_until_epoch_of(0)); check(x.scheduled_demotions() == 1, "memory fixture ordinary conversion missing"); stable(x, conversion);
#ifdef ADAPTIVE_ALLOC_TRACK
        check(global_alloc::current == conversion.current(), "demotion independent allocation total differs from four accounts");
#endif
    }
    released(conversion);
#ifdef ADAPTIVE_ALLOC_TRACK
    global_alloc::track = false;
    check(global_alloc::current == 0 && global_alloc::allocations > 0 && global_alloc::peak > 0, "independent global allocation owner leak");
    std::cout << "T18_alloc_tracking PASS allocations=" << global_alloc::allocations << " simultaneous_peak=" << global_alloc::peak << '\n';
#else
    std::cout << "T18_alloc_tracking UNVERIFIED (build with ADAPTIVE_ALLOC_TRACK independently of sanitizers)\n";
#endif
    std::cout << "T18_tool UNVERIFIED in this process; aggregate GREEN requires external ASAN and UBSAN evidence\n";
}

void T19() {
    Params defaults; check(defaults.down_idle_epochs == 4, "main d must be 4");
    MemoryAccounts invalid; auto bad = fixture(); bad.down_idle_epochs = 0;
    throws<std::invalid_argument>([&]{ Index x(domain, bad, invalid); }, "d=0 accepted"); released(invalid);
    MemoryAccounts m; auto p = fixture(32, true); p.down_idle_epochs = 2; Index x(domain, p, m); x.build(seed(0)); promote(x, 0);
    check(x.cooldown_until_epoch_of(0) == x.epoch() + 2 * p.down_idle_epochs, "promotion C != 2d");
    advance(x, x.cooldown_until_epoch_of(0)); check(!x.is_tree(0) && x.scheduled_demotions() == 1, "ordinary demotion at legal idle cooldown");
    auto t = x.epoch(); check(x.cooldown_until_epoch_of(0) == t + 2 * p.down_idle_epochs, "demotion C != 2d");
    advance(x, t + p.down_idle_epochs); qualify(x, 0); check(!x.in_cand_of(0), "t+d prematurely eligible");
    next_epoch(x); check(!x.is_tree(0) && x.promotions() == 1, "t+d prematurely re-promoted");
    advance(x, t + 2 * p.down_idle_epochs); qualify(x, 0); check(x.in_cand_of(0), "t+2d not eligible on normal structure touch");
    next_epoch(x); check(x.is_tree(0) && x.promotions() == 2 && x.total_demotions() == 1, "up/down/up cooldown sequence"); stable(x, m);
    MemoryAccounts main_mem; auto main_p = fixture(32, true); Index main_x(domain, main_p, main_mem); main_x.build(seed(0)); promote(main_x, 0);
    check(main_x.cooldown_until_epoch_of(0) == main_x.epoch() + 8, "main C=8");
}

void C_guards_and_constructor_failures() {
    // Build is an initial-state operation. A successful nonempty range has
    // already observed LIST buckets, even if its materialized output is empty.
    MemoryAccounts observed;
    {
        auto p = fixture(); Index x(domain, p, observed);
        check(x.range(0, 1).empty(), "fresh empty LIST range content");
        near(x.gain_ns_of(0), -.125, "fresh nonempty range must observe empty LIST");
        check(x.epoch() == 0 && x.ops_in_epoch() == 0, "fresh range advances structure clock");
        throws<std::logic_error>([&]{ x.build(seed(0)); }, "build accepted after successful nonempty range observation");
        check(x.size() == 0, "rejected build after range changed content");
    }
    released(observed);
    MemoryAccounts untouched;
    {
        auto p = fixture(); Index x(domain, p, untouched);
        check(x.range(10, 10).empty(), "fresh empty range content");
        check(x.range(domain.end() + 1, domain.end() + 10).empty(), "fresh out-of-domain empty range content");
        x.peek_range(0, 1); x.values(); x.size();
        x.build(seed(0)); check(x.size() == 8, "empty range or read-only API consumed build freshness");
        stable(x, untouched);
    }
    released(untouched);
    MemoryAccounts m; auto p = fixture();
    throws<std::invalid_argument>([&]{ Index x(Domain{0,4096}, p, m); }, "invalid domain accepted"); released(m);
    for (auto which : {0, 1}) {
        auto q = p; if (which == 0) q.epoch_size = 0; else q.tree_budget = 4097;
        throws<std::invalid_argument>([&]{ Index x(domain, q, m); }, "invalid epoch/K accepted"); released(m);
    }
    {
        Index x(domain, p, m); auto unsorted = seed(0); std::reverse(unsorted.begin(), unsorted.end());
        throws<std::invalid_argument>([&]{ x.build(unsorted); }, "unsorted build accepted"); check(x.size() == 0, "build validated too late");
        auto outside = seed(0); outside.push_back({domain.end(),0});
        throws<std::out_of_range>([&]{ x.build(outside); }, "out-of-domain build accepted"); check(x.size() == 0, "domain build validation too late");
        x.build(seed(0)); throws<std::logic_error>([&]{ x.build(seed(0)); }, "second build accepted");
        auto old = x.values(); auto ops = x.ops_in_epoch();
        throws<std::out_of_range>([&]{ x.insert({domain.end(),0}); }, "out-of-domain insert accepted");
        throws<std::out_of_range>([&]{ x.erase({domain.end(),0}); }, "out-of-domain erase accepted");
        check(x.values() == old && x.ops_in_epoch() == ops, "invalid key changed state"); stable(x, m);
    }
    released(m);
#ifdef INDEX_FAILURE_TEST
    // Every successful constructor allocation prefix in each account is tested.
    for (bool manager : {false, true}) {
        bool reached_success = false;
        for (std::int64_t prefix = 0; prefix < 128; ++prefix) {
            MemoryAccounts a; if (manager) a.manager.fail_after = prefix; else a.buckets.fail_after = prefix;
            try { Index x(domain, p, a); reached_success = true; } catch (const std::bad_alloc&) {}
            released(a); if (reached_success) break;
        }
        check(reached_success, "constructor prefix enumeration incomplete");
    }
    // Directory growth must eventually allocate manager storage. Inject only
    // manager allocation after construction, while ordinary pool growth is real.
    MemoryAccounts directory;
    {
        auto q = fixture(1000000); q.min_tree_size = 10000000; Index x(domain, q, directory);
        bool failed = false; directory.manager.fail_after = 0;
        for (std::size_t j = 0; j < 100000 && !failed; ++j) {
            auto n = x.size(); auto ops = x.ops_in_epoch();
            try { x.insert(key(2, j, j)); }
            catch (const std::bad_alloc&) { failed = true; check(x.size() == n && x.ops_in_epoch() == ops, "chunk directory failure committed content"); }
        }
        directory.manager.fail_after = -1; check(failed, "chunk directory allocator not manager-bound"); stable(x, directory);
        x.insert(key(2, 900001, 1)); stable(x, directory);
    }
    released(directory);
#endif
}
#ifdef ADAPTIVE_ALLOC_TRACK
void C_owner() {
    // Input storage is allocated before tracking. Its request bytes never enter
    // the index-only owner account or the equality below.
    auto input = seeds({0, 1}); auto p = fixture(32, true); MemoryAccounts m;
    check(!global_alloc::track && global_alloc::current == 0, "owner tracking scope not clean");
    global_alloc::track = true;
    {
        Index x(domain, p, m);
        auto total = [&] {
            check(global_alloc::current == m.current(), "independent index-owned request bytes differ from four accounts");
            check(x.memory_bytes() == sizeof(Index) + global_alloc::current, "independent total memory differs from reported total");
        };
        total(); x.build(input); total(); promote(x, 0); total(); promote(x, 1); total();
        for (auto k : seed(1)) x.erase(k);
        check(x.cleanup_demotions() == 1, "owner fixture cleanup missing"); total();
        advance(x, x.cooldown_until_epoch_of(0));
        check(x.scheduled_demotions() == 1, "owner fixture ordinary demote missing"); total();
    }
    global_alloc::track = false;
    released(m); check(global_alloc::current == 0, "independent Index owner scope leaked");
}
#endif
}

int main(int argc, char** argv) {
    struct Test { const char* id; void (*run)(); };
    const Test tests[] = {{"T5",formal::T5},{"T9",formal::T9},{"T10",formal::T10},{"T11",formal::T11},
        {"T12",formal::T12},{"T13",formal::T13},{"T14",formal::T14},{"T15",formal::T15},
        {"T16",formal::T16},{"T17",formal::T17},{"T18",formal::T18},{"T19",formal::T19},
        {"C_guards",formal::C_guards_and_constructor_failures}
#ifdef ADAPTIVE_ALLOC_TRACK
        ,{"C_owner",formal::C_owner}
#endif
    };
    const char* only = nullptr;
    if (argc == 3 && std::strcmp(argv[1], "--only") == 0) only = argv[2];
    else if (argc != 1) { std::cerr << "usage: test_adaptive_final [--only T13]\n"; return 2; }
    unsigned failed = 0, ran = 0;
    for (const auto& t : tests) {
        if (only && std::strcmp(only, t.id) != 0) continue;
        ++ran;
        auto start_checks = formal::checks;
        try { t.run(); std::cout << "CASE," << t.id << ",PASS," << formal::checks-start_checks << '\n'; }
        catch (const std::exception& e) {
            ++failed; global_alloc::fail_after = -1; global_alloc::audit = false;
#ifdef ADAPTIVE_ALLOC_TRACK
            global_alloc::track = false;
#endif
            std::cout << "CASE," << t.id << ",FAIL,exception=" << e.what() << '\n';
        } catch (...) { ++failed; global_alloc::fail_after = -1; global_alloc::audit = false; std::cout << "CASE," << t.id << ",FAIL,exception=unknown\n"; }
    }
    if (!ran) { std::cerr << "unknown test ID\n"; return 2; }
    std::cout << "SUMMARY," << (ran-failed) << ',' << failed << ',' << formal::checks << '\n';
    std::cout << "FORMAL " << (failed ? "RED" : "ASSERTIONS_PASS")
              << " T6-T8=RESERVED aggregate_GREEN_requires_external_T18_tools\n";
    return failed ? 1 : 0;
}
