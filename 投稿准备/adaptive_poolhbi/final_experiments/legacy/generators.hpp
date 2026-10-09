#pragma once
#include "public_index.hpp"
#include <random>
#include <map>
#include <numeric>
#include <functional>
#include <iomanip>
#include <climits>
namespace udriver {
using namespace pubbench;
static std::uint64_t mix(std::uint64_t h,std::uint64_t v){h^=v;h*=1099511628211ULL;return h;}
static std::uint64_t hash_records(const std::vector<Record>& v){std::uint64_t h=1469598103934665603ULL;for(auto r:v){h=mix(h,r.first);h=mix(h,r.second);}return mix(h,v.size());}
struct Step{Record added;std::uint64_t erased=0,lo=0,hi=0,expected_hash=0,expected_count=0;bool query=false;};
struct Trace{std::vector<Record> initial,final;std::vector<Step> steps;std::uint64_t hash=1469598103934665603ULL,returned=0,queries=0,start=0,initmax=0,tail_inserts=0,head_erases=0,initial_distinct_times=0,initial_nonempty_buckets=0,initial_max_bucket=0;};
static Trace make_trace(const std::vector<Record>& physical,const std::vector<Record>& sorted,Domain d,const std::string& workload,unsigned seed,std::size_t n,std::size_t units){
 if(n==0||units==0||units>n||n>physical.size()||units>physical.size()-n)throw std::runtime_error("invalid window or dataset too small");
 std::mt19937_64 rng(7817329ULL+seed*104729ULL);
 std::uniform_int_distribution<std::uint64_t> startdist(0,physical.size()-n-units);
 Trace t;t.start=startdist(rng);
 auto& source=workload=="file_order_sparse"?physical:sorted;
 std::vector<Record> incoming(source.begin()+t.start+n,source.begin()+t.start+n+units);
 std::vector<Record> deleted(source.begin()+t.start,source.begin()+t.start+units);
 t.initial.assign(source.begin()+t.start,source.begin()+t.start+n);std::sort(t.initial.begin(),t.initial.end());
 if(workload=="ordered_sparse_cancel"||workload=="long_ordered_sparse_cancel"){
  // Sparse cancellations remove a random remaining old record. Other steps
  // remove the oldest remaining record, without leaving a displaced head behind.
  std::vector<unsigned char> alive(n,1);std::size_t oldest=0;deleted.clear();
  for(std::size_t i=0;i<units;++i){while(!alive[oldest])++oldest;std::size_t pos=oldest;
   if((i+1)%256==0){std::uniform_int_distribution<std::size_t> future(oldest,n-1);do{pos=future(rng);}while(!alive[pos]);}
   deleted.push_back(t.initial[pos]);alive[pos]=0;
  }
 }
 if(workload=="shuffled_churn"){
  std::shuffle(incoming.begin(),incoming.end(),rng);
  // Random deletion is over the whole initial window, not just its earliest records.
  auto deletion_pool=t.initial;std::shuffle(deletion_pool.begin(),deletion_pool.end(),rng);
  deleted.assign(deletion_pool.begin(),deletion_pool.begin()+units);
 }
 std::size_t period=workload=="ordered_dense"?1:(workload=="ordered_medium"||workload=="shuffled_churn"?8:256);
 std::map<std::uint64_t,std::uint64_t> reference(t.initial.begin(),t.initial.end());
 std::array<std::size_t,4096> loads{};std::uint64_t lasttime=UINT64_MAX;
 for(auto r:t.initial){auto time=r.first/d.stride;if(time!=lasttime){++t.initial_distinct_times;lasttime=time;}++loads[d.slot(r.first)];}
 for(auto load:loads){t.initial_nonempty_buckets+=(load>0);t.initial_max_bucket=std::max(t.initial_max_bucket,(std::uint64_t)load);}
 auto water=t.initial.back().first/d.stride;t.initmax=water;
 t.hash=mix(t.hash,hash_records(t.initial));
 for(std::size_t i=0;i<units;++i){
  Step s;s.added=incoming[i];s.erased=deleted[i].first;
  auto old=reference.find(s.erased);if(old==reference.end())throw std::runtime_error("reference erase missing");
  if(old==reference.begin()||d.slot(std::prev(old)->first)!=d.slot(s.erased))++t.head_erases;
  reference.erase(old);
  auto after=reference.lower_bound(s.added.first);if(after==reference.end()||d.slot(after->first)!=d.slot(s.added.first))++t.tail_inserts;
  if(!reference.insert(s.added).second)throw std::runtime_error("reference duplicate composite key");
  water=std::max(water,s.added.first/d.stride);
  if((i+1)%period==0){s.query=true;s.hi=(water+1)*d.stride;s.lo=(water+1>60?water+1-60:0)*d.stride;
   std::vector<Record> result;for(auto q=reference.lower_bound(s.lo);q!=reference.end()&&q->first<s.hi;++q)result.emplace_back(*q);
   s.expected_hash=hash_records(result);s.expected_count=result.size();t.returned+=result.size();++t.queries;
  }
  t.hash=mix(t.hash,s.erased);t.hash=mix(t.hash,s.added.first);t.hash=mix(t.hash,s.added.second);t.hash=mix(t.hash,s.query);t.hash=mix(t.hash,s.lo);t.hash=mix(t.hash,s.hi);t.hash=mix(t.hash,s.expected_hash);
  t.steps.push_back(s);
 }
 t.final.assign(reference.begin(),reference.end());t.hash=mix(t.hash,hash_records(t.final));return t;
}

static std::vector<Record> load(const std::string& path,Domain& d,std::uint64_t span){
 std::ifstream f(path,std::ios::binary);if(!f)throw std::runtime_error("missing dataset "+path);
 std::uint64_t n=0;f.read(reinterpret_cast<char*>(&n),8);if(n<1000||n>100000000)throw std::runtime_error("invalid dataset header");
 d={n+1,span};d.validate();std::vector<Record> v;v.reserve(n);
 for(std::uint64_t i=1;i<=n;++i){std::uint64_t ts;f.read(reinterpret_cast<char*>(&ts),8);if(!f||ts>=span)throw std::runtime_error("invalid source timestamp or binary length");v.emplace_back(ts*d.stride+i,i);}
 char extra;if(f.read(&extra,1))throw std::runtime_error("trailing source bytes");return v;
}

static constexpr std::uint64_t phase_hash_basis = UINT64_C(1469598103934665603);

struct PhaseSegment {
    std::string name;
    std::size_t begin = 0, end = 0, query_period = 0, cancel_period = 256;
    bool shuffle_incoming = false, random_every_delete = false;
    std::uint64_t queries = 0, returned = 0, query_hash = phase_hash_basis;
    std::uint64_t request_hash = phase_hash_basis;
};
struct PhaseTrace { Trace whole; std::vector<PhaseSegment> segments; };

static std::vector<PhaseSegment> phase_plan(const std::string& workload, std::size_t units) {
    if (!units) throw std::invalid_argument("zero phase length");
    std::vector<PhaseSegment> answer;
    const auto add = [&](const char* name, std::size_t query, bool shuffled) {
        PhaseSegment segment;
        segment.name = name;
        segment.begin = answer.size() * units;
        segment.end = segment.begin + units;
        segment.query_period = query;
        segment.cancel_period = shuffled ? 0 : 256;
        segment.shuffle_incoming = segment.random_every_delete = shuffled;
        answer.push_back(segment);
    };
    if (workload == "sparse_dense_sparse") { add("sparse_before", 256, false); add("dense", 1, false); add("sparse_after", 256, false); }
    else if (workload == "dense_sparse") { add("dense", 1, false); add("sparse_after", 256, false); }
    else if (workload == "sparse_shuffle_sparse") { add("sparse_before", 256, false); add("shuffle", 8, true); add("sparse_after", 256, false); }
    else throw std::invalid_argument("unknown frozen phase workload");
    return answer;
}
static std::uint64_t phase_start_seed(unsigned seed) {
    return UINT64_C(0x6249037adf150be1) + std::uint64_t(seed) * 104729;
}
static std::uint64_t phase_cancel_seed(unsigned seed) {
    return UINT64_C(0x81ec39b7526a04df) ^ (std::uint64_t(seed) * 104729);
}
static std::uint64_t phase_shuffle_seed(unsigned seed) {
    return UINT64_C(0x35710df29a48b6ce) + std::uint64_t(seed) * 130363;
}
static std::uint64_t phase_mix_step(std::uint64_t hash, const Step& step) {
    hash = mix(hash, step.erased);
    hash = mix(hash, step.added.first);
    hash = mix(hash, step.added.second);
    hash = mix(hash, step.query);
    hash = mix(hash, step.lo);
    hash = mix(hash, step.hi);
    return mix(hash, step.expected_hash);
}

static PhaseTrace make_phase_trace(const std::vector<Record>& sorted, Domain domain,
                                   const std::string& workload, unsigned seed,
                                   std::size_t initial_n, std::size_t units_per_phase) {
    domain.validate();
    if (!initial_n || !units_per_phase || units_per_phase > initial_n / 3
        || initial_n > sorted.size() || units_per_phase > (sorted.size() - initial_n) / 3)
        throw std::invalid_argument("phase source/window cannot accommodate common three-cohort start domain");
    PhaseTrace result;
    result.segments = phase_plan(workload, units_per_phase);
    auto& trace = result.whole;
    // All three trajectories share the same (month, seed, N) initial window.
    // The legal start interval reserves 3 cohorts even for the 2-phase case.
    std::mt19937_64 start_random(phase_start_seed(seed));
    std::uniform_int_distribution<std::uint64_t> choose_start(0, sorted.size() - initial_n - 3 * units_per_phase);
    trace.start = choose_start(start_random);
    const auto first = sorted.begin() + trace.start;
    const auto last = first + initial_n + 3 * units_per_phase;
    if (!std::is_sorted(first, last)) throw std::invalid_argument("phase source window must be sorted");
    if ((last - 1)->first >= domain.end()) throw std::out_of_range("phase source outside calendar domain");
    trace.initial.assign(first, first + initial_n);
    std::map<std::uint64_t, std::uint64_t> reference(trace.initial.begin(), trace.initial.end());
    if (reference.size() != initial_n) throw std::invalid_argument("duplicate composite initial key");
    std::array<std::size_t, 4096> loads{};
    std::uint64_t previous_time = UINT64_MAX;
    for (const auto& record : trace.initial) {
        const auto time = record.first / domain.stride;
        if (time != previous_time) { ++trace.initial_distinct_times; previous_time = time; }
        ++loads[domain.slot(record.first)];
    }
    for (const auto load : loads) {
        trace.initial_nonempty_buckets += load > 0;
        trace.initial_max_bucket = std::max(trace.initial_max_bucket, std::uint64_t(load));
    }
    std::vector<unsigned char> alive(initial_n, 1);
    std::size_t oldest = 0;
    std::mt19937_64 cancel_random(phase_cancel_seed(seed));
    std::mt19937_64 shuffle_random(phase_shuffle_seed(seed));
    auto water = trace.initial.back().first / domain.stride;
    trace.initmax = water;
    trace.hash = mix(trace.hash, hash_records(trace.initial));
    trace.steps.reserve(result.segments.size() * units_per_phase);
    for (auto& segment : result.segments) {
        std::vector<Record> incoming(sorted.begin() + trace.start + initial_n + segment.begin,
                                     sorted.begin() + trace.start + initial_n + segment.end);
        if (segment.shuffle_incoming) std::shuffle(incoming.begin(), incoming.end(), shuffle_random);
        for (std::size_t local = 0; local < incoming.size(); ++local) {
            while (oldest < initial_n && !alive[oldest]) ++oldest;
            if (oldest == initial_n) throw std::logic_error("no remaining initial old record");
            auto position = oldest;
            const bool specified = segment.random_every_delete || (local + 1) % 256 == 0;
            if (specified) {
                // Uniform rejection sampling among ALL remaining initial rows.
                // It can select the head and never re-deletes a cancelled row.
                std::uniform_int_distribution<std::size_t> remaining(oldest, initial_n - 1);
                do { position = remaining(cancel_random); } while (!alive[position]);
            }
            alive[position] = 0;
            Step step;
            step.erased = trace.initial[position].first;
            step.added = incoming[local];
            const auto old = reference.find(step.erased);
            if (old == reference.end()) throw std::logic_error("phase reference deletion missing");
            if (old == reference.begin() || domain.slot(std::prev(old)->first) != domain.slot(step.erased))
                ++trace.head_erases;
            reference.erase(old);
            const auto after = reference.lower_bound(step.added.first);
            if (after == reference.end() || domain.slot(after->first) != domain.slot(step.added.first)) ++trace.tail_inserts;
            if (!reference.insert(step.added).second) throw std::logic_error("phase insertion duplicate composite key");
            water = std::max(water, step.added.first / domain.stride);
            if ((local + 1) % segment.query_period == 0) {
                step.query = true;
                step.hi = (water + 1) * domain.stride;
                step.lo = (water + 1 > 60 ? water + 1 - 60 : 0) * domain.stride;
                std::vector<Record> answer;
                for (auto it = reference.lower_bound(step.lo); it != reference.end() && it->first < step.hi; ++it)
                    answer.emplace_back(*it);
                step.expected_hash = hash_records(answer);
                step.expected_count = answer.size();
                trace.returned += answer.size();
                ++trace.queries;
                segment.returned += answer.size();
                ++segment.queries;
                segment.query_hash = mix(segment.query_hash, step.expected_hash);
            }
            trace.hash = phase_mix_step(trace.hash, step);
            segment.request_hash = phase_mix_step(segment.request_hash, step);
            trace.steps.push_back(step);
        }
    }
    trace.final.assign(reference.begin(), reference.end());
    trace.hash = mix(trace.hash, hash_records(trace.final));
    return result;
}


static std::uint64_t boundary_start_seed(unsigned seed) {
    return UINT64_C(0x4bc35d271908ae61) + std::uint64_t(seed) * 104729;
}
static std::uint64_t boundary_cancel_seed(unsigned seed, std::size_t initial_n) {
    return UINT64_C(0x9b51e4201cd65f37) ^ (std::uint64_t(seed) * 104729)
           ^ (std::uint64_t(initial_n) << 17);
}
static std::string boundary_name(std::size_t initial_n, std::size_t query_period,
                                 std::size_t cancel_period) {
    return "grid_n" + std::to_string(initial_n) + "_q" + std::to_string(query_period)
           + "_c" + std::to_string(cancel_period);
}

static Trace make_boundary_trace(const std::vector<Record>& sorted, Domain domain, unsigned seed,
                                 std::size_t initial_n, std::size_t units,
                                 std::size_t query_period, std::size_t cancel_period) {
    domain.validate();
    if (!initial_n || !units || !query_period || units > initial_n
        || initial_n > sorted.size() || units > sorted.size() - initial_n)
        throw std::invalid_argument("invalid boundary window, query period or source size");

    // Start selection is independent of cancellation and method-order streams.
    // Holding (source, N, seed) fixed therefore holds the window fixed across q/c.
    std::mt19937_64 start_random(boundary_start_seed(seed));
    std::uniform_int_distribution<std::uint64_t> choose_start(0, sorted.size() - initial_n - units);
    Trace trace;
    trace.start = choose_start(start_random);
    const auto first = sorted.begin() + trace.start;
    const auto last = first + initial_n + units;
    if (!std::is_sorted(first, last)) throw std::invalid_argument("boundary input window must be sorted");
    if ((last - 1)->first >= domain.end()) throw std::out_of_range("boundary source outside calendar domain");
    trace.initial.assign(first, first + initial_n);
    std::map<std::uint64_t, std::uint64_t> reference(trace.initial.begin(), trace.initial.end());
    if (reference.size() != initial_n) throw std::invalid_argument("duplicate composite source key");

    std::array<std::size_t, 4096> loads{};
    std::uint64_t last_time = UINT64_MAX;
    for (const auto& record : trace.initial) {
        const auto time = record.first / domain.stride;
        if (time != last_time) { ++trace.initial_distinct_times; last_time = time; }
        ++loads[domain.slot(record.first)];
    }
    for (const auto load : loads) {
        trace.initial_nonempty_buckets += load > 0;
        trace.initial_max_bucket = std::max(trace.initial_max_bucket, std::uint64_t(load));
    }

    std::vector<unsigned char> alive(initial_n, 1);
    std::size_t oldest = 0;
    // q is excluded: changing query frequency cannot change deletion requests.
    std::mt19937_64 cancel_random(boundary_cancel_seed(seed, initial_n));
    auto water = trace.initial.back().first / domain.stride;
    trace.initmax = water;
    trace.hash = mix(trace.hash, hash_records(trace.initial));
    trace.steps.reserve(units);
    for (std::size_t i = 0; i < units; ++i) {
        while (oldest < initial_n && !alive[oldest]) ++oldest;
        if (oldest == initial_n) throw std::logic_error("no remaining old record");
        auto position = oldest;
        if (cancel_period && (i + 1) % cancel_period == 0) {
            // Uniform rejection sampling over ALL remaining initial old rows,
            // not the first `units` rows. A cancellation can select the head.
            std::uniform_int_distribution<std::size_t> remaining(oldest, initial_n - 1);
            do { position = remaining(cancel_random); } while (!alive[position]);
        }
        alive[position] = 0;
        Step step;
        step.erased = trace.initial[position].first;
        step.added = sorted[trace.start + initial_n + i];
        const auto old = reference.find(step.erased);
        if (old == reference.end()) throw std::logic_error("boundary reference deletion missing");
        if (old == reference.begin() || domain.slot(std::prev(old)->first) != domain.slot(step.erased))
            ++trace.head_erases;
        reference.erase(old);
        const auto after = reference.lower_bound(step.added.first);
        if (after == reference.end() || domain.slot(after->first) != domain.slot(step.added.first))
            ++trace.tail_inserts;
        if (!reference.insert(step.added).second) throw std::logic_error("boundary duplicate inserted composite key");
        water = std::max(water, step.added.first / domain.stride);
        if ((i + 1) % query_period == 0) {
            step.query = true;
            step.hi = (water + 1) * domain.stride;
            step.lo = (water + 1 > 60 ? water + 1 - 60 : 0) * domain.stride;
            std::vector<Record> answer;
            for (auto it = reference.lower_bound(step.lo); it != reference.end() && it->first < step.hi; ++it)
                answer.emplace_back(*it);
            step.expected_hash = hash_records(answer);
            step.expected_count = answer.size();
            trace.returned += answer.size();
            ++trace.queries;
        }
        trace.hash = mix(trace.hash, step.erased);
        trace.hash = mix(trace.hash, step.added.first);
        trace.hash = mix(trace.hash, step.added.second);
        trace.hash = mix(trace.hash, step.query);
        trace.hash = mix(trace.hash, step.lo);
        trace.hash = mix(trace.hash, step.hi);
        trace.hash = mix(trace.hash, step.expected_hash);
        trace.steps.push_back(step);
    }
    trace.final.assign(reference.begin(), reference.end());
    trace.hash = mix(trace.hash, hash_records(trace.final));
    return trace;
}


}
