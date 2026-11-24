"""Evaluate the published affine fits against TPS with identical observations."""
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
import argparse
import hashlib
import json
import subprocess
import sys


ROOT = Path(__file__).resolve().parent
OUTPUT = ROOT/'output'
WORK = ROOT/'work/atlas-tps-rollout'
SOLVER = ROOT/'compare_atlas004_tps.py'


def read(path):
    return json.loads(path.read_text())


def write(path, data):
    temporary = path.with_suffix('.tmp')
    temporary.write_text(json.dumps(data, indent=2, allow_nan=False)+'\n')
    temporary.replace(path)


def prepare(entry, frames):
    sid = entry['id']
    folder = WORK/sid
    folder.mkdir(parents=True, exist_ok=True)
    source = OUTPUT/entry['directory']
    config_path = ROOT/entry.get('frame_config',f'data/{sid}-scan.json')
    affine_path = ROOT/entry['affine_reference'] if 'affine_reference' in entry else source/'fit-report.json'
    if sid == 'atlas7':
        points = read(source/'control-points.json')
        old = read(source/'historical-projection-comparison.json')['models']['detailed_angles']
        table = read(ROOT/'data/atlas7-historical-projection.json')
        table_path = folder/'historical-table.json'
        write(table_path, dict(latitudes=table['summary_table']['latitudes'],
                               radius_fathoms=table['summary_table']['radius_fathoms'],
                               angle_arcseconds_per_longitude_degree=table['detailed_tables']['angle_arcseconds_per_longitude_degree'],
                               reference_radius_fathoms=7331657.))
        checks = [dict(p, error_arcseconds=e) for p,e in zip(points['independent_edge_checks'],old['edge_arcsecond_errors'],strict=True)]
        fit = dict(points, **{key:old[key] for key in ['affine_coefficients','affine_plane_centre_fathoms']},
                   table=str(table_path.relative_to(ROOT)), independent_edge_checks=checks)
        affine_path = folder/'affine-reference.json'
        write(affine_path,fit)
    else:
        fit = read(affine_path)
    if not config_path.exists():
        config_path = folder/'frame.json'
        write(config_path,dict(frame_corners=frames[sid]['frame_corners_printed_pixels'],
                               frame_pixel_offset=0 if sid=='atlas7' else .5))
    controls = fit.get('control_observations')
    if controls is None:
        controls = [dict(p, kind='crossing') for p in fit['points']]
    checks = [dict(p,kind=p.get('kind','margin_tick'),side=p.get('side',p.get('edge')))
              for p in fit['independent_edge_checks']]
    crossings = [p for p in controls if p['kind']=='crossing']
    def repeats_crossing(p):
        axis = p.get('known_axis')
        return axis is not None and any(abs(q[axis]-p['known_value']) < 1e-10 and
            (p['pixel']-q['pixel'])**2+(p['line']-q['line'])**2 <= 4 for q in crossings)
    repeated_controls = [p for p in controls if repeats_crossing(p)]
    repeated_checks = [p for p in checks if repeats_crossing(p)]
    controls = [p for p in controls if not repeats_crossing(p)]
    checks = [p for p in checks if not repeats_crossing(p)]
    dataset = dict(id=sid, controls=controls, checks=checks, source=fit['source'],
                   source_sha256=fit['source_sha256'],table=fit['table'],
                   affine_reference=str(affine_path.relative_to(ROOT)),
                   frame_config=str(config_path.relative_to(ROOT)),paired_edge_audit=True)
    if repeated_controls or repeated_checks:
        dataset['repeated_crossing_observations'] = dict(controls=repeated_controls,checks=repeated_checks)
    inputs = [SOLVER, ROOT/'georeference_atlas001.py', affine_path, config_path, ROOT/fit['table']]
    signature = hashlib.sha256(json.dumps(dataset,sort_keys=True).encode())
    for path in inputs:
        signature.update(path.read_bytes())
    dataset['input_signature'] = signature.hexdigest()
    dataset_path = folder/'dataset.json'
    write(dataset_path, dataset)
    return dataset_path, dataset


def run(entry, frames):
    sid = entry['id']
    dataset_path, dataset = prepare(entry, frames)
    result_path = dataset_path.parent/'tps.json'
    if result_path.exists() and read(result_path).get('input_signature')==dataset['input_signature']:
        return sid
    candidate = result_path.with_suffix('.candidate')
    log = result_path.with_suffix('.log')
    with log.open('w') as handle:
        if dataset.get('repeated_crossing_observations',{}).get('controls'):
            subprocess.run([sys.executable,str(ROOT/'compare_atlas_polynomial.py'),'--dataset',str(dataset_path),
                            '--output',str(dataset_path.parent/'paired-affine.json')],cwd=ROOT,
                           stdout=handle,stderr=subprocess.STDOUT,check=True)
        subprocess.run([sys.executable,str(SOLVER),'--sheet',sid,'--dataset',str(dataset_path),
                        '--output',str(candidate)],cwd=ROOT,stdout=handle,stderr=subprocess.STDOUT,check=True)
    result = read(candidate)
    result['input_signature'] = dataset['input_signature']
    write(result_path,result)
    candidate.unlink()
    return sid


if __name__=='__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--workers',type=int,default=8)
    parser.add_argument("--sheet", help="Build one baseline from data/<id>-scan.json and output/<id>/fit-report.json")
    args = parser.parse_args()
    if args.sheet:
        run(dict(id=args.sheet, directory=args.sheet), {})
        sys.exit(0)
    registry = read(OUTPUT/'atlas-georeferencing/sheets.json')
    frames = {r['id']:r for r in read(OUTPUT/'atlas-continuity-audit/continuity.json')['sheets']}
    WORK.mkdir(exist_ok=True)
    write(WORK/'registry.json',registry)
    failures = {}
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        pending = {pool.submit(run, entry, frames): entry['id'] for entry in registry}
        for n, future in enumerate(as_completed(pending),1):
            sid = pending[future]
            try:
                future.result()
            except Exception as exc:
                failures[sid] = str(exc)
                print(sid, repr(exc),flush=True)
            if n%10==0 or n==len(pending):
                print(f'{n}/{len(pending)} completed including {len(failures)} failures',flush=True)
    write(WORK/'failures.json', failures)
    sys.exit(bool(failures))
