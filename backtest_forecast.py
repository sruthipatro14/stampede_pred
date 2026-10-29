"""Backtest stored forecast endpoints against observed estimator density, not ground truth.
False alarms are new warning episodes, per zone-hour of observation. Threshold
confusion is sample-level; lead time uses first observed crossing after a correct
new early warning. Missing horizons are reported with n=0, never extrapolated as truth.
"""
import argparse
import csv
import json
import math
from pathlib import Path
from statistics import mean


def load_series(root):
    series={}
    for path in Path(root).rglob('*.json'):
        meta=json.loads(path.read_text())
        if meta.get('format')!='crowd-monitor-segment-v1':continue
        for sample in meta['samples']:
            for z in sample['zones']:
                if z.get('density') is None:continue
                key=(meta['recording_id'],meta['camera'],z['name'])
                series.setdefault(key,[]).append(dict(z,t=float(sample['video_s'])))
    return {k:sorted({r['t']:r for r in rows}.values(),key=lambda r:r['t']) for k,rows in series.items()}


def backtest(series,tolerance=2,damping=None,smoothing=15):
    results=[]
    for horizon in (30,60,120):
        errors=[];tables={level:{'tp':0,'fp':0,'fn':0,'tn':0,'false_alarm_episodes':0,'lead_times_s':[]} for level in (2,3,4)}
        hours=0
        for rows in series.values():
            if len(rows)<2:continue
            previous={level:False for level in tables}
            for i,row in enumerate(rows):
                target=row['t']+horizon
                # Never match an earlier horizon just because the recording ended.
                candidates=[r for r in rows[i+1:] if abs(r['t']-target)<=tolerance]
                if not candidates:continue
                actual=min(candidates,key=lambda r:abs(r['t']-target))
                if damping is None:prediction=row.get('forecast_'+str(horizon))
                else:
                    recent=[r for r in rows[:i+1] if r['t']>=row['t']-smoothing]
                    dt=row['t']-recent[0]['t'];slope=(row['density']-recent[0]['density'])/dt if dt else 0
                    prediction=max(0,row['density']+slope*damping*(1-math.exp(-horizon/damping)))
                if prediction is None:continue
                hours+=(rows[i+1]['t']-row['t'])/3600
                errors.append(prediction-actual['density'])
                for level,threshold in zip((2,3,4),row['thresholds']):
                    forecast=prediction>=threshold;observed=actual['density']>=threshold
                    table=tables[level];table['tp' if forecast and observed else 'fp' if forecast else 'fn' if observed else 'tn']+=1
                    onset=forecast and not previous[level]
                    if onset and not observed:table['false_alarm_episodes']+=1
                    if onset and observed and row['density']<threshold:
                        crossing=next((r['t'] for r in rows[i+1:] if r['t']<=actual['t'] and r['density']>=threshold),None)
                        if crossing is not None:table['lead_times_s'].append(crossing-row['t'])
                    previous[level]=forecast
        for table in tables.values():
            leads=table.pop('lead_times_s');table['mean_early_warning_lead_s']=mean(leads) if leads else None
            table['correct_early_warning_episodes']=len(leads)
            table['false_alarms_per_zone_hour']=table['false_alarm_episodes']/hours if hours else None
        results.append({'horizon_s':horizon,'n':len(errors),'mae':mean(map(abs,errors)) if errors else None,
           'bias':mean(errors) if errors else None,'threshold_confusion':tables,'zone_hours':hours})
    return results


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--recordings-dir',default='recordings')
    p.add_argument('--tolerance',type=float,default=2);p.add_argument('--damping-values',default='')
    p.add_argument('--smoothing-values',default='15');p.add_argument('--output',default='forecast_backtest.json')
    p.add_argument('--sweep-output',default='forecast_sweep.csv');a=p.parse_args()
    series=load_series(a.recordings_dir)
    if not series:p.error('No monitor sidecar samples found')
    if a.tolerance<0:p.error('tolerance must be nonnegative')
    stored=backtest(series,a.tolerance)
    Path(a.output).write_text(json.dumps({'comparison':'observed estimator density, not independently labeled truth','results':stored},indent=2))
    print(json.dumps(stored,indent=2))
    if a.damping_values:
        damping=[float(x) for x in a.damping_values.split(',')];smoothing=[float(x) for x in a.smoothing_values.split(',')]
        if min(damping+smoothing)<=0:p.error('damping and smoothing values must be positive seconds')
        table=[]
        for d in damping:
            for s in smoothing:
                for row in backtest(series,a.tolerance,d,s):
                    table.append({'damping_s':d,'smoothing_s':s,**{k:row[k] for k in ('horizon_s','n','mae','bias')},
                        **{f'L{level}_{metric}':row['threshold_confusion'][level][metric] for level in (2,3,4) for metric in ('false_alarms_per_zone_hour','mean_early_warning_lead_s')}})
        with Path(a.sweep_output).open('w',newline='') as f:
            writer=csv.DictWriter(f,fieldnames=list(table[0]));writer.writeheader();writer.writerows(table)
        print('Sweep written; config.json was not changed.')


if __name__=='__main__':main()
