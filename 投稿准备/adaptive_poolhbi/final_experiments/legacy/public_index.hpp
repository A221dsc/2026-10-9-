#pragma once
#include "../../final/shared_allocator.hpp"
namespace pbpolicy {
struct Params{
 double scan_update=2,scan_query=2,tree_base=30,tree_log=5,migrate_base=0,migrate_per_item=30;
 std::size_t window=512,min_visits=4,high=128,low=32;double safety=1.25;
};
inline Params load_params(const std::string& path){
 Params p;std::ifstream f(path);if(!f)throw std::runtime_error("missing params "+path);std::string line;
 while(std::getline(f,line)){if(line.empty()||line[0]=='#')continue;auto i=line.find('=');if(i==std::string::npos)throw std::runtime_error("invalid parameter line");auto k=line.substr(0,i);double v=std::stod(line.substr(i+1));
 if(k=="scan_update")p.scan_update=v;else if(k=="scan_query")p.scan_query=v;else if(k=="tree_base")p.tree_base=v;else if(k=="tree_log")p.tree_log=v;else if(k=="migrate_base")p.migrate_base=v;else if(k=="migrate_per_item")p.migrate_per_item=v;
 else if(k=="window")p.window=static_cast<std::size_t>(v);else if(k=="safety")p.safety=v;else if(k=="min_visits")p.min_visits=static_cast<std::size_t>(v);else if(k=="high")p.high=static_cast<std::size_t>(v);else if(k=="low")p.low=static_cast<std::size_t>(v);else throw std::runtime_error("unknown parameter "+k);
 }return p;
}
template<Mode M>class Index{
 struct Node{Key key;Node* prev;Node* next;};
 using Tree=std::multiset<Key,std::less<Key>,Alloc<Key>>;
 struct Bucket{Node* head=nullptr;Node* tail=nullptr;Tree* tree=nullptr;std::size_t n=0;double credit=0;std::uint64_t last=0;std::size_t visits=0;};
 std::array<Bucket*,64> roots_{};MemoryStats& mem_;Params p_;pubbench::Domain domain_;std::size_t size_=0;std::uint64_t clock_=0,promotions_=0,demotions_=0,conversion_ns_=0,last_work_=0;bool building_=false;
 static constexpr bool observe_=M==Mode::Cost||M==Mode::Monitor||M==Mode::Occupancy||M==Mode::Count||M==Mode::Gated||M==Mode::EndpointGated;
 static constexpr bool count_=observe_
#ifdef COST_WORK_COUNTS
 ||true
#endif
 ;
 std::size_t slot(std::uint64_t x)const{return domain_.slot(x);}
 Bucket* bucket(std::size_t i,bool create){auto& r=roots_[i/64];if(!r&&create){Alloc<Bucket> a(mem_);r=a.allocate(64);for(std::size_t j=0;j<64;++j)std::allocator_traits<Alloc<Bucket>>::construct(a,r+j);}return r?r+i%64:nullptr;}
 const Bucket* bucket(std::size_t i)const{auto r=roots_[i/64];return r?r+i%64:nullptr;}
 template<class T,class...A>T* make(A&&...args){Alloc<T>a(mem_);T* q=a.allocate(1);try{std::allocator_traits<Alloc<T>>::construct(a,q,std::forward<A>(args)...);}catch(...){a.deallocate(q,1);throw;}return q;}
 template<class T>void destroy(T* q){if(!q)return;Alloc<T>a(mem_);std::allocator_traits<Alloc<T>>::destroy(a,q);a.deallocate(q,1);}
 void clear_nodes(Bucket& b){auto q=b.head;while(q){auto n=q->next;destroy(q);q=n;}b.head=b.tail=nullptr;}
 void append(Bucket& b,Key k){auto q=make<Node>(Node{k,b.tail,nullptr});if(b.tail)b.tail->next=q;else b.head=q;b.tail=q;}
 Node* lower(Bucket& b,Key k,std::uint64_t& work){
  auto less=[&](Key x,Key y){if constexpr(count_&&M!=Mode::EndpointGated)++work;return x<y;};
  if(!b.head||less(b.tail->key,k))return nullptr;
  auto l=b.head,r=b.tail;
  for(;;){if(!less(l->key,k))return l;if(less(r->key,k))return r->next;if(l==r)return l;if(l->next==r)return r;l=l->next;r=r->prev;if constexpr(M==Mode::EndpointGated)work+=2;}
 }
 void promote(Bucket& b){
  if(b.tree)return;
  auto start=std::chrono::steady_clock::now();Tree* t=make<Tree>(std::less<Key>{},Alloc<Key>(mem_));
  try{for(auto q=b.head;q;q=q->next)t->insert(t->end(),q->key);}catch(...){destroy(t);throw;}
  clear_nodes(b);b.tree=t;b.credit=0;b.visits=0;++promotions_;
  conversion_ns_+=std::chrono::duration_cast<std::chrono::nanoseconds>(std::chrono::steady_clock::now()-start).count();
 }
 void demote(Bucket& b){Bucket stage;try{for(auto k:*b.tree)append(stage,k);}catch(...){clear_nodes(stage);throw;}b.head=stage.head;b.tail=stage.tail;destroy(b.tree);b.tree=nullptr;b.credit=0;b.visits=0;b.last=0;++demotions_;}
 void touch(Bucket& b){if constexpr(M==Mode::FirstTouch)if(!building_&&!b.tree&&b.n>=p_.high)promote(b);}
 void observed(Bucket& b,std::uint64_t work,bool query){
  if constexpr(observe_){
   if(building_||b.tree||b.n<p_.high)return;
   if constexpr(M==Mode::Gated||M==Mode::EndpointGated){if constexpr(M==Mode::EndpointGated){if(work==0)return;}else{if(query?work==0:work<=1)return;}if(++b.visits>=16)promote(b);return;}
   if constexpr(M==Mode::Count){if(++b.visits>=16)promote(b);return;}
   // Zero avoidable work cannot pay for a conversion. Defer credit decay to
   // the next expensive observation; the global clock still advances.
   if constexpr(M==Mode::Cost||M==Mode::Monitor){if(query?work==0:work<=1)return;}
   auto gap=clock_-b.last;
   if(gap>=p_.window){b.credit=0;b.visits=0;}else b.credit*=std::exp(-double(gap)/double(p_.window));
   b.last=clock_;
   // The update tail comparison is unavoidable even for a constant-time append.
   double steps=double(query?work:(work>0?work-1:0));if constexpr(M==Mode::Occupancy)steps=double(b.n)/2;
   double gain=(query?p_.scan_query:p_.scan_update)*steps-(p_.tree_base+p_.tree_log*std::log2(double(b.n)+1));
   if(gain>0){b.credit+=gain;++b.visits;}
   double price=p_.migrate_base+p_.migrate_per_item*double(b.n);
   if(b.visits>=p_.min_visits&&b.credit>=p_.safety*price){if constexpr(M!=Mode::Monitor)promote(b);}
  }
 }
 std::vector<Key> ranged(std::uint64_t lo,std::uint64_t hi,bool active){
  std::vector<Key> out;hi=std::min(hi,domain_.end());last_work_=0;if(active&&!building_)++clock_;if(lo>=hi)return out;
  for(std::size_t i=slot(lo),last=slot(hi-1);i<=last;++i){auto b=bucket(i,false);if(!b)continue;if(active)touch(*b);std::uint64_t work=0;
   if(b->tree){auto end=b->tree->lower_bound({hi,0});for(auto q=b->tree->lower_bound({lo,0});q!=end;++q)out.push_back(*q);}
   else for(auto q=b->head;q;q=q->next){if(q->key.first>=hi){if constexpr(count_&&M!=Mode::EndpointGated)++work;break;}if(q->key.first>=lo)out.push_back(q->key);else if constexpr(count_)++work;}
   last_work_+=work;if(active)observed(*b,work,true);
  }return out;
 }
public:
 explicit Index(MemoryStats& s,pubbench::Domain d,Params p={}):mem_(s),p_(p),domain_(d){domain_.validate();if(!p.window||!p.min_visits||!p.high||p.low>=p.high||p.safety<=0||p.scan_query<=0||p.scan_update<=0||p.tree_base<0||p.tree_log<0||p.migrate_base<0||p.migrate_per_item<=0)throw std::invalid_argument("invalid policy params");}
 Index(const Index&)=delete;Index&operator=(const Index&)=delete;
 ~Index(){for(auto r:roots_)if(r){for(std::size_t j=0;j<64;++j){clear_nodes(r[j]);destroy(r[j].tree);}Alloc<Bucket>a(mem_);for(std::size_t j=0;j<64;++j)std::allocator_traits<Alloc<Bucket>>::destroy(a,r+j);a.deallocate(r,64);}}
 void insert(Key k){auto i=slot(k.first);if(!building_)++clock_;last_work_=0;auto& b=*bucket(i,true);touch(b);
  if constexpr(M==Mode::AllTree)if(!b.tree)b.tree=make<Tree>(std::less<Key>{},Alloc<Key>(mem_));
  if(b.tree)b.tree->insert(k);else{auto pos=lower(b,k,last_work_);auto prev=pos?pos->prev:b.tail;auto q=make<Node>(Node{k,prev,pos});if(prev)prev->next=q;else b.head=q;if(pos)pos->prev=q;else b.tail=q;}
  ++b.n;++size_;if constexpr(M==Mode::Fixed)if(!b.tree&&b.n>=p_.high)promote(b);observed(b,last_work_,false);
 }
 bool erase(Key k){auto i=slot(k.first);if(!building_)++clock_;last_work_=0;auto b=bucket(i,false);if(!b)return false;touch(*b);bool found=false;
  if(b->tree){auto q=b->tree->find(k);if(q!=b->tree->end()){b->tree->erase(q);found=true;}}
  else{auto q=lower(*b,k,last_work_);if(q&&q->key==k){if(q->prev)q->prev->next=q->next;else b->head=q->next;if(q->next)q->next->prev=q->prev;else b->tail=q->prev;destroy(q);found=true;}}
  if(found){--b->n;--size_;if constexpr(M==Mode::Fixed)if(b->tree&&p_.low&&b->n<=p_.low)demote(*b);}
  observed(*b,last_work_,false);return found;
 }
 void build(const std::vector<Key>& v){if(size_)throw std::logic_error("build requires empty index");if(!std::is_sorted(v.begin(),v.end()))throw std::invalid_argument("build must be sorted");building_=true;try{for(auto k:v)insert(k);}catch(...){building_=false;throw;}building_=false;clock_=0;last_work_=0;}
 std::vector<Key> range(std::uint64_t l,std::uint64_t h){return ranged(l,h,true);}
 std::vector<Key> peek_range(std::uint64_t l,std::uint64_t h){return ranged(l,h,false);}
 std::vector<Key> values()const{std::vector<Key>v;v.reserve(size_);for(auto r:roots_)if(r)for(std::size_t j=0;j<64;++j){auto& b=r[j];if(b.tree)for(auto k:*b.tree)v.push_back(k);else for(auto q=b.head;q;q=q->next)v.push_back(q->key);}return v;}
 void force_promote(std::uint64_t x){auto b=bucket(slot(x),false);if(b)promote(*b);}
 std::size_t size()const{return size_;}std::uint64_t last_work()const{return last_work_;}
 std::uint64_t promotions()const{return promotions_;}std::uint64_t demotions()const{return demotions_;}std::uint64_t conversion_ns()const{return conversion_ns_;}
 std::size_t tree_buckets()const{std::size_t n=0;for(auto r:roots_)if(r)for(std::size_t j=0;j<64;++j)n+=r[j].tree!=nullptr;return n;}
};
}

