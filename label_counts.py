"""SCREEN REQUIRED: left-click every head/person; u undo, s save, q quit."""
import argparse
import json
from pathlib import Path
import cv2


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('images',nargs='+',type=Path);a=p.parse_args()
    for path in a.images:
        frame=cv2.imread(str(path))
        if frame is None:raise SystemExit('Cannot read image: '+str(path))
        target=path.with_suffix('.json');points=[]
        if target.exists():points=json.loads(target.read_text()).get('points',[])
        def click(event,x,y,*_):
            if event==cv2.EVENT_LBUTTONDOWN:points.append([x,y])
        cv2.namedWindow('Label every person');cv2.setMouseCallback('Label every person',click)
        print('SCREEN REQUIRED:',path,'left click person/head; u undo; s save; q quit')
        while True:
            view=frame.copy()
            for point in points:cv2.circle(view,tuple(point),4,(0,255,255),-1)
            cv2.putText(view,str(len(points))+' labeled people',(10,25),cv2.FONT_HERSHEY_SIMPLEX,.7,(0,255,255),2)
            cv2.imshow('Label every person',view);key=cv2.waitKey(30)&255
            if key==ord('u') and points:points.pop()
            if key==ord('s'):
                temp=target.with_suffix('.json.tmp');temp.write_text(json.dumps({'image':path.name,'points':points,'count':len(points),
                    'width':frame.shape[1],'height':frame.shape[0],'point_convention':'head_or_person_click'}));temp.replace(target);break
            if key==ord('q'):cv2.destroyAllWindows();return
        cv2.destroyAllWindows()


if __name__=='__main__':main()
