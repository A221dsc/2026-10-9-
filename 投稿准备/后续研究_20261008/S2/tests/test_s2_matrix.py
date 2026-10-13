import importlib.util, math, pathlib, unittest
TOOLS=pathlib.Path(__file__).resolve().parents[1]/'tools'
SPEC=importlib.util.spec_from_file_location('s2_matrix',TOOLS/'s2_matrix.py')
M=None
if SPEC and SPEC.origin and pathlib.Path(SPEC.origin).exists():
 M=importlib.util.module_from_spec(SPEC);SPEC.loader.exec_module(M)

class MatrixTests(unittest.TestCase):
 def setUp(self): self.assertIsNotNone(M,'S2 matrix/acceptance tool not implemented')
 def test_native_unique_cells(self):
  c=M.native_cells();self.assertEqual(len(c),270);self.assertEqual(len({tuple(x.items()) for x in c}),270)
 def test_native_child_order(self):
  self.assertEqual(M.pair_order(),[('AB','A'),('AB','B'),('BA','B'),('BA','A')])
 def test_aa_counts_and_before_after(self):
  for p in ('before','after'):self.assertEqual(len(M.aa_cells(p)),45)
  self.assertEqual(sum(len(M.pair_order()) for x in M.aa_cells('before')+M.aa_cells('after')),360)
 def test_resource_longest_separate(self):
  cells=M.resource_cells();self.assertEqual(len(cells),120);self.assertEqual({x['U'] for x in cells},{1048576});self.assertEqual({x['mode'] for x in cells},{'resource'})
 def test_no_final_seed_in_aa(self):
  self.assertEqual({x['seed'] for x in M.aa_cells('before')},{101001})
  self.assertEqual({x['seed'] for x in M.native_cells()},set(range(100001,100011)))
 def test_unknown_aa_position(self):
  with self.assertRaises(ValueError):M.aa_cells('middle')
 def test_geometric_pair_avoids_absolute_average(self):
  self.assertAlmostEqual(M.pair_ratio([(1,2),(100,50)]),1.)
 def test_nonpositive_time_rejected(self):
  for pairs in ([(0,1),(1,1)],[(1,float('nan')),(1,1)],[(1,1)]):
   with self.assertRaises(ValueError):M.pair_ratio(pairs)
 def test_accept_native_clock_and_identity(self):
  x={'method':'R6','mode':'native','cache_sha':'a'*64,'seed':'100001'}
  row={**x,'verified':'true','build_ns':'10','online_ns':'20','total_ns':'30','destroy_ns':'2','owner_current_after_destroy':'NA','owner_live_after_destroy':'NA','promotions':'40','scheduled_demotions':'39','cleanup_demotions':'1','total_demotions':'40','peak_tree_buckets':'32','final_tree_buckets':'0'}
  self.assertTrue(M.validate_raw(x,row))
  row['total_ns']='31'
  with self.assertRaises(ValueError):M.validate_raw(x,row)
 def test_identity_and_count_invariants_rejected(self):
  x={'method':'R6','mode':'resource','cache_sha':'a'*64}
  row={**x,'verified':'true','build_ns':'10','online_ns':'20','total_ns':'30','destroy_ns':'2','owner_current_after_destroy':'0','owner_live_after_destroy':'0','promotions':'40','scheduled_demotions':'39','cleanup_demotions':'1','total_demotions':'40','peak_tree_buckets':'32','final_tree_buckets':'0'}
  for field,value in [('cache_sha','b'*64),('total_demotions','1'),('peak_tree_buckets','33'),('owner_current_after_destroy','1')]:
   bad={**row,field:value}
   with self.assertRaises(ValueError):M.validate_raw(x,bad)
 def test_recovery_prefix_no_gaps_no_duplicates(self):
  plans=['a','b','c'];self.assertEqual(M.sealed_prefix(plans,['a','b']),2)
  for completed in (['b'],['a','c'],['a','a']):
   with self.assertRaises(ValueError):M.sealed_prefix(plans,completed)
 def test_no_cross_mode_ranking(self):
  with self.assertRaises(ValueError):M.require_native_rank([{'mode':'native'},{'mode':'resource'}])
  self.assertTrue(M.require_native_rank([{'mode':'native'}]))
 def test_actual_execution_success_required(self):
  self.assertTrue(hasattr(M,'validate_execution'),'actual process receipt validation missing')
  command=['pin','8','driver','run']; receipt={'command':command,'actual_exit_observed':True,'exit_code':0}
  self.assertTrue(M.validate_execution(command,receipt))
 def test_bad_actual_execution_rejected(self):
  self.assertTrue(hasattr(M,'validate_execution'),'actual process receipt validation missing')
  command=['driver','run'];receipt={'command':command,'actual_exit_observed':True,'exit_code':0}
  for changed in ({'exit_code':1},{'exit_code':None},{'actual_exit_observed':False},{'command':['other','run']}):
   with self.assertRaises(ValueError):M.validate_execution(command,{**receipt,**changed})
  with self.assertRaises(ValueError):M.validate_execution(command,{})
 def test_raw_attached_failure_is_not_success(self):
  self.assertTrue(hasattr(M,'validate_execution'),'actual process receipt validation missing')
  with self.assertRaises(ValueError):M.validate_execution(['driver'],{'command':['driver'],'exit_code':1,'actual_exit_observed':True})
 def test_exit_code_requires_json_integer(self):
  for value in (False,0.0,'0',None,float('nan'),float('inf')):
   with self.assertRaises(ValueError):M.validate_execution(['driver'],{'command':['driver'],'exit_code':value,'actual_exit_observed':True})
 def test_tree_lifecycle_matches_conversion_counts(self):
  expected={'method':'R6','mode':'native'}
  row={**expected,'verified':'true','build_ns':'10','online_ns':'20','total_ns':'30','destroy_ns':'1','owner_current_after_destroy':'NA','owner_live_after_destroy':'NA','promotions':'2','scheduled_demotions':'1','cleanup_demotions':'0','total_demotions':'1','peak_tree_buckets':'2','final_tree_buckets':'1'}
  self.assertTrue(M.validate_raw(expected,row))
  for changed in ({'final_tree_buckets':'0'},{'peak_tree_buckets':'3'},{'promotions':'0'}):
   with self.assertRaises(ValueError):M.validate_raw(expected,{**row,**changed})
 def test_list_cannot_treeify(self):
  expected={'method':'M_LIST','mode':'native'}
  row={**expected,'verified':'true','build_ns':'10','online_ns':'20','total_ns':'30','destroy_ns':'1','owner_current_after_destroy':'NA','owner_live_after_destroy':'NA','promotions':'1','scheduled_demotions':'0','cleanup_demotions':'0','total_demotions':'0','peak_tree_buckets':'1','final_tree_buckets':'1'}
  with self.assertRaises(ValueError):M.validate_raw(expected,row)
if __name__=='__main__':unittest.main()

