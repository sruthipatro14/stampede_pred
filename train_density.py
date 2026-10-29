"""Fine-tuning SKELETON for compatible user-supplied TorchScript density weights.
Requires labeled points and >=2 independent recording IDs. Not an accuracy claim.
RGB [0,1] inputs; Bx1xHxW nonnegative density outputs whose sum is count.
"""
import argparse
import csv
import json
from pathlib import Path
import random
import cv2
import numpy as np
from training_data import labeled_examples,gaussian_density
from density_estimator import load_density_model


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--manifest',required=True);p.add_argument('--weights',required=True)
    p.add_argument('--device',choices=['cpu','mps'],default='cpu');p.add_argument('--epochs',type=int,default=10)
    p.add_argument('--lr',type=float,default=1e-5);p.add_argument('--sigma',type=float,default=2)
    p.add_argument('--width',type=int,default=256);p.add_argument('--height',type=int,default=192)
    p.add_argument('--output',default='density_training');p.add_argument('--seed',type=int,default=42)
    a=p.parse_args()
    if min(a.epochs,a.width,a.height,a.sigma)<=0:p.error('epochs, dimensions and sigma must be positive')
    if not Path(a.manifest).is_file():p.error('Provide an existing manifest with your labeled recordings')
    if not Path(a.weights).is_file():p.error('Provide existing compatible initial TorchScript weights; no weights are supplied')
    examples=labeled_examples(a.manifest)
    recordings=sorted({e['recording_id'] for e in examples})
    if len(recordings)<2:p.error('Need labeled images from at least two independent recordings; never split adjacent frames across train and validation')
    random.Random(a.seed).shuffle(recordings);n=max(1,int(len(recordings)*.2));valid_ids=set(recordings[:n])
    train=[e for e in examples if e['recording_id'] not in valid_ids];valid=[e for e in examples if e['recording_id'] in valid_ids]
    model,device=load_density_model({'density_model':a.weights,'density_device':a.device})
    import torch
    torch.manual_seed(a.seed)
    optimizer=torch.optim.Adam(model.parameters(),lr=a.lr)
    out=Path(a.output);out.mkdir(parents=True,exist_ok=True)
    (out/'split.json').write_text(json.dumps({'train_recordings':recordings[n:],'validation_recordings':recordings[:n],
        'seed':a.seed,'manifest':str(Path(a.manifest).resolve()),'input_size':[a.width,a.height]},indent=2))
    def forward(example):
        bgr=cv2.imread(str(example['path']))
        if bgr is None:raise ValueError('Cannot read labeled image: '+str(example['path']))
        rgb=cv2.cvtColor(cv2.resize(bgr,(a.width,a.height)),cv2.COLOR_BGR2RGB)
        tensor=torch.from_numpy(np.ascontiguousarray(rgb.transpose(2,0,1))).float().unsqueeze(0).to(device)/255
        output=model(tensor)
        if output.ndim!=4 or tuple(output.shape[:2])!=(1,1):raise ValueError('Model output must be Bx1xHxW density tensor')
        if not torch.isfinite(output).all() or (output<0).any():raise ValueError('Model density must be finite and nonnegative')
        target=gaussian_density(example['points'],(bgr.shape[1],bgr.shape[0]),(output.shape[3],output.shape[2]),a.sigma)
        return output,torch.from_numpy(target).unsqueeze(0).unsqueeze(0).to(device)
    with (out/'metrics.csv').open('w',newline='') as f:
        writer=csv.writer(f);writer.writerow(['epoch','train_loss','validation_MAE','validation_RMSE'])
        for epoch in range(a.epochs):
            model.train();losses=[];random.Random(a.seed+epoch).shuffle(train)
            for e in train:
                optimizer.zero_grad();prediction,target=forward(e)
                loss=torch.nn.functional.mse_loss(prediction,target)+.001*(prediction.sum()-target.sum()).square()
                loss.backward();optimizer.step();losses.append(loss.item())
            model.eval();errors=[]
            with torch.no_grad():
                for e in valid:
                    prediction,_=forward(e);errors.append(float(prediction.sum().cpu())-len(e['points']))
            mae=float(np.mean(np.abs(errors)));rmse=float(np.sqrt(np.mean(np.square(errors))))
            writer.writerow([epoch+1,float(np.mean(losses)),mae,rmse]);f.flush()
            torch.jit.save(model,str(out/f'epoch_{epoch+1:03d}.pt'))
            torch.save({'optimizer':optimizer.state_dict(),'epoch':epoch+1},out/'optimizer.pt')
            print(f'epoch {epoch+1}: validation MAE={mae:.4f} RMSE={rmse:.4f}',flush=True)
    (out/'inference_config.json').write_text(json.dumps({'estimator':'density','density_model':str((out/f'epoch_{a.epochs:03d}.pt').resolve()),'density_device':a.device,'density_input_size':[a.width,a.height]},indent=2))
    print('Skeleton run complete. Validate preprocessing, architecture, calibration and independent-camera performance before use.')


if __name__=='__main__':main()
