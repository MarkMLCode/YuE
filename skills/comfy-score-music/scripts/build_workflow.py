#!/usr/bin/env python3
"""Prepare direct-score or YuE2 opening-continuation music workflows."""
import argparse
import copy
import hashlib
import importlib.util
import json
from pathlib import Path
import re
import sys
import types


def module_from_file(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def primitive(node_id, value, title):
    if isinstance(value, int):
        kind, dtype, widgets = 'PrimitiveInt', 'INT', [value, 'fixed']
    else:
        kind, dtype, widgets = 'PrimitiveStringMultiline', 'STRING', [value]
    return {'id': int(node_id), 'type': kind, 'title': title,
        'pos': [0, 0], 'size': [420, 240 if isinstance(value, str) and '\n' in value else 100],
        'flags': {}, 'order': 0, 'mode': 0,
        'inputs': [{'name': 'value', 'type': dtype, 'widget': {'name': 'value'}, 'link': None}],
        'outputs': [{'name': dtype, 'type': dtype, 'links': []}],
        'properties': {'Node name for S&R': kind},
        'widgets_values': widgets, 'widgets_values_named': {'value': value}}


def continuation_module(toolkit):
    package = types.ModuleType('score_continuation_toolkit')
    package.__path__ = [str(toolkit)]
    sys.modules[package.__name__] = package
    return module_from_file(package.__name__ + '.score_continuation', toolkit / 'score_continuation.py')


def continuation_node(module, values):
    schema = module.YuE2ContinueABC.INPUT_TYPES()['required']
    inputs, named = [], {}
    for name, spec in schema.items():
        kind = spec[0]
        entry = {'name': name, 'type': 'COMBO' if isinstance(kind, list) else kind, 'link': None}
        if name != 'clip':
            entry['widget'] = {'name': name}
            named[name] = values.get(name, kind[0] if isinstance(kind, list) else spec[1].get('default'))
        inputs.append(entry)
    return {'id': 208, 'type': 'YuE2ContinueABC', 'title': 'CONTINUE · YuE2 composes after the frozen opening',
            'pos': [0, 0], 'size': [520, 1000], 'flags': {}, 'order': 0, 'mode': 0,
            'inputs': inputs, 'outputs': [
                {'name': 'abc', 'type': 'STRING', 'links': []},
                {'name': 'continuation_receipt', 'type': 'STRING', 'links': []}],
            'properties': {'Node name for S&R': 'YuE2ContinueABC'},
            'widgets_values_named': named, 'widgets_values': list(named.values())}


def build(comfy, request_path, seed, output_name, keep_unit=None, keep_value=None, score_only=False):
    toolkit = comfy / 'custom_nodes/ComfyUI-MiniMax-Music-Production-Toolkit'
    converter = module_from_file('score_workflow_converter', toolkit / 'scripts/comfyui_smoke_test.py')
    checker = module_from_file('score_abc_checker', toolkit / 'third_party/yue2_abc.py')
    source = comfy / 'user/default/workflows/YuE2_Gemma_Music_Production.json'
    workflow = json.loads(source.read_text())
    api = converter.to_api_format(workflow)
    templates = {str(n['id']): copy.deepcopy(n) for n in workflow['nodes']}
    request = json.loads(request_path.read_text())
    for key in ('abc', 'style', 'lyrics', 'title'):
        if not isinstance(request[key], str) or not request[key].strip():
            raise ValueError(f'{key} must be nonempty text')
    parsed = checker.parse_abc(request['abc'])
    seconds = float(parsed.voices['Ins'].time * 60 / parsed.bpm)
    maximum = float(request.get('max_duration', seconds + 20))
    if keep_unit is None and maximum < seconds:
        raise ValueError(f'Score lasts {seconds:.2f}s, longer than the {maximum:.2f}s ceiling')
    if maximum > 900:
        raise ValueError('YuE2 supports at most a 900-second ceiling')
    source_kind = 'yue2_score_continuation' if keep_unit is not None else 'authored_score'
    provenance_data = {'song_model': 'yue2', 'prompt_origin': source_kind,
        'source_path': str(request_path.resolve()), 'score_bpm': parsed.bpm}
    if keep_unit is None:
        provenance_data.update(abc_sha256=hashlib.sha256(request['abc'].encode()).hexdigest(),
                               score_nominal_seconds=seconds)
    else:
        provenance_data.update(source_abc_sha256=hashlib.sha256(request['abc'].encode()).hexdigest(),
                               source_score_nominal_seconds=seconds, keep_unit=keep_unit, keep_value=keep_value)
    provenance = json.dumps(provenance_data)
    constants = {
        '201': (request['style'], 'ARRANGEMENT · Instrument roles and sound'),
        '202': (request['lyrics'], 'SECTIONS · Instrumental tags or sung lyrics'),
        '203': (request['title'], 'TITLE'),
        '204': (output_name, 'OUTPUT NAME · Use a new name for a new score'),
        '205': (request['abc'], 'SCORE · Paste native ABC here'),
        '206': (seed, 'SEED · Fixed for reproducibility'),
    }
    for nid, (value, title) in constants.items():
        templates[nid] = primitive(nid, value, title)
        api[nid] = {'class_type': templates[nid]['type'], 'inputs': {'value': value}}
    source_outputs = {0: ['201', 0], 1: ['202', 0], 2: ['203', 0], 3: '',
        4: ['204', 0], 5: ['206', 0], 6: 1, 7: 1, 8: str(request_path.resolve()),
        9: source_kind, 10: provenance}
    keep = {'35', '37', '45', '46', '49', '50', '52', '54', '55', '63', '91', '93', '94',
        '95', '99', '108', '109', '110', '111', '112', '116', '118', '119', '120', '123', *constants}
    api = {nid: node for nid, node in api.items() if nid in keep}
    for nid, node in api.items():
        for key, value in list(node['inputs'].items()):
            if isinstance(value, list) and value[0] == '53':
                node['inputs'][key] = copy.deepcopy(source_outputs[value[1]])
            elif isinstance(value, list) and value[0] not in keep:
                if nid == '99' and key == 'artwork_path':
                    node['inputs'][key] = ''
                else:
                    del node['inputs'][key]
        if 'filename_mode' in node['inputs']:
            node['inputs']['filename_mode'] = 'prefix as provided'
    api['37']['inputs']['score_abc'] = ['205', 0]
    templates['37']['inputs'].append({'name': 'score_abc', 'type': 'STRING',
        'shape': 7, 'widget': {'name': 'score_abc'}, 'link': None})
    templates['37']['widgets_values_named']['score_abc'] = ''
    api['118']['inputs'].update(model='YuE2', cover_artwork_enabled=False)
    api['55']['inputs'].update(yue2_mode='full', yue2_max_duration=maximum)
    api['54']['inputs']['base_output'] = 'audio/score-music'
    api['63']['inputs'].update(artist='', album='', album_artist='', composer='',
        genre='Instrumental soundtrack' if not parsed.voices['Vocal'].notes else 'Soundtrack',
        comment='YuE2 from an authored ABC score')
    api['99']['inputs']['workflow_name'] = 'YuE2 authored score / Music Production Toolkit'
    api['99']['inputs']['llm_status'] = 'Not used: supplied score and arrangement'
    if keep_unit is not None:
        continuation = continuation_module(toolkit)
        opening, _, count, end = continuation.opening_score(request['abc'], keep_unit, keep_value)
        preserved_seconds = float(end * 60 / parsed.bpm)
        sampling = request.get('continuation_sampling', {})
        unknown = set(sampling) - {'max_abc_tokens', 'temperature', 'top_p', 'top_k', 'repetition_penalty', 'penalty_window', 'max_attempts'}
        if unknown:
            raise ValueError(f'Unknown continuation sampling fields: {sorted(unknown)}')
        values = {'source_abc': '', 'style': '', 'lyrics': '', 'seed': seed,
                  'keep_unit': keep_unit, 'keep_value': keep_value,
                  'filename_prefix': 'scores/continuations/' + output_name,
                  **sampling}
        templates['208'] = continuation_node(continuation, values)
        settings = dict(templates['208']['widgets_values_named'])
        settings.update(clip=['207', 1], source_abc=['205', 0], style=['201', 0],
                        lyrics=['202', 0], seed=['206', 0])
        api['208'] = {'class_type': 'YuE2ContinueABC', 'inputs': settings}
        checkpoint = api['37']['inputs']['yue2_checkpoint']
        templates['207'] = {'id': 207, 'type': 'CheckpointLoaderSimple', 'pos': [0, 0],
            'size': [520, 120], 'flags': {}, 'order': 0, 'mode': 0,
            'inputs': [{'name': 'ckpt_name', 'type': 'COMBO', 'widget': {'name': 'ckpt_name'}, 'link': None}],
            'outputs': [{'name': kind, 'type': kind, 'links': []} for kind in ('MODEL', 'CLIP', 'VAE')],
            'properties': {'Node name for S&R': 'CheckpointLoaderSimple'},
            'widgets_values_named': {'ckpt_name': checkpoint}, 'widgets_values': [checkpoint]}
        api['207'] = {'class_type': 'CheckpointLoaderSimple', 'inputs': {'ckpt_name': checkpoint}}
        api['37']['inputs']['score_abc'] = ['208', 0]
        templates['205']['title'] = 'SOURCE SCORE · Opening is preserved; YuE2 replaces the rest'
        templates['202']['title'] = 'SECTIONS · Instrumental tags only'
        api['99']['inputs']['workflow_name'] = 'YuE2 score continuation / Music Production Toolkit'
        api['99']['inputs']['llm_status'] = 'YuE2 ABC continuation; no external LLM'
        api['63']['inputs']['comment'] = 'YuE2 score continuation from a preserved opening'
        if score_only:
            api = {nid: node for nid, node in api.items() if nid in {'201', '202', '205', '206', '207', '208'}}
    # Forced-input literals need visible primitive nodes when opened in the UI.
    literals = {}
    next_id = 220
    for nid, node in list(api.items()):
        entries = {item['name']: item for item in templates[nid]['inputs']}
        for key, value in list(node['inputs'].items()):
            if isinstance(value, list) or 'widget' in entries[key]:
                continue
            token = (type(value).__name__, str(value))
            if token not in literals:
                pid = str(next_id); next_id += 1
                literals[token] = pid
                templates[pid] = primitive(pid, value, key.replace('_', ' ').upper())
                templates[pid]['flags'] = {'collapsed': True}
                api[pid] = {'class_type': templates[pid]['type'], 'inputs': {'value': value}}
            node['inputs'][key] = [literals[token], 0]
    ui_nodes = {}
    for order, (nid, node) in enumerate(api.items()):
        template = templates[nid]
        template['order'] = order
        template['mode'] = 0
        for entry in template['inputs']:
            entry['link'] = None
        for output in template['outputs']:
            output['links'] = []
        named = template.get('widgets_values_named', {})
        for key, value in node['inputs'].items():
            if key in named and not isinstance(value, list):
                named[key] = value
        template['widgets_values_named'] = named
        template['widgets_values'] = list(named.values())
        if template['type'] == 'YuE2ContinueABC':
            index = list(named).index('seed') + 1
            template['widgets_values'].insert(index, 'fixed')
        if template['type'] == 'PrimitiveInt':
            template['widgets_values'].append('fixed')
        ui_nodes[nid] = template
    links = []
    for nid, node in api.items():
        for name, value in node['inputs'].items():
            if not isinstance(value, list):
                continue
            origin, output_slot = value
            target_slot = next(i for i, item in enumerate(ui_nodes[nid]['inputs']) if item['name'] == name)
            lid = len(links) + 1
            dtype = ui_nodes[origin]['outputs'][output_slot]['type']
            links.append([lid, int(origin), output_slot, int(nid), target_slot, dtype])
            ui_nodes[nid]['inputs'][target_slot]['link'] = lid
            ui_nodes[origin]['outputs'][output_slot]['links'].append(lid)
    # Separate editable inputs, generation, finishing, and exports on the canvas.
    columns = [['205', '201', '202', '203', '204', '206'], ['207', '208', '118', '55', '37'], ['119', '123', '109', '110', '112'],
        ['91', '111', '120'], ['54', '63', '35', '46', '52', '116', '108', '99'],
        ['95', '49', '45', '93', '94', '50'], list(literals.values())]
    for column, ids in enumerate(columns):
        y = 80
        for nid in ids:
            if nid not in ui_nodes:
                continue
            node = ui_nodes[nid]
            height = 560 if nid in ('201', '205') else min(max(node['size'][1], 150), 900)
            node['pos'] = [column * 580, y]
            node['size'] = [520, height]
            y += height + 90
    result = {'last_node_id': max(int(x) for x in ui_nodes), 'last_link_id': len(links),
        'nodes': list(ui_nodes.values()), 'links': links, 'groups': [], 'config': {},
        'extra': {'ds': {'scale': 0.65, 'offset': [60, 60]},
            'score_source': {'request': str(request_path.resolve()), 'nominal_seconds': seconds}}, 'version': 0.4}
    if keep_unit is not None:
        result['extra']['score_source'].update(mode='yue2_score_continuation', preserved_bars=count,
            preserved_nominal_seconds=preserved_seconds, score_only=score_only)
    # Compare graph behavior, allowing disconnected optional widgets to restore defaults.
    roundtrip = converter.to_api_format(result)
    for nid, node in api.items():
        for key, value in node['inputs'].items():
            if roundtrip[nid]['inputs'].get(key) != value:
                raise ValueError(f'Workflow conversion changed {nid}.{key}')
    return result, roundtrip


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('request', type=Path, help='JSON with title, style, lyrics, abc and optional max_duration')
    parser.add_argument('--comfy-dir', type=Path, default=Path('/home/mark/repos/comfy'))
    parser.add_argument('--seed', type=int, default=42001)
    parser.add_argument('--name', help='Output filename stem')
    parser.add_argument('--output', type=Path, required=True, help='New UI workflow JSON; also writes .api.json')
    keep = parser.add_mutually_exclusive_group()
    keep.add_argument('--keep-bars', type=int, help='Let YuE2 continue after this many frozen opening bars')
    keep.add_argument('--keep-seconds', type=float, help='Continue after the nearest complete bar to this score time')
    parser.add_argument('--score-only', action='store_true', help='Save continued ABC scores without rendering audio; requires --keep-bars or --keep-seconds')
    args = parser.parse_args()
    keep_unit = 'bars' if args.keep_bars is not None else 'seconds' if args.keep_seconds is not None else None
    keep_value = args.keep_bars if args.keep_bars is not None else args.keep_seconds
    if args.score_only and keep_unit is None:
        parser.error('--score-only requires --keep-bars or --keep-seconds')
    if not 0 <= args.seed < 2**63:
        parser.error('seed must be between 0 and 2**63-1')
    name = args.name or re.sub(r'[^a-z0-9]+', '-', json.loads(args.request.read_text())['title'].lower()).strip('-')
    if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_-]*', name):
        parser.error('name must be a filename stem using letters, numbers, hyphens or underscores')
    api_path = args.output.with_suffix('.api.json')
    if args.output.exists() or api_path.exists():
        parser.error('Choose new workflow filenames; existing files are not overwritten')
    workflow, api = build(args.comfy_dir.resolve(), args.request.resolve(), args.seed, name, keep_unit, keep_value, args.score_only)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    for path, value in ((args.output, workflow), (api_path, api)):
        with path.open('x') as f:
            json.dump(value, f, indent=2, ensure_ascii=False); f.write('\n')
    print(json.dumps({'workflow': str(args.output), 'api': str(api_path), 'nodes': len(api)}))


if __name__ == '__main__':
    main()
