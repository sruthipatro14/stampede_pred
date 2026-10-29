"""Synthetic/code-only tests. No camera, socket, model weights or training."""
import io
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch
import numpy as np
from alert_workflow import decorate, RepeatNotifications
from dashboard import make_handler
from density_estimator import load_density_model
from evaluate_counts import report
from training_data import gaussian_density
from backtest_forecast import backtest
from data_recording import RecordingWriter


class V2Tests(unittest.TestCase):
    def test_protected_config_bytes(self):
        old=Path('config.json.v2.bak').read_text();new=Path('config.json').read_text()
        before=json.loads(old);after=json.loads(new)
        self.assertEqual({k:after[k] for k in before},before)
        # Everything preceding the original closing brace remains literal bytes,
        # except the comma required to append the new alerts member.
        self.assertTrue(new.startswith(old.rstrip()[:-1].rstrip()))

    def test_ack_auth_and_repeat_stop(self):
        cfg=json.loads(Path('config.json').read_text())
        event=decorate({'camera':'default','zone':'Concourse','level':4,'kind':'level','trigger':'DRILL test',
                        'drill':True,'time':'2026-01-01T00:00:00+00:00','density':1,'eta_to_L4_s':0},cfg)
        self.assertTrue(event['drill']);self.assertEqual(event['staff_message']['label'],'DRILL')
        class Connection:
            def __init__(self,route,body,headers):
                data=json.dumps(body).encode()
                self.request=io.BytesIO((f'POST {route} HTTP/1.0\r\nHost: localhost\r\nContent-Type: application/json\r\nContent-Length: {len(data)}\r\n'+headers+'\r\n').encode()+data)
                self.response=bytearray()
            def makefile(self,*_):return self.request
            def sendall(self,data):self.response.extend(data)
        with tempfile.TemporaryDirectory() as directory:
            log=Path(directory)/'alerts.jsonl';acks=Path(directory)/'acks.jsonl';log.write_text(json.dumps(event)+'\n')
            def request(client='127.0.0.1',token=None,supplied='',body=None,extra=''):
                connection=Connection('/api/ack',body or {'alert_id':event['id'],'staff':'Test Staff'},supplied+extra)
                make_handler(directory,log,acks,token)(connection,(client,1),SimpleNamespace())
                headers,data=bytes(connection.response).split(b'\r\n\r\n',1)
                return int(headers.split()[1]),json.loads(data)
            self.assertEqual(request(client='192.0.2.1')[0],403)  # Test client address, no request to a camera.
            self.assertEqual(request(token='test-token')[0],403)
            self.assertEqual(request(body={'alert_id':'bad','staff':'Staff'})[0],400)
            self.assertEqual(request(body={'alert_id':'0'*32,'staff':'Test Staff'})[0],404)
            self.assertEqual(request(body={'alert_id':event['id'],'staff':'   '})[0],400)
            self.assertEqual(request(body={'alert_id':event['id'],'staff':'<script>'})[0],400)
            self.assertEqual(request(token='test-token',supplied='Authorization: Bearer wrong-token\r\n')[0],403)
            self.assertEqual(request(extra='Origin: http://untrusted.invalid\r\n')[0],403)
            repeat=RepeatNotifications(cfg,log,acks)
            with patch('alert_workflow.deliver') as delivery:
                repeat.tick(now=2000000000);self.assertEqual(delivery.call_count,1)
                code,ack=request(token='test-token',supplied='Authorization: Bearer test-token\r\n')
                self.assertEqual(code,200);self.assertEqual(ack['staff'],'Test Staff');self.assertTrue(ack['drill']);self.assertIn('timestamp',ack)
                repeat.tick(now=2000000100);self.assertEqual(delivery.call_count,1)
                self.assertEqual(request()[0],200)
                self.assertEqual(len(acks.read_text().splitlines()),1)

    def test_metrics_and_gaussian(self):
        pairs=[(0,0),(5,4),(10,8),(20,15),(35,20)]
        result=report(pairs)
        self.assertAlmostEqual(result['overall']['mae'],4.6);self.assertAlmostEqual(result['overall']['bias'],-4.6)
        self.assertAlmostEqual(result['overall']['rmse'],np.sqrt(51))
        density=gaussian_density([[0,0],[99,99]],(100,100),(20,20))
        self.assertAlmostEqual(float(density.sum()),2,places=5)

    def test_missing_density_weights(self):
        with self.assertRaisesRegex(ValueError,'Density weights missing'):load_density_model({})

    def test_retention_bound(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            for n in (1,2):
                (root/f'{n}.mp4').write_bytes(b'x'*1000)
                (root/f'{n}.json').write_text(json.dumps({'format':'crowd-monitor-segment-v1'}))
            recorder=RecordingWriter(root,'default',25,max_gb=1400/1024**3)
            recorder._bound()
            self.assertLessEqual(recorder._size(),1400)
            self.assertEqual(len(list(root.glob('*.mp4'))),1)

    def test_forecast_known_future(self):
        rows=[{'t':t,'density':t/10,'thresholds':[2,4,6],**{'forecast_'+str(h):(t+h)/10 for h in (30,60,120)}} for t in range(181)]
        result=backtest({('recording','camera','zone'):rows},tolerance=0)
        for r in result:self.assertEqual(r['mae'],0);self.assertGreater(r['n'],0)
        missing=backtest({('r','c','z'):rows[:20]},tolerance=0)
        self.assertTrue(all(r['n']==0 for r in missing))


if __name__=='__main__':unittest.main()
