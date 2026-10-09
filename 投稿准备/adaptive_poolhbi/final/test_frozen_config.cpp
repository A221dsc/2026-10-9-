#include "frozen_config.hpp"
#include <iostream>
#include <stdexcept>
#include <array>
#include <limits>
using namespace pbadaptive;
void require(bool condition, const char* what) { if(!condition) throw std::runtime_error(what); }
void common(const Params& p) {
    require(p.epoch_size==512 && p.min_tree_size==128 && p.down_idle_epochs==4 && p.max_convert_records==0,"common integer parameters");
    require(p.scan_ns_per_work==1.1427456845204484 && p.conversion_base_ns==0.0 && p.conversion_ns_per_record==31.412726323575615,"full precision common costs");
    require(p.tree_cost_provisional,"provisional table marker");
    for(std::size_t c=0;c<10;++c) for(double cost:p.tree_cost[c])
        require(cost==30+5*std::log2(128.0*double(std::uint64_t(1)<<c)+1),"unchanged tree cost expression");
}
void default_r6(const FrozenConfig& c) {
    require(c.arm=="R6","default arm is R6"); common(c.params);
    const Params d;
    require(c.params.tree_budget==32 && c.params.payback==2.0 && c.params.cooldown_enabled,"R6 method parameters");
    require(c.params.epoch_size==d.epoch_size && c.params.min_tree_size==d.min_tree_size && c.params.down_idle_epochs==d.down_idle_epochs &&
            c.params.tree_budget==d.tree_budget && c.params.max_convert_records==d.max_convert_records && c.params.payback==d.payback &&
            c.params.scan_ns_per_work==d.scan_ns_per_work && c.params.conversion_base_ns==d.conversion_base_ns &&
            c.params.conversion_ns_per_record==d.conversion_ns_per_record && c.params.tree_cost==d.tree_cost &&
            c.params.cooldown_enabled==d.cooldown_enabled && c.params.tree_cost_provisional==d.tree_cost_provisional,"R6 equals every ordinary Params default");
#ifdef ADAPTIVE_ABLATION
    require(c.params.signal==d.signal && c.params.demotion_enabled==d.demotion_enabled && c.params.gain_clip==d.gain_clip &&
            c.params.decay_factor==d.decay_factor && c.params.scheduled_limit==d.scheduled_limit,"R6 equals every ablation Params default");
#endif
}
int main() {
    try {
        default_r6(load_frozen_config());
        for(const auto& invalid : {"", "r6", "R12", "R06", "R6 ", "R-1"}) {
            bool rejected=false; try { (void)load_frozen_config(invalid); } catch(const std::invalid_argument&) { rejected=true; }
            require(rejected,"invalid configuration must be rejected");
        }
#ifdef ADAPTIVE_ABLATION
        const std::array<int,12> parents{{-1,0,1,2,2,4,5,6,6,6,6,6}};
        const std::array<int,12> changed{{-1,0,0,5,2,3,4,5,6,0,7,1}};
        std::array<FrozenConfig,12> configurations;
        for(int i=0;i<12;++i) { configurations[i]=load_frozen_config("R"+std::to_string(i)); common(configurations[i].params); }
        for(int i=1;i<12;++i) {
            const auto& a=configurations[parents[i]].params; const auto& b=configurations[i].params;
            const std::array<bool,8> diffs{{a.signal!=b.signal,a.payback!=b.payback,a.tree_budget!=b.tree_budget,a.demotion_enabled!=b.demotion_enabled,
                a.cooldown_enabled!=b.cooldown_enabled,a.decay_factor!=b.decay_factor,a.gain_clip!=b.gain_clip,a.scheduled_limit!=b.scheduled_limit}};
            int count=0; for(int j=0;j<8;++j) { if(diffs[j]) ++count; require(diffs[j]==(j==changed[i]),"parent arm changed wrong parameter"); }
            require(count==1,"parent arm must have exactly one difference");
            require(a.tree_cost==b.tree_cost && a.scan_ns_per_work==b.scan_ns_per_work && a.conversion_ns_per_record==b.conversion_ns_per_record,"parent arm costs unchanged");
        }
        require(configurations[1].params.signal==Signal::EventCount && configurations[1].params.payback==2.0,"event gate retains unused payback");
        require(configurations[9].params.signal==Signal::BinaryWork && configurations[9].params.tree_cost==configurations[6].params.tree_cost,"binary signal does not refit costs");
        for(const auto& c:configurations) std::cout<<"CONFIG "<<fingerprint_json(c)<<'\n';
#else
        for(int i=0;i<12;++i) if(i!=6) { bool rejected=false; try { (void)load_frozen_config("R"+std::to_string(i)); } catch(const std::invalid_argument&) { rejected=true; } require(rejected,"production must reject non-R6"); }
        std::cout<<"CONFIG "<<fingerprint_json(load_frozen_config())<<'\n';
#endif
        std::cout<<"PASS frozen configuration unit checks\n"; return 0;
    } catch(const std::exception& e) { std::cerr<<"FAIL "<<e.what()<<'\n'; return 1; }
}
