"""Shared manifest and point-density utilities; no data or model weights included."""
import csv
import json
from pathlib import Path
import cv2
import numpy as np


def labeled_examples(manifest):
    examples={}
    with Path(manifest).open() as f:
        for row in csv.DictReader(f):
            path=Path(row['file'])
            label=path.with_suffix('.json')
            if not label.is_file():continue
            points=json.loads(label.read_text()).get('points')
            if not isinstance(points,list):raise ValueError('Label needs points: '+str(label))
            recording=row.get('recording_id')
            if not recording:raise ValueError('Manifest requires recording_id for leakage-free splitting')
            examples[str(path)]={'path':path,'points':points,'recording_id':recording}
    return list(examples.values())


def gaussian_density(points, original_size, output_size, sigma=2):
    width,height=original_size;ow,oh=output_size
    result=np.zeros((oh,ow),np.float32);radius=max(1,int(3*sigma))
    for x,y in points:
        if not (0<=x<width and 0<=y<height):raise ValueError('Labeled point lies outside image')
        cx=min(ow-1,int(x*ow/width));cy=min(oh-1,int(y*oh/height))
        x0,x1=max(0,cx-radius),min(ow,cx+radius+1);y0,y1=max(0,cy-radius),min(oh,cy+radius+1)
        yy,xx=np.mgrid[y0:y1,x0:x1];g=np.exp(-((xx-cx)**2+(yy-cy)**2)/(2*sigma**2))
        result[y0:y1,x0:x1]+=g/g.sum()
    return result
