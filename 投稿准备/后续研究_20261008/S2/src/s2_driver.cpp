#include "s2_cli.hpp"
#include <iostream>
int wmain(int argc,wchar_t** argv){try{std::vector<std::string> args;for(int j=1;j<argc;++j)args.push_back(s1::path_utf8(std::filesystem::path(argv[j])));return s2::execute(s2::parse(args));}catch(const std::exception& e){std::cerr<<"S2 rejected: "<<e.what()<<'\n';return 2;}}
