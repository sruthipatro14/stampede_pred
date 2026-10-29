"""Category boundaries and dashboard contract; synthetic data only."""
import json
import math
import unittest
from pathlib import Path
from monitor import Zone, zone_snapshot, load_cfg
from dashboard_output import finite_json

class Phase1Tests(unittest.TestCase):
    def setUp(self): self.cfg=load_cfg('config.json')
    def zone(self,index=0): return Zone(self.cfg['zones'][index],self.cfg['categories'],(480,640,3))
    def tick(self,z,t,d): z.raw.append((t-1,d)); z.tick(t,self.cfg)
    def test_category_boundaries(self):
        for i in (0,1):
            z=self.zone(i)
            for level,t in enumerate(z.th,2):
                self.assertEqual(z.lv(t),level)
                self.assertEqual(z.lv(t-1e-8),level-1)
            self.assertIsNone(z.lv(float('nan')))
    def test_delayed_people_match_density(self):
        z=self.zone();self.tick(z,0,2);z.people=999
        s=zone_snapshot(z,self.cfg)
        self.assertEqual(s['people'],s['density']*z.area)
        self.assertIsNone(s['forecast_30']);self.assertEqual(s['eta_state'],'unavailable')
    def test_persistence_and_hysteresis(self):
        z=self.zone();self.tick(z,0,4.5)
        self.assertEqual(z.level,1)
        self.assertEqual(zone_snapshot(z,self.cfg)['density_level'],3)
        self.assertEqual(zone_snapshot(z,self.cfg)['trigger'],'forecast +120s')
        self.tick(z,10,4.5);self.assertEqual(z.level,3)
        self.tick(z,11,3.5);self.assertEqual(z.level,3) # strict fall boundary
        self.assertIn('hysteresis',zone_snapshot(z,self.cfg)['trigger'])
        self.tick(z,12,3.49);self.assertEqual(z.level,2)
    def test_overrides_and_forecasts(self):
        for i in (0,1):
            z=self.zone(i);self.tick(z,0,1);self.tick(z,10,3)
            s=zone_snapshot(z,self.cfg)
            for h in (30,60,120): self.assertEqual(s['forecast_levels'][str(h)],z.lv(s['forecast_'+str(h)]))
        z=self.zone();self.tick(z,0,8);self.assertNotIn('packed crowd',zone_snapshot(z,self.cfg)['active_overrides'])
        self.tick(z,1,8.01);self.assertEqual(z.eff,4)
        self.assertIn('packed crowd',zone_snapshot(z,self.cfg)['active_overrides'])
        z=self.zone(1);z.speed=0.05;self.tick(z,0,2.5);self.tick(z,10,2.5)
        self.assertEqual(z.eff,4);self.assertIn('stalled crowd',zone_snapshot(z,self.cfg)['active_overrides'])
    def test_eta_states_and_nonfinite(self):
        z=self.zone();self.assertIsNone(zone_snapshot(z,self.cfg)['level'])
        self.tick(z,0,1);self.tick(z,10,1)
        self.assertEqual(zone_snapshot(z,self.cfg)['eta_state'],'not_rising')
        self.tick(z,20,1.1);self.assertEqual(zone_snapshot(z,self.cfg)['eta_state'],'beyond_horizon')
        self.assertEqual(finite_json({'v':float('inf')}),{'v':None})
    def test_configuration_bytes(self): self.assertEqual(Path('config.json').read_bytes(),Path('backups/phase1/config.json').read_bytes())

if __name__=='__main__':unittest.main()
