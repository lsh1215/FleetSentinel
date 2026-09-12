#!/usr/bin/env python3
"""Fixed-rate, single-host acceptance run; not a Kafka capacity benchmark."""
import argparse
from io import BytesIO
import json
from pathlib import Path
import sys
import threading
import time
import urllib.parse
import urllib.request
import uuid
from confluent_kafka import Producer
from fastavro import schemaless_writer

sys.path.insert(0, str(Path('exploration').resolve()))
sys.path.insert(0, str(Path('exploration/scripts').resolve()))
from fleetsentinel_ingest.nuscenes_source import extract_native_signals
from ship_to_gateway import _signal_row
from nuscenes.nuscenes import NuScenes
from nuscenes.can_bus.can_bus_api import NuScenesCanBus


def get(url):
    return json.load(urllib.request.urlopen(url, timeout=10))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--out', type=Path, required=True)
    ap.add_argument('--seconds', type=int, default=60)
    ap.add_argument('--rate', type=int, default=1300)
    args = ap.parse_args()
    assert args.seconds > 0 and args.rate >= 2
    args.out.mkdir(parents=True, exist_ok=False)
    run = 'steady-' + uuid.uuid4().hex[:8]
    jobs = [j for j in get('http://localhost:8081/jobs/overview')['jobs'] if j['state'] == 'RUNNING']
    assert len(jobs) == 1 and jobs[0]['state'] == 'RUNNING', jobs
    job = jobs[0]['jid']
    cp = get(f'http://localhost:8081/jobs/{job}/checkpoints')
    assert cp['counts']['completed'] > 0, 'no completed checkpoint'
    baseline_restarts=get(f'http://localhost:8081/jobs/{job}/metrics?get=numRestarts')
    assert baseline_restarts, 'restart metric unavailable before run'
    baseline_restart_count=int(baseline_restarts[0]['value'])
    schema = json.loads(Path('schemas/vehicle-signal.avsc').read_text())
    nusc = NuScenes(version='v1.0-mini', dataroot='data/nuscenes', verbose=False)
    can = NuScenesCanBus(dataroot='data/nuscenes')
    templates = [_signal_row(s) for s in extract_native_signals(nusc, nusc.scene[0], run, can)]
    hypothesis = dict(run=run, sealedAtMs=time.time_ns()//1_000_000, rate=args.rate,
                      warmupSeconds=30, measurementSeconds=args.seconds,
                      predictions=dict(uniqueStored='all sent records after 30s drain',
                                       immediateAlertLatencyP95Ms=1000),
                      invalidIf='schedule lag > 100ms, producer error, metric fetch error, or job restart',
                      scope='local single-host Kafka→Flink→ClickHouse and alert SSE; excludes gateway throughput',
                      source='nuScenes native signals, timestamps rebased; fleet_status is synthetic',
                      expectedBottleneck='synchronous ClickHouse batch flush may propagate backpressure', job=job,
                      baselineRestarts=baseline_restart_count)
    (args.out/'hypothesis.json').write_text(json.dumps(hypothesis, indent=2))
    producer = Producer({'bootstrap.servers':'localhost:29092,localhost:29093,localhost:29094',
                         'acks':'all','enable.idempotence':True,'broker.address.family':'v4', 'linger.ms':5})
    points, alerts, errors = [], [], []
    sent = 0
    done = threading.Event()
    def watch():
        while not done.is_set():
            try:
                query = f"SELECT count() AS n FROM fleet.signals FINAL WHERE boot_id = '{run}' FORMAT JSON"
                req=urllib.request.Request('http://localhost:8124/?user=fleet&password=fleet', data=query.encode())
                stored = json.load(urllib.request.urlopen(req, timeout=10))['data'][0]['n']
                checks = get(f'http://localhost:8081/jobs/{job}/checkpoints')
                latest = checks.get('latest',{}).get('completed',{}) or {}
                points.append(dict(atMs=time.time_ns()//1_000_000, sent=sent, stored=int(stored),
                                   checkpoints=checks['counts']['completed'],
                                   checkpointMs=latest.get('end_to_end_duration')))
            except Exception as error: errors.append(str(error))
            done.wait(2)
    def listen():
        try:
            with urllib.request.urlopen('http://localhost:8080/api/alerts', timeout=150) as response:
                for line in response:
                    if line.startswith(b'data:'):
                        event=json.loads(line[5:])
                        if event['vehicleId'] == run:
                            alerts.append(dict(receivedAtMs=time.time_ns()//1_000_000, **event))
        except Exception as error:
            if not done.is_set(): errors.append(str(error))
    threading.Thread(target=watch,daemon=True).start()
    threading.Thread(target=listen,daemon=True).start()
    start=time.monotonic(); epoch=time.time_ns()//1_000_000
    max_lag=0.0
    total=(30+args.seconds)*args.rate
    def delivery(error, message):
        if error: errors.append(str(error))
    for index in range(total):
        due=start+index/args.rate
        time.sleep(max(0,due-time.monotonic()))
        max_lag=max(max_lag,(time.monotonic()-due)*1000)
        ts=epoch+index*1000//args.rate
        rec=dict(templates[index % len(templates)])
        rec['sensor_time']=ts*1000; rec['log_time']=ts*1000
        if index % (args.rate//2) == 0:
            rec=dict(scene_id='synthetic-monitor-under-load',channel='fleet_status',
                     sensor_time=ts*1000,log_time=ts*1000,
                     values_num=dict(speed_mps=3.0,mission_active=1.0,planned_stop=0.0,
                                     sensor_healthy=float((index//args.rate//5)%2)),
                     values_vec={},values_str=dict(mission_id='load-test'))
        buf=BytesIO(); schemaless_writer(buf,schema,rec)
        producer.produce('telemetry.records',key=run,value=buf.getvalue(),on_delivery=delivery,
                         headers=[('vehicle_id',run),('boot_id',run),('seq',str(index)),('kind','RECORD_KIND_SIGNAL')])
        sent+=1
        producer.poll(0)
    if producer.flush(10): errors.append('producer did not drain')
    deadline=time.monotonic()+30
    while time.monotonic()<deadline and (not points or points[-1]['stored'] != total): time.sleep(.2)
    done.set()
    final_jobs=get('http://localhost:8081/jobs/overview')['jobs']
    job_info=get(f'http://localhost:8081/jobs/{job}')
    restarts=get(f'http://localhost:8081/jobs/{job}/metrics?get=numRestarts')
    observed=[e['receivedAtMs']-e['eventTimeMs'] for e in alerts
              if e['eventTimeMs']>=epoch+30_000 and e['type'] in ('SENSOR_FAULT','SENSOR_RECOVERED')]
    observed.sort()
    p95=observed[min(len(observed)-1,int(len(observed)*.95))] if observed else None
    restart_count=int(restarts[0]['value'])-baseline_restart_count if restarts else -1
    valid=not errors and max_lag<=100 and restart_count==0 and job_info['state']=='RUNNING'
    expected_alerts = len(range(30, 30 + args.seconds, 5))
    passed=(valid and points[-1]['stored']==total and len(observed)==expected_alerts
            and len({e['eventId'] for e in alerts})==len(alerts)
            and p95 is not None and p95<=1000)
    result=dict(**hypothesis,startedAtMs=epoch,finishedAtMs=time.time_ns()//1_000_000,
                sent=sent,stored=points[-1]['stored'],maxScheduleLagMs=max_lag,
                immediateAlertP95Ms=p95,measuredAlerts=len(observed),expectedAlerts=expected_alerts,restarts=restart_count,
                errors=errors,valid=valid,passed=passed,points=points,alerts=alerts,
                finalJobs=final_jobs)
    (args.out/'result.json').write_text(json.dumps(result,ensure_ascii=False,indent=2))
    print(json.dumps({k:result[k] for k in ('run','valid','passed','sent','stored','maxScheduleLagMs','immediateAlertP95Ms','errors')}))
    if not passed: raise SystemExit(1)

if __name__=='__main__': main()
