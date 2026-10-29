"""Record synchronized monitor outputs and raw segments using the existing monitor."""
import argparse
import subprocess
import sys


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--config',default='config.json');p.add_argument('--camera')
    p.add_argument('--source');p.add_argument('--source-env')
    p.add_argument('--segment-seconds',type=float,default=60);p.add_argument('--max-gb',type=float,default=5)
    p.add_argument('--max-seconds',type=float);p.add_argument('--recordings-dir',default='recordings')
    p.add_argument('--frame-skip',type=int,default=1)
    a=p.parse_args()
    cmd=[sys.executable,'monitor.py','--headless','--config',a.config,'--recordings-dir',a.recordings_dir,
         '--segment-seconds',str(a.segment_seconds),'--max-gb',str(a.max_gb),'--frame-skip',str(a.frame_skip)]
    for flag,value in [('--camera',a.camera),('--source',a.source),('--source-env',a.source_env),('--max-seconds',a.max_seconds)]:
        if value is not None:cmd += [flag,str(value)]
    return subprocess.call(cmd)


if __name__=='__main__':raise SystemExit(main())