namespace pubbench {
class OriginalHBI {
 struct Node { Key key; Node* prev; Node* next; };
 struct Bucket { Node* head=nullptr; Node* tail=nullptr; std::size_t size=0; };
 std::size_t bins_, roots_, width_, size_=0;
 bool two_;
 std::vector<std::unique_ptr<std::vector<Bucket>>> directory_;
 mutable std::uint64_t comparisons_=0;
 Domain domain_;
 static std::size_t checked_bins(std::size_t bins){
  if(bins<64 || bins%64 || bins>1048576)throw std::invalid_argument("bins must be a multiple of 64 in [64,1048576]");
  return bins;
 }
 std::size_t index(std::uint64_t key) const {return domain_.slot(key);}
 Bucket* bucket(std::size_t i,bool create){
  auto& p=directory_[i/width_];
  if(!p && create)p=std::make_unique<std::vector<Bucket>>(width_);
  return p? &(*p)[i%width_]:nullptr;
 }
 const Bucket* bucket(std::size_t i) const {
  const auto& p=directory_[i/width_];return p? &(*p)[i%width_]:nullptr;
 }
 bool less(Key a,Key b) const {
#ifdef HBI_COUNT
  ++comparisons_;
#endif
  return a<b;
 }
 Node* lower(Bucket& b,Key key) const {
  if(!b.head)return nullptr;
  if(less(b.tail->key,key))return nullptr;
  Node* left=b.head;
  if(!two_){while(left && less(left->key,key))left=left->next;return left;}
  Node* right=b.tail;
  for(;;){
   if(!less(left->key,key))return left;
   if(less(right->key,key))return right->next;
   if(left==right)return left;
   if(left->next==right)return right;
   left=left->next;right=right->prev;
  }
 }
 template<class F> void scan(F visit,bool reverse=false) const {
  if(!reverse){for(const auto& p:directory_)if(p)for(const auto& b:*p)for(auto q=b.head;q;q=q->next)visit(q->key);}
  else {for(auto it=directory_.rbegin();it!=directory_.rend();++it)if(*it)for(auto jt=(*it)->rbegin();jt!=(*it)->rend();++jt)for(auto q=jt->tail;q;q=q->prev)visit(q->key);}
 }
public:
 explicit OriginalHBI(Domain d,std::size_t bins=4096,bool two=true):bins_(checked_bins(bins)),roots_(std::min<std::size_t>(64,bins_)),width_(bins_/roots_),two_(two),directory_(roots_),domain_(d) {domain_.validate();if(bins!=4096)throw std::invalid_argument("public protocol uses 4096 bins");}
 OriginalHBI(const OriginalHBI&)=delete;OriginalHBI& operator=(const OriginalHBI&)=delete;
 ~OriginalHBI(){for(auto& p:directory_)if(p)for(auto& b:*p){auto q=b.head;while(q){auto n=q->next;delete q;q=n;}}}
 void insert(Key key){
  auto& b=*bucket(index(key.first),true);auto pos=lower(b,key);
  auto prev=pos?pos->prev:b.tail;auto q=new Node{key,prev,pos};
  if(prev)prev->next=q;else b.head=q;
  if(pos)pos->prev=q;else b.tail=q;
  ++b.size;++size_;
 }
 bool erase(Key key){
  auto b=bucket(index(key.first),false);if(!b)return false;
  auto q=lower(*b,key);if(!q || q->key!=key)return false;
  if(q->prev)q->prev->next=q->next;else b->head=q->next;
  if(q->next)q->next->prev=q->prev;else b->tail=q->prev;
  delete q;--b->size;--size_;return true;
 }
 void build(const std::vector<Key>& input){for(auto k:input)insert(k);}
 std::vector<Key> values(bool reverse=false) const {std::vector<Key> out;out.reserve(size_);scan([&](Key k){out.push_back(k);},reverse);return out;}
 std::vector<Key> range(std::uint64_t lo,std::uint64_t hi) const {
  std::vector<Key> out;hi=std::min(hi,domain_.end());
  if(lo>=hi)return out;
  auto first=index(lo),last=index(hi-1);
  for(auto i=first;i<=last;++i){auto b=bucket(i);if(b)for(auto q=b->head;q;q=q->next){if(q->key.first>=hi)break;if(q->key.first>=lo)out.push_back(q->key);}}
  return out;
 }
 void erase(std::uint64_t code){erase(Key{code,code%domain_.stride});}
 std::size_t size() const{return size_;}
 std::size_t memory_bytes()const{return sizeof(*this)+structural_bytes();}
 std::size_t tree_buckets()const{return 0;}
 std::size_t promotions()const{return 0;}
 std::uint64_t conversion_ns()const{return 0;}
 void reset_comparisons(){comparisons_=0;}
 std::uint64_t comparisons() const{return comparisons_;}
 std::size_t max_load() const {std::size_t m=0;for(auto& p:directory_)if(p)for(auto& b:*p)m=std::max(m,b.size);return m;}
 std::size_t allocated_bins() const {std::size_t n=0;for(auto& p:directory_)if(p)n+=width_;return n;}
 std::size_t structural_bytes() const {return size_*sizeof(Node)+allocated_bins()*sizeof(Bucket)+roots_*sizeof(std::unique_ptr<std::vector<Bucket>>)+(allocated_bins()/width_)*sizeof(std::vector<Bucket>);}
};

template<pbpolicy::Mode M>class Policy {
 pbpolicy::MemoryStats memory_;Domain d_;pbpolicy::Index<M> x_;
public:
 explicit Policy(Domain d):d_(d),x_(memory_,d){}
 void build(const std::vector<Record>& v){x_.build(v);}
 void insert(Record k){x_.insert(k);}
 void erase(std::uint64_t k){x_.erase({k,k%d_.stride});}
 std::vector<Record> range(std::uint64_t l,std::uint64_t h){return x_.range(l,h);}
 std::vector<Record> values()const{return x_.values();}
 std::size_t size()const{return x_.size();}
 std::size_t tree_buckets()const{return x_.tree_buckets();}
 std::size_t promotions()const{return x_.promotions();}
 std::uint64_t conversion_ns()const{return x_.conversion_ns();}
 std::size_t memory_bytes()const{return sizeof(*this)+memory_.current;}
};
using SharedList=Policy<pbpolicy::Mode::List>;
using Fixed=Policy<pbpolicy::Mode::Fixed>;
using Gated=Policy<pbpolicy::Mode::Gated>;
using EndpointGated=Policy<pbpolicy::Mode::EndpointGated>;
}
