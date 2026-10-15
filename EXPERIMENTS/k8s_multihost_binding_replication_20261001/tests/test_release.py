import importlib.util,json,sys,unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('mh',ROOT/'src'/'multihost_runner.py')
mh=importlib.util.module_from_spec(spec); spec.loader.exec_module(mh)

class ReleaseTests(unittest.TestCase):
    def test_frozen_matrix(self):
        self.assertEqual(len(mh.CFG['science_seeds']),20)
        self.assertEqual(len(mh.METHODS),3)
        self.assertEqual(len(mh.CFG['science_seeds'])*len(mh.METHODS),60)
        self.assertEqual(set(mh.CFG['science_seeds']),set(mh.SOURCE_S1))
    def test_all_cases_reconstruct(self):
        info={'rack_to_node':{'rack-a':'rack-a','rack-b':'rack-b','rack-c':'rack-c'}}
        for seed in mh.CFG['science_seeds']:
            p,pe,plans,state=mh.build_problem(seed,info)
            self.assertAlmostEqual(mh.lc.max_conflict_util(p,p.current_placement),1.25,places=8)
            self.assertFalse(mh.lc.evaluate_placement(p,plans['Affinity-Bytes'],mh.RISK).feasible)
            self.assertTrue(mh.lc.evaluate_placement(p,plans['Affinity-Bytes+Admission'],mh.RISK).feasible)
            self.assertTrue(mh.lc.evaluate_placement(p,plans['MAPE-CAP-WS'],mh.RISK).feasible)
            self.assertEqual({r.cpu_request for r in pe.replicas},{0.1})
            self.assertEqual({r.memory_request_mb for r in pe.replicas},{128.0})
    def test_k3s_version_and_resource_gates(self):
        self.assertEqual(mh.CFG['expected_kubelet_version'],'v1.33.1+k3s1')
        self.assertEqual(mh.CFG['expected_kubernetes_base_version'],'v1.33.1')
        self.assertGreaterEqual(float(mh.CFG['minimum_agent_allocatable_memory_mb']),1200.0)
        self.assertGreaterEqual(float(mh.CFG['minimum_server_allocatable_memory_mb']),3000.0)
        self.assertEqual(mh.CFG['method_order_seed'],20260926)
        self.assertEqual(mh.CFG['bootstrap_seed'],20260926)
        self.assertEqual(mh.CFG['expected_node_architecture'],'amd64')
        self.assertEqual(mh.CFG['expected_node_os'],'linux')
    def test_host_fingerprint_probe_present(self):
        text=(ROOT/'src'/'multihost_runner.py').read_text()
        self.assertIn('host_fingerprint_probe',text)
        self.assertIn('/host-etc/machine-id',text)
        self.assertIn('len(set(fingerprints.values())) != 3',text)
    def test_no_performance_gate_in_runner(self):
        text=(ROOT/'src'/'multihost_runner.py').read_text()
        for bad in ['p95_threshold','completion_threshold','if ep["scheduled_completion"] <','if ep["sched_p95_ms"] >']:
            self.assertNotIn(bad,text)

if __name__=='__main__': unittest.main()
