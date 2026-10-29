"""Estimator contract: process(BGR uint8 frame, zones, t=None, fps=25) -> (counts, occupancy).
counts: float count per zone in input order, or None during warm-up.
occupancy: full-resolution uint8 mask for optical flow. No thresholds live in estimators.
"""
from typing import Protocol


class Estimator(Protocol):
    def process(self, frame, zones, t=None, fps=25): ...


def create_estimator(cfg):
    from monitor import FgEstimator, YoloEstimator
    name = cfg['estimator']
    if name == 'fg': return FgEstimator(cfg)
    if name == 'yolo': return YoloEstimator(cfg)
    if name == 'density':
        from density_estimator import DensityEstimator
        return DensityEstimator(cfg)
    raise ValueError('Unknown estimator: ' + str(name))
