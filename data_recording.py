"""Segmented local recording with monitor sidecars. Source URLs are never persisted."""
from datetime import datetime, timezone
import json
from pathlib import Path
import uuid
import cv2
from dashboard_output import camera_directory


class RecordingWriter:
    def __init__(self, root, camera, fps, segment_seconds=60, max_gb=5):
        if segment_seconds <= 0 or max_gb <= 0: raise ValueError('segment-seconds and max-gb must be positive')
        self.root, self.camera, self.fps = Path(root), camera, fps
        self.duration, self.budget = segment_seconds, int(max_gb * 1024**3)
        self.recording_id = uuid.uuid4().hex
        self.writer = None
        self.meta = None
        self.path = None

    def _size(self):
        return sum(p.stat().st_size for p in self.root.rglob('*') if p.is_file() and not p.is_symlink())

    def _bound(self):
        # Delete complete segment pairs only. Never delete arbitrary files or live segments.
        segments = sorted(self.root.rglob('*.json'), key=lambda p:p.stat().st_mtime)
        for sidecar in segments:
            if self._size() <= self.budget: break
            try: meta = json.loads(sidecar.read_text())
            except (OSError,ValueError): continue
            if meta.get('format') != 'crowd-monitor-segment-v1': continue
            video = sidecar.with_suffix('.mp4')
            if video == self.path and self.writer is not None: continue
            video.unlink(missing_ok=True); sidecar.unlink()
        if self._size() > self.budget: raise RuntimeError('Recording storage exceeds --max-gb; shorten segments or increase the budget')

    def write(self, frame, video_s):
        if self.writer is not None and video_s-self.meta['start_video_s'] >= self.duration: self.close_segment()
        if self.writer is None:
            now=datetime.now(timezone.utc)
            directory=self.root/camera_directory(self.camera)/now.strftime('%Y-%m-%d'); directory.mkdir(parents=True,exist_ok=True)
            self.path=directory/(now.strftime('%H%M%S_%f')+'_'+uuid.uuid4().hex[:8]+'.mp4')
            height,width=frame.shape[:2]
            self.writer=cv2.VideoWriter(str(self.path),cv2.VideoWriter_fourcc(*'mp4v'),self.fps,(width,height))
            if not self.writer.isOpened(): self.writer=None; raise RuntimeError('Cannot open mp4v recording writer')
            self.meta={'format':'crowd-monitor-segment-v1','recording_id':self.recording_id,
                       'camera':self.camera,'video':self.path.name,'fps':self.fps,'width':width,'height':height,
                       'start_video_s':video_s,'end_video_s':video_s,'frames':0,'samples':[]}
        self.writer.write(frame); self.meta['frames']+=1; self.meta['end_video_s']=video_s
        if self.meta['frames']%25==0: self._bound()

    def sample(self, status):
        if self.writer is not None:
            self.meta['estimator']=status.get('estimator')
            self.meta['samples'].append({'timestamp':datetime.now(timezone.utc).isoformat(),
              'frame_index':self.meta['frames']-1,'video_s':status['video_s'],'zones':status['zones']})

    def close_segment(self):
        if self.writer is None:return
        self.writer.release(); self.writer=None
        sidecar=self.path.with_suffix('.json'); temp=sidecar.with_suffix('.json.tmp')
        temp.write_text(json.dumps(self.meta,allow_nan=False)); temp.replace(sidecar)
        self._bound()
        if not sidecar.exists(): raise RuntimeError('Completed segment exceeded --max-gb and was removed; increase the budget or shorten segments')

    def close(self): self.close_segment()
