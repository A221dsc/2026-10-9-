#pragma once
#include "public_index.hpp"
#include <memory>
#include <set>
namespace pubbench {
template<bool Gate> class PoolIndex {
 struct Node{Record key;Node* prev;Node* next;};
 using Tree=std::multiset<Record>;
 struct Bucket{Node* head=nullptr;Node* tail=nullptr;Tree* tree=nullptr;std::size_t n=0,visits=0;};
 struct Chunk{std::unique_ptr<Node[]> data;std::size_t count;};
 Domain d_;std::array<Bucket*,64> roots_{};std::vector<Chunk> chunks_;Node* free_=nullptr;Node* cursor_=nullptr;
 std::size_t unused_=0,size_=0;std::uint64_t promotions_=0,conversion_=0;
 Bucket* bucket(std::size_t i,bool create){auto& root=roots_[i/64];if(!root&&create)root=new Bucket[64];return root?root+i%64:nullptr;}
 const Bucket* bucket(std::size_t i)const{auto root=roots_[i/64];return root?root+i%64:nullptr;}
 void grow(std::size_t count){auto nodes=std::make_unique<Node[]>(count);auto ptr=nodes.get();chunks_.push_back({std::move(nodes),count});cursor_=ptr;unused_=count;}
 Node* node(Record r,Node* before,Node* after){Node* q;
  if(free_){q=free_;free_=q->next;}else{if(!unused_)grow(1024);q=cursor_++;--unused_;}
  q->key=r;q->prev=before;q->next=after;return q;
 }
 void recycle(Node* q)noexcept{q->next=free_;free_=q;}
 static Node* lower(Bucket& b,Record r,std::uint64_t& work){
  if(!b.head||b.tail->key<r)return nullptr;
  auto l=b.head,right=b.tail;
  for(;;){if(!(l->key<r))return l;if(right->key<r)return right->next;if(l==right)return l;if(l->next==right)return right;l=l->next;right=right->prev;if constexpr(Gate)work+=2;}
 }
 void promote(Bucket& b){
  if(b.tree)return;auto a=std::chrono::steady_clock::now();auto stage=std::make_unique<Tree>();
  for(auto q=b.head;q;q=q->next)stage->insert(stage->end(),q->key);
  auto q=b.head;while(q){auto next=q->next;recycle(q);q=next;}
  b.head=b.tail=nullptr;b.tree=stage.release();b.visits=0;++promotions_;
  conversion_+=std::chrono::duration_cast<std::chrono::nanoseconds>(std::chrono::steady_clock::now()-a).count();
 }
 void observe(Bucket& b,std::uint64_t work){if constexpr(Gate)if(!b.tree&&b.n>=128&&work>0&&++b.visits>=16)promote(b);}
 static void link(Bucket& b,Node* q){if(q->prev)q->prev->next=q;else b.head=q;if(q->next)q->next->prev=q;else b.tail=q;}
public:
 explicit PoolIndex(Domain d):d_(d){d_.validate();}
 PoolIndex(const PoolIndex&)=delete;PoolIndex&operator=(const PoolIndex&)=delete;
 ~PoolIndex(){for(auto r:roots_)if(r){for(std::size_t i=0;i<64;++i)delete r[i].tree;delete[] r;}}
 void build(const std::vector<Record>& v){
  if(size_||!chunks_.empty())throw std::logic_error("pool build requires fresh index");
  if(!std::is_sorted(v.begin(),v.end()))throw std::invalid_argument("unsorted pool bulk input");
  if(v.empty())return;if(v.back().first>=d_.end())throw std::out_of_range("bulk record outside calendar");
  grow(v.size());std::size_t slot=d_.slot(v.front().first);Bucket* b=bucket(slot,true);
  auto boundary=[&](std::size_t i){return (std::uint64_t)(((__uint128_t)(i+1)*d_.span+4095)/4096)*d_.stride;};
  auto next=boundary(slot);
  for(auto r:v){if(r.first>=next){do{++slot;next=boundary(slot);}while(r.first>=next);b=bucket(slot,true);}
   auto q=node(r,b->tail,nullptr);link(*b,q);++b->n;++size_;
  }
 }
 void insert(Record r){auto& b=*bucket(d_.slot(r.first),true);std::uint64_t work=0;
  if(b.tree)b.tree->insert(r);else{auto after=lower(b,r,work);auto q=node(r,after?after->prev:b.tail,after);link(b,q);}++b.n;++size_;observe(b,work);
 }
 void erase(std::uint64_t key){auto b=bucket(d_.slot(key),false);if(!b)return;Record r{key,key%d_.stride};std::uint64_t work=0;bool found=false;
  if(b->tree){auto q=b->tree->find(r);if(q!=b->tree->end()){b->tree->erase(q);found=true;}}else{auto q=lower(*b,r,work);if(q&&q->key==r){if(q->prev)q->prev->next=q->next;else b->head=q->next;if(q->next)q->next->prev=q->prev;else b->tail=q->prev;recycle(q);found=true;}}
  if(found){--b->n;--size_;}observe(*b,work);
 }
 std::vector<Record> range(std::uint64_t lo,std::uint64_t hi){std::vector<Record> out;hi=std::min(hi,d_.end());if(lo>=hi)return out;
  auto last=d_.slot(hi-1);for(std::size_t i=d_.slot(lo);i<=last;++i){auto b=bucket(i,false);if(!b)continue;std::uint64_t work=0;
   if(b->tree){auto end=b->tree->lower_bound({hi,0});for(auto q=b->tree->lower_bound({lo,0});q!=end;++q)out.push_back(*q);}
   else for(auto q=b->head;q;q=q->next){if(q->key.first>=hi)break;if(q->key.first>=lo)out.push_back(q->key);else if constexpr(Gate)++work;}
   observe(*b,work);
  }return out;
 }
 std::vector<Record> values()const{std::vector<Record> out;out.reserve(size_);for(auto root:roots_)if(root)for(std::size_t i=0;i<64;++i){auto& b=root[i];if(b.tree)for(auto r:*b.tree)out.push_back(r);else for(auto q=b.head;q;q=q->next)out.push_back(q->key);}return out;}
 std::size_t size()const{return size_;}
 std::size_t tree_buckets()const{std::size_t n=0;for(auto r:roots_)if(r)for(std::size_t i=0;i<64;++i)n+=r[i].tree!=nullptr;return n;}
 std::size_t promotions()const{return promotions_;}
 std::uint64_t conversion_ns()const{return conversion_;}
 std::size_t pool_capacity()const{std::size_t n=0;for(auto& chunk:chunks_)n+=chunk.count;return n;}
};
using PoolHBI=PoolIndex<false>;
using PoolEndpoint=PoolIndex<true>;
}
