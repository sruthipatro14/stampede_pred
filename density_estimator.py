"""User-supplied TorchScript model: RGB [0,1] BCHW -> nonnegative Bx1xHxW density.
The sum of output pixels is the estimated count; output resolution may differ.
No architecture or weights are supplied. Export a trained, compatible density model
with torch.jit.script/trace; check its preprocessing and pixel-sum units first.
"""
from pathlib import Path
import cv2
import numpy as np


def load_density_model(cfg):
    path = cfg.get('density_model')
    if not path or not Path(path).is_file():
        raise ValueError('Density weights missing: configure density_model with an existing trained TorchScript model. Obtain compatible pretrained weights from their author, then fine-tune on your recording-split labeled camera data with train_density.py. No weights are downloaded or supplied.')
    import torch
    device = cfg.get('density_device', 'cpu')
    if device not in ('cpu', 'mps'): raise ValueError('density_device must be cpu or mps')
    if device == 'mps' and not torch.backends.mps.is_available(): raise ValueError('MPS is unavailable; use density_device cpu')
    return torch.jit.load(str(path), map_location=device), device


class DensityEstimator:
    def __init__(self, cfg):
        self.model, self.device = load_density_model(cfg)
        self.model.eval()
        self.input_size = cfg.get('density_input_size')
        if self.input_size and (len(self.input_size)!=2 or min(self.input_size)<1): raise ValueError('density_input_size must be [width,height] with positive integers')

    def process(self, frame, zones, t=None, fps=25):
        import torch
        model_frame = cv2.resize(frame, tuple(map(int,self.input_size))) if self.input_size else frame
        image = np.ascontiguousarray(cv2.cvtColor(model_frame, cv2.COLOR_BGR2RGB).transpose(2, 0, 1))
        with torch.no_grad():
            output = self.model(torch.from_numpy(image).float().unsqueeze(0).to(self.device) / 255)
        if output.ndim != 4 or output.shape[:2] != (1, 1):
            raise ValueError('Density model must output one tensor with shape [1,1,H,W]')
        density = output[0, 0].detach().cpu().numpy()
        if not np.isfinite(density).all() or (density < 0).any(): raise ValueError('Density output must be finite and nonnegative')
        counts = []
        for zone in zones:
            poly = zone.poly.astype(float) * [density.shape[1] / frame.shape[1], density.shape[0] / frame.shape[0]]
            mask = np.zeros(density.shape, np.uint8)
            cv2.fillPoly(mask, [np.rint(poly).astype(np.int32)], 1)
            counts.append(float(density[mask > 0].sum()))
        occupied = cv2.resize((density > 0).astype(np.uint8) * 255, (frame.shape[1], frame.shape[0]), interpolation=cv2.INTER_NEAREST)
        return counts, occupied
