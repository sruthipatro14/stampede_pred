"""Count evaluation. CSV: true_count,predicted_count; or labeled manifest estimates.
Manifest evaluation uses recorded current_estimate values, not new inference on stills.
Bands are [0,5), [5,15), [15,30), [30,infinity), without overlapping endpoints.
"""
import argparse
import csv
import json
from pathlib import Path
import math
import cv2
import numpy as np


def metrics(pairs):
    errors=[float(pred)-float(true) for true,pred in pairs]
    if not errors:return {'n':0,'mae':None,'rmse':None,'bias':None}
    if not all(math.isfinite(x) for pair in pairs for x in pair):raise ValueError('Counts must be finite')
    if any(x<0 for pair in pairs for x in pair):raise ValueError('Counts cannot be negative')
    return {'n':len(errors),'mae':sum(map(abs,errors))/len(errors),'rmse':math.sqrt(sum(x*x for x in errors)/len(errors)), 'bias':sum(errors)/len(errors)}


def report(pairs):
    return {'overall':metrics(pairs),'bands':{name:metrics([(t,p) for t,p in pairs if low<=t<high])
            for name,low,high in [('0-5',0,5),('5-15',5,15),('15-30',15,30),('30+',30,float('inf'))]},
            'bias_definition':'predicted minus true; negative means undercounting','band_endpoints':'lower inclusive, upper exclusive'}


def main():
    p=argparse.ArgumentParser(description=__doc__);g=p.add_mutually_exclusive_group(required=True)
    g.add_argument('--csv');g.add_argument('--manifest');p.add_argument('--output');p.add_argument('--estimator',choices=['yolo','density'],help='run this estimator on labeled manifest images instead of using recorded estimates');p.add_argument('--config',default='config.json');a=p.parse_args();pairs=[]
    estimator=None
    if a.estimator:
        if not a.manifest:p.error('--estimator requires --manifest')
        from estimators import create_estimator
        cfg=json.loads(Path(a.config).read_text());cfg['estimator']=a.estimator
        try:estimator=create_estimator(cfg)
        except ValueError as exc:p.error(str(exc))
    with Path(a.csv or a.manifest).open() as f:
        for row in csv.DictReader(f):
            if a.csv:pairs.append((float(row['true_count']),float(row['predicted_count'])));continue
            label=Path(row['file']).with_suffix('.json')
            if not label.exists():continue
            points=json.loads(label.read_text())['points'];poly=np.array(json.loads(row['polygon']),np.int32)
            true=sum(cv2.pointPolygonTest(poly,tuple(map(float,point)),False)>=0 for point in points)
            if estimator is not None:
                from types import SimpleNamespace
                frame=cv2.imread(row['file'])
                if frame is None:p.error('Cannot read labeled image: '+row['file'])
                mask=np.zeros(frame.shape[:2],np.uint8);cv2.fillPoly(mask,[poly],255)
                counts,_=estimator.process(frame,[SimpleNamespace(poly=poly,mask=mask)])
                pairs.append((true,float(counts[0])))
            elif row['current_estimate'] not in ('','None'):pairs.append((true,float(row['current_estimate'])))
    if not pairs:p.error('No valid labeled pairs to evaluate')
    result=report(pairs);text=json.dumps(result,indent=2);print(text)
    if a.output:Path(a.output).write_text(text)


if __name__=='__main__':main()
