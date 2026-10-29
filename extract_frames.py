"""Prioritize high-level/rising samples for labeling; preserve recording IDs for splits."""
import argparse
import csv
import json
from pathlib import Path
import cv2
from dashboard_output import camera_directory


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--recordings-dir',default='recordings');p.add_argument('--output',default='labeling')
    p.add_argument('--max-frames',type=int,default=100);a=p.parse_args()
    if a.max_frames<1:p.error('max-frames must be positive')
    candidates=[]
    for path in Path(a.recordings_dir).rglob('*.json'):
        meta=json.loads(path.read_text())
        if meta.get('format')!='crowd-monitor-segment-v1':continue
        prev={}
        for sample in meta['samples']:
            for zone in sample['zones']:
                density=zone['density']
                rising=density is not None and density>prev.get(zone['name'],density)
                prev[zone['name']]=density or 0
                candidates.append((zone['level']*10+int(rising)*5+(density or 0),path,meta,sample,zone))
    selected={}
    for _,path,meta,sample,zone in sorted(candidates,key=lambda x:x[0],reverse=True):
        key=(str(path),sample['frame_index'])
        if key not in selected and len(selected)>=a.max_frames:continue
        selected.setdefault(key,(path,meta,sample,[]))[3].append(zone)
    rows={}
    for path,meta,sample,zones in selected.values():
        video=path.with_suffix('.mp4');cap=cv2.VideoCapture(str(video))
        cap.set(cv2.CAP_PROP_POS_FRAMES,sample['frame_index']);ok,frame=cap.read();cap.release()
        if not ok:raise SystemExit('Cannot decode selected recording frame: '+str(video))
        directory=Path(a.output)/camera_directory(meta['camera'])/'images';directory.mkdir(parents=True,exist_ok=True)
        image=directory/(path.stem+'_'+str(sample['frame_index'])+'.jpg')
        if not cv2.imwrite(str(image),frame):raise SystemExit('Cannot write image: '+str(image))
        for z in zones:
            rows.setdefault(directory.parent,[]).append({'file':str(image.resolve()),'time':sample['video_s'],'zone':z['name'],
              'current_estimate':z['people'],'level':z['level'],'recording_id':meta['recording_id'],
              'camera':meta['camera'],'polygon':json.dumps(z['polygon'])})
    for directory,data in rows.items():
        with (directory/'manifest.csv').open('w',newline='') as f:
            writer=csv.DictWriter(f,fieldnames=list(data[0]));writer.writeheader();writer.writerows(data)
    print('Saved',len(selected),'images; manifests preserve recording_id. Sampling is biased toward high/rising risk; use independent representative recordings for evaluation.')


if __name__=='__main__':main()
