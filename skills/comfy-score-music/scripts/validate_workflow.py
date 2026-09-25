#!/usr/bin/env python3
"""Validate prepared score workflows on CPU; never queue or render audio."""
import argparse
import asyncio
import hashlib
import json
from pathlib import Path
import sys
import types


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('prompts', type=Path, nargs='+', help='Prepared .api.json files')
    parser.add_argument('--comfy-dir', type=Path, default=Path('/home/mark/repos/comfy'))
    parser.add_argument('--report', type=Path)
    args = parser.parse_args()
    root = args.comfy_dir.resolve()
    sys.path.insert(0, str(root))
    # ComfyUI reads its own CLI during import; force CPU before importing it.
    sys.argv = [sys.argv[0], '--cpu']
    import comfy.options
    comfy.options.enable_args_parsing()
    import nodes
    import execution
    import server
    from aiohttp import web

    async def validate():
        server.PromptServer.instance = types.SimpleNamespace(routes=web.RouteTableDef())
        for name in ('nodes_audio.py', 'nodes_yue2.py', 'nodes_primitive.py'):
            if not await nodes.load_custom_node(str(root / 'comfy_extras' / name), module_parent='comfy_extras'):
                raise RuntimeError(f'Cannot load {name}')
        toolkit = root / 'custom_nodes/ComfyUI-MiniMax-Music-Production-Toolkit'
        if not await nodes.load_custom_node(str(toolkit)):
            raise RuntimeError('Cannot load the Music Production Toolkit')
        reports = []
        for path in args.prompts:
            graph = json.loads(path.read_text())
            valid, error, outputs, node_errors = await execution.validate_prompt('score-validation', graph, None)
            if not valid or node_errors:
                raise ValueError(json.dumps({'path': str(path), 'error': error, 'node_errors': node_errors}))
            cache = {}

            def evaluate(node_id):
                node = graph[node_id]
                if node_id in cache:
                    return cache[node_id]
                kind = node['class_type']
                if kind.startswith('Primitive'):
                    result = (node['inputs']['value'],)
                elif kind == 'YuE2ContinueABC':
                    resolved = resolve({key: value for key, value in node['inputs'].items() if key != 'clip'})
                    result = (resolved['source_abc'], '{}')  # A stand-in for routing checks only.
                elif kind in ('MusicProductionControl', 'MiniMaxMusicModelSettings'):
                    obj = nodes.NODE_CLASS_MAPPINGS[kind]()
                    result = getattr(obj, obj.FUNCTION)(**resolve(node['inputs']))
                else:
                    raise ValueError(f'Refusing to evaluate {kind} during a non-rendering check')
                cache[node_id] = result
                return result

            def resolve(inputs):
                return {key: evaluate(value[0])[value[1]] if isinstance(value, list) else value
                    for key, value in inputs.items()}

            continuation = next((node for node in graph.values() if node['class_type'] == 'YuE2ContinueABC'), None)
            continuation_report = None
            if continuation:
                from build_workflow import continuation_module
                module = continuation_module(toolkit)
                ci = {key: value for key, value in continuation['inputs'].items() if key != 'clip'}
                ci = resolve(ci)
                opening, source, count, end = module.opening_score(ci['source_abc'], ci['keep_unit'], ci['keep_value'])
                continuation_report = {'preserved_bars': count, 'preserved_nominal_seconds': float(end * 60 / source.bpm),
                    'opening_sha256': hashlib.sha256(opening.encode()).hexdigest(), 'generation_executed': False}
            generation = next((node for node in graph.values() if node['class_type'] == 'MusicGeneration'), None)
            if generation is None:
                allowed = {'CheckpointLoaderSimple', 'YuE2ContinueABC', 'PrimitiveStringMultiline', 'PrimitiveInt'}
                if not continuation or any(node['class_type'] not in allowed for node in graph.values()):
                    raise ValueError('Unexpected node in a score-only continuation workflow')
                reports.append({'path': str(path.resolve()), 'valid': True, 'outputs': outputs,
                    'nodes': len(graph), 'score_only': True, 'continuation': continuation_report, 'audio_rendered': False})
                continue
            inputs = resolve(generation['inputs'])
            cls = nodes.NODE_CLASS_MAPPINGS['MusicGeneration']
            if 'score_abc' not in cls.INPUT_TYPES().get('optional', {}):
                raise ValueError('Toolkit lacks the supplied score input; install the music_generation.py change')
            expanded = cls().generate(**inputs)['expand']
            by_type = {node['class_type']: node['inputs'] for node in expanded.values()}
            if 'YuE2GenerateABC' in by_type:
                raise ValueError('Workflow would regenerate the score')
            music = by_type['YuE2GenerateMusic']
            if music['abc'] != inputs['score_abc'] or music['mode'] != 'full':
                raise ValueError('Score or harmony mode changed before music generation')
            receipt = by_type['MusicGenerationReceipt']
            settings = json.loads(receipt['settings_json'])
            if receipt['abc'] != music['abc'] or settings.get('abc_source') != 'supplied_score':
                raise ValueError('Generation receipt does not preserve the authored score')
            forbidden = {'MiniMaxLLMChat', 'YuE2GenerateABC', 'MusicCoverTranscription',
                'MusicOptionalCoverPreview', 'SaveImageSmartPrefix'}
            if any(node['class_type'] in forbidden for node in graph.values()):
                raise ValueError('Unexpected planner, transcription or artwork stage')
            reports.append({'path': str(path.resolve()), 'valid': True, 'outputs': outputs,
                'nodes': len(graph), 'abc_sha256': hashlib.sha256(music['abc'].encode()).hexdigest(),
                'exact_score_passed': True, 'planner_skipped': True, 'receipt_source': settings['abc_source'],
                'mode': music['mode'], 'maximum_seconds': music['max_duration'],
                'audio_rendered': False, 'continuation': continuation_report})
        return reports

    reports = asyncio.run(validate())
    text = json.dumps(reports, indent=2) + '\n'
    if args.report:
        with args.report.open('x') as f:
            f.write(text)
    print(text)


if __name__ == '__main__':
    main()
