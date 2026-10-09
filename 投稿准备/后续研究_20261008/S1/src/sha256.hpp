#pragma once
#include <array>
#include <cstdint>
#include <filesystem>
#include <fstream>
#include <iomanip>
#include <sstream>
#include <stdexcept>
#ifndef WIN32_LEAN_AND_MEAN
#define WIN32_LEAN_AND_MEAN
#endif
#ifndef NOMINMAX
#define NOMINMAX
#endif
#include <windows.h>
namespace s1 {
inline std::string path_utf8(const std::filesystem::path& path){const auto& wide=path.native();auto length=WideCharToMultiByte(CP_UTF8,WC_ERR_INVALID_CHARS,wide.data(),static_cast<int>(wide.size()),nullptr,0,nullptr,nullptr);if(!length&&!wide.empty())throw std::runtime_error("path UTF8 conversion failed");std::string out(length,'\0');if(length)WideCharToMultiByte(CP_UTF8,WC_ERR_INVALID_CHARS,wide.data(),static_cast<int>(wide.size()),out.data(),length,nullptr,nullptr);return out;}
class SHA256 {
 std::array<std::uint32_t,8> h_{{0x6a09e667,0xbb67ae85,0x3c6ef372,0xa54ff53a,0x510e527f,0x9b05688c,0x1f83d9ab,0x5be0cd19}};
 std::array<unsigned char,64> buf_{};std::size_t used_=0;std::uint64_t bytes_=0;
 static std::uint32_t rr(std::uint32_t x,unsigned n){return(x>>n)|(x<<(32-n));}
 void block(){
  static constexpr std::uint32_t k[]={0x428a2f98,0x71374491,0xb5c0fbcf,0xe9b5dba5,0x3956c25b,0x59f111f1,0x923f82a4,0xab1c5ed5,0xd807aa98,0x12835b01,0x243185be,0x550c7dc3,0x72be5d74,0x80deb1fe,0x9bdc06a7,0xc19bf174,0xe49b69c1,0xefbe4786,0x0fc19dc6,0x240ca1cc,0x2de92c6f,0x4a7484aa,0x5cb0a9dc,0x76f988da,0x983e5152,0xa831c66d,0xb00327c8,0xbf597fc7,0xc6e00bf3,0xd5a79147,0x06ca6351,0x14292967,0x27b70a85,0x2e1b2138,0x4d2c6dfc,0x53380d13,0x650a7354,0x766a0abb,0x81c2c92e,0x92722c85,0xa2bfe8a1,0xa81a664b,0xc24b8b70,0xc76c51a3,0xd192e819,0xd6990624,0xf40e3585,0x106aa070,0x19a4c116,0x1e376c08,0x2748774c,0x34b0bcb5,0x391c0cb3,0x4ed8aa4a,0x5b9cca4f,0x682e6ff3,0x748f82ee,0x78a5636f,0x84c87814,0x8cc70208,0x90befffa,0xa4506ceb,0xbef9a3f7,0xc67178f2};
  std::uint32_t w[64];for(unsigned i=0;i<16;++i)w[i]=(std::uint32_t(buf_[4*i])<<24)|(std::uint32_t(buf_[4*i+1])<<16)|(std::uint32_t(buf_[4*i+2])<<8)|buf_[4*i+3];for(unsigned i=16;i<64;++i){auto x=w[i-15],y=w[i-2];w[i]=w[i-16]+(rr(x,7)^rr(x,18)^(x>>3))+w[i-7]+(rr(y,17)^rr(y,19)^(y>>10));}
  auto a=h_[0],b=h_[1],c=h_[2],d=h_[3],e=h_[4],f=h_[5],g=h_[6],h=h_[7];for(unsigned i=0;i<64;++i){auto t=h+(rr(e,6)^rr(e,11)^rr(e,25))+((e&f)^(~e&g))+k[i]+w[i],u=(rr(a,2)^rr(a,13)^rr(a,22))+((a&b)^(a&c)^(b&c));h=g;g=f;f=e;e=d+t;d=c;c=b;b=a;a=t+u;}h_[0]+=a;h_[1]+=b;h_[2]+=c;h_[3]+=d;h_[4]+=e;h_[5]+=f;h_[6]+=g;h_[7]+=h;
 }
public:
 void update(const void* raw,std::size_t n){auto p=static_cast<const unsigned char*>(raw);bytes_+=n;while(n){auto amount=std::min(n,64-used_);std::copy(p,p+amount,buf_.begin()+used_);used_+=amount;p+=amount;n-=amount;if(used_==64){block();used_=0;}}}
 void u64(std::uint64_t n){unsigned char b[8];for(unsigned j=0;j<8;++j)b[j]=static_cast<unsigned char>(n>>(8*j));update(b,8);}
 std::string finish(){auto bits=bytes_*8;unsigned char pad=128;update(&pad,1);pad=0;while(used_!=56)update(&pad,1);unsigned char len[8];for(unsigned j=0;j<8;++j)len[7-j]=static_cast<unsigned char>(bits>>(8*j));update(len,8);std::ostringstream out;out<<std::hex<<std::setfill('0');for(auto n:h_)out<<std::setw(8)<<n;return out.str();}
};
inline std::string sha_file(const std::filesystem::path& path){std::ifstream f(path,std::ios::binary);if(!f)throw std::runtime_error("SHA input unavailable: "+path.u8string());SHA256 sha;std::array<char,65536>b;while(f){f.read(b.data(),b.size());sha.update(b.data(),static_cast<std::size_t>(f.gcount()));}if(!f.eof())throw std::runtime_error("SHA read failed");return sha.finish();}
inline std::string sha_text(const std::string& str){SHA256 sha;sha.update(str.data(),str.size());return sha.finish();}
inline void require_sha(const std::filesystem::path& p,const std::string& expected){if(sha_file(p)!=expected)throw std::runtime_error("actual SHA mismatch: "+p.u8string());}
}
