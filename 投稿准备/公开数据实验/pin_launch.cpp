// pin_launch -- run a command with a fixed CPU affinity mask.
//
// Why a launcher instead of "start /affinity": the benchmark's build phase runs
// in the first ~100 ms, so the child must be pinned from its very first
// instruction. On Windows a child inherits the parent's affinity mask, so
// setting our own mask here pins the target from process creation onward.
//
// Usage: pin_launch <mask> <exe> [args...]
//   <mask> is decimal or 0x-hex, e.g. 4 (CPU 2 only) or 0x6 (CPUs 1,2).
//
// Exits with the child's exit code, so it drops into any existing script.

#include <windows.h>

#include <cstdio>
#include <cstdlib>
#include <string>
#include <vector>

namespace {

// Quote for CreateProcessA's lpCommandLine. Args from the benchmark command
// lines are paths and numbers, none of which contain a double quote, so
// wrapping in quotes is sufficient and keeps spaces safe.
std::string quote(const char* arg) { return std::string("\"") + arg + "\""; }

}  // namespace

int main(int argc, char** argv) {
    if (argc < 3) {
        std::fprintf(stderr, "usage: pin_launch <mask> <exe> [args...]\n");
        return 2;
    }

    const unsigned long long mask = std::strtoull(argv[1], nullptr, 0);
    if (mask == 0) {
        std::fprintf(stderr, "pin_launch: affinity mask must be non-zero\n");
        return 2;
    }
    if (!SetProcessAffinityMask(GetCurrentProcess(),
                                static_cast<DWORD_PTR>(mask))) {
        std::fprintf(stderr, "pin_launch: SetProcessAffinityMask failed (%lu)\n",
                     GetLastError());
        return 3;
    }

    std::string command;
    for (int i = 2; i < argc; ++i) {
        if (!command.empty()) command += ' ';
        command += quote(argv[i]);
    }
    std::vector<char> mutable_command(command.begin(), command.end());
    mutable_command.push_back('\0');

    STARTUPINFOA startup{};
    startup.cb = sizeof(startup);
    PROCESS_INFORMATION child{};
    if (!CreateProcessA(nullptr, mutable_command.data(), nullptr, nullptr,
                        FALSE, 0, nullptr, nullptr, &startup, &child)) {
        std::fprintf(stderr, "pin_launch: CreateProcess failed (%lu)\n",
                     GetLastError());
        return 4;
    }

    WaitForSingleObject(child.hProcess, INFINITE);
    DWORD exit_code = 0;
    GetExitCodeProcess(child.hProcess, &exit_code);
    CloseHandle(child.hProcess);
    CloseHandle(child.hThread);
    return static_cast<int>(exit_code);
}
