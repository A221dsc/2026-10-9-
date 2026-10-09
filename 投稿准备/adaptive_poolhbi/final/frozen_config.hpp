#pragma once
#include "adaptive_types.hpp"
#include <string>
#include <stdexcept>
#include <iomanip>
#include <sstream>
#include <limits>
namespace pbadaptive {
struct FrozenConfig { std::string arm; Params params; };
// Configuration assets only. All decision semantics remain in Index.
inline FrozenConfig load_frozen_config(const std::string& arm = "R6") {
    Params p;
    p.epoch_size=512; p.min_tree_size=128; p.down_idle_epochs=4;
    p.max_convert_records=0; p.scan_ns_per_work=1.1427456845204484;
    p.conversion_base_ns=0.0; p.conversion_ns_per_record=31.412726323575615;
    p.tree_cost_provisional=true;
    for(std::size_t c=0;c<10;++c) p.tree_cost[c].fill(30+5*std::log2(128.0*double(std::uint64_t(1)<<c)+1));
#ifdef ADAPTIVE_ABLATION
    struct Arm { const char* id; Signal signal; double payback; std::size_t budget; bool demotion,cooldown; double decay; bool clip; std::size_t limit; };
    static const std::array<Arm,12> arms{{
        {"R0",Signal::Off,2,4096,false,false,1,false,1},
        {"R1",Signal::EventCount,2,4096,false,false,1,false,1},
        {"R2",Signal::ActualWork,2,4096,false,false,1,false,1},
        {"R3",Signal::ActualWork,2,4096,false,false,.75,false,1},
        {"R4",Signal::ActualWork,2,32,false,false,1,false,1},
        {"R5",Signal::ActualWork,2,32,true,false,1,false,1},
        {"R6",Signal::ActualWork,2,32,true,true,1,false,1},
        {"R7",Signal::ActualWork,2,32,true,true,.75,false,1},
        {"R8",Signal::ActualWork,2,32,true,true,1,true,1},
        {"R9",Signal::BinaryWork,2,32,true,true,1,false,1},
        {"R10",Signal::ActualWork,2,32,true,true,1,false,2},
        {"R11",Signal::ActualWork,0,32,true,true,1,false,1}
    }};
    for(const auto& a:arms) if(arm==a.id) {
        p.signal=a.signal; p.payback=a.payback; p.tree_budget=a.budget; p.demotion_enabled=a.demotion;
        p.cooldown_enabled=a.cooldown; p.decay_factor=a.decay; p.gain_clip=a.clip; p.scheduled_limit=a.limit;
        return {arm,p};
    }
    throw std::invalid_argument("unknown frozen configuration: "+arm);
#else
    if(arm!="R6") throw std::invalid_argument("production supports only R6; requested: "+arm);
    p.payback=2.0; p.tree_budget=32; p.cooldown_enabled=true;
    return {arm,p};
#endif
}
inline std::string fingerprint_json(const FrozenConfig& configuration) {
    const auto& p=configuration.params;
#ifdef ADAPTIVE_ABLATION
    const Signal signal=p.signal;
    const bool demotion=p.demotion_enabled,clip=p.gain_clip;
    const double decay=p.decay_factor;
    const std::size_t limit=p.scheduled_limit;
    const char* build_mode="ablation";
    const std::array<const char*,12> parents{{nullptr,"R0","R1","R2","R2","R4","R5","R6","R6","R6","R6","R6"}};
    std::string parent="null";
    for(int i=0;i<12;++i) if(configuration.arm=="R"+std::to_string(i) && parents[i]) parent="\""+std::string(parents[i])+"\"";
#else
    const Signal signal=Signal::ActualWork;
    const bool demotion=true,clip=false;
    const double decay=1;
    const std::size_t limit=1;
    const char* build_mode="production";
    const std::string parent="\"R5\"";
#endif
    const char* signal_name=signal==Signal::Off?"off":signal==Signal::EventCount?"event_count":signal==Signal::BinaryWork?"binary_work":"actual_work";
    std::ostringstream out; out<<std::setprecision(std::numeric_limits<double>::max_digits10)<<std::boolalpha;
    out<<"{\"schema\":\"adaptive_poolhbi.v4.config.v1\",\"configuration_status\":\"VALUES_FIXED_ENTRY_GATE_EXTERNAL\",\"build_mode\":\""<<build_mode
       <<"\",\"arm\":\""<<configuration.arm<<"\",\"parent\":"<<parent<<",\"parameters\":{"
       <<"\"epoch_size\":"<<p.epoch_size<<",\"min_tree_size\":"<<p.min_tree_size<<",\"down_idle_epochs\":"<<p.down_idle_epochs
       <<",\"cooldown_epochs\":"<<2*p.down_idle_epochs<<",\"max_convert_records\":"<<p.max_convert_records
       <<",\"scan_ns_per_work\":"<<p.scan_ns_per_work<<",\"conversion_base_ns\":"<<p.conversion_base_ns
       <<",\"conversion_ns_per_record\":"<<p.conversion_ns_per_record
       <<",\"tree_cost_expression\":\"30+5*log2(128*2^class+1)\",\"tree_cost_provisional\":"<<p.tree_cost_provisional
       <<",\"signal\":\""<<signal_name<<"\",\"payback\":"<<p.payback<<",\"tree_budget\":"<<p.tree_budget
       <<",\"demotion\":"<<demotion<<",\"cooldown\":"<<p.cooldown_enabled<<",\"decay_factor\":"<<decay
       <<",\"gain_clip\":"<<clip<<",\"scheduled_limit\":"<<limit<<"},\"tree_cost_ns\":[";
    for(std::size_t c=0;c<10;++c) { if(c) out<<','; out<<'['; for(std::size_t op=0;op<3;++op) { if(op) out<<','; out<<p.tree_cost[c][op]; } out<<']'; }
    out<<"],\"tree_cost_operations\":[\"insert\",\"erase\",\"range\"],\"tree_cost_unit\":\"ns/observation\",\"conversion_unit\":\"ns\""
       <<",\"credit_unit\":\""<<(signal==Signal::EventCount?"event":"ns")<<"\",\"work_unit\":\"avoidable_pointer_steps\",\"actual_work_counter_shared\":true"
       <<",\"event_threshold\":"<<(signal==Signal::EventCount?"16":"null")<<",\"payback_used\":"<<(signal!=Signal::Off && signal!=Signal::EventCount)
       <<",\"promotion_enabled\":"<<(signal!=Signal::Off)<<",\"rank_rule\":\""<<(signal==Signal::EventCount?"events_then_bucket_address":"gain_over_conversion_then_gain_then_bucket_address")
       <<"\",\"decay_execution\":\""<<(decay==1?"identity_no_decay_scan":"multiply_LIST_gain_in_all_4096_buckets_before_epoch_candidate_revalidation")
       <<"\",\"cleanup\":{\"immediate\":true,\"quota_exempt\":true,\"counter_identity\":\"total_demotions=scheduled_demotions+cleanup_demotions\"}"
       <<",\"layout\":{\"record_bytes\":"<<sizeof(Record)<<",\"node_bytes\":32,\"adaptive_tail_bytes\":32,\"bucket_bytes\":64,\"root_count\":64,\"buckets_per_root\":64,\"bucket_count\":4096,\"pointer_bytes\":"<<sizeof(void*)<<",\"eager_buckets\":true}}";
    return out.str();
}
}
