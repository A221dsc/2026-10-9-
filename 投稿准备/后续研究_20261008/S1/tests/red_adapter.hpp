#pragma once
// Negative control only: future policy interface, actual frozen production R6.
// No policy behavior is fabricated here. New-policy assertions must fail on R6.
#include "../../../adaptive_poolhbi/final/adaptive_poolhbi_final.hpp"
namespace matched {
using namespace pbadaptive;
enum class Arm { List, ObserveList, Fixed, Event, Cost, NoIdle };
template<Arm A, std::size_t Threshold=0>
class Index : public pbadaptive::Index {
public:
    using pbadaptive::Index::Index;
    static constexpr Arm arm=A;
    static constexpr std::size_t threshold=Threshold;
};
}
