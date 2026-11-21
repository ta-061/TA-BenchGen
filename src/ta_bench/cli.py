"""The two user-facing commands: generate and review."""
import argparse
import ipaddress
import json
import os
import socket
import sys
from pathlib import Path

import yaml

from .common.classes import japanese_descriptions, load_classes
from .common.jsonio import load_json
from .errors import ExecutionError, ValidationError
from .generation.requests import is_pending, load_request_file, normalize_requests
from .generation.session import RUN_ID, run_generation
from .providers.api import APIProvider
from .providers.file import FileProvider
from .providers.profiles import ModelProfile, select_profile
from .runtime.docker import DockerRunner
from .verification.reverify import reverify_cases

# Settings a resumed run inherits from its first invocation. API keys are never stored.
RESUMED_SETTINGS = ('candidate', 'models', 'use', 'model', 'api_url', 'image', 'development',
                    'timeout', 'memory', 'cpus', 'classes', 'benchmark')
PATH_SETTINGS = {'candidate', 'models', 'classes', 'benchmark'}
IMAGE_REQUIRED = '検証用イメージを --image または TA_BENCH_IMAGE で指定してください'


def positive(value):
    value = int(value)
    if value < 1:
        raise argparse.ArgumentTypeError('must be positive')
    return value


def address_arg(value):
    try:
        return str(ipaddress.ip_address(value))
    except ValueError as exc:
        raise argparse.ArgumentTypeError('expected an IP address such as 127.0.0.1 or 0.0.0.0') from exc


def defects_arg(value):
    try:
        pairs = [item.strip().split('=') for item in value.split(',')]
        result = {name: int(count) for name, count in pairs}
        if len(result) != len(pairs) or any(count < 1 for count in result.values()):
            raise ValueError()
        return result
    except (ValueError, TypeError) as exc:
        raise argparse.ArgumentTypeError('expected IVW=1 or IVW=2,UDO=2') from exc


def parser():
    root = argparse.ArgumentParser(prog='ta-bench', description='OP-TEE TA設計不備の生成・挙動検証・人手レビュー')
    commands = root.add_subparsers(dest='command', required=True)

    gen = commands.add_parser('generate', help='候補生成とR1–R3検証')
    group = gen.add_mutually_exclusive_group(required=True)
    group.add_argument('--ta', type=Path)
    group.add_argument('--request', type=Path)
    group.add_argument('--resume')
    gen.add_argument('--defects', type=defects_arg)
    gen.add_argument('--count', type=positive, default=1)
    gen.add_argument('--max-attempts', type=positive, help='要求ごとの総試行上限。既定はcount×3')
    gen.add_argument('--benchmark', type=Path, default=Path('benchmark'))
    gen.add_argument('--candidate', type=Path, help='APIの代わりに手書き候補JSONを使用')
    gen.add_argument('--models', type=Path, default=Path('config/models.yaml'), help='モデル登録ファイル')
    gen.add_argument('--use', default=os.environ.get('TA_BENCH_USE'),
                     help='使用する登録名。既定はモデル登録ファイル先頭の use')
    gen.add_argument('--model', help='選んだ登録のモデルIDを上書き')
    gen.add_argument('--api-url', help='選んだ登録のURLを上書き')

    review = commands.add_parser('review', help='ローカルレビュー、再検証、ブラインド出力')
    review.add_argument('--dir', type=Path, default=Path('benchmark'))
    actions = review.add_mutually_exclusive_group()
    actions.add_argument('--reverify', action='store_true')
    actions.add_argument('--export-blind', type=Path)
    review.add_argument('--approved-only', action='store_true', help='承認済みだけを出力（既定）')
    review.add_argument('--include-unreviewed', action='store_true', help='未承認の機械合格候補も明示的に出力')
    review.add_argument('--include-host', action='store_true')
    review.add_argument('--host', type=address_arg, default='127.0.0.1',
                        help='待ち受けアドレス。既定はこのPCのみ。0.0.0.0 かこのPCのIPアドレスでLAN内に公開（認証なし）')
    review.add_argument('--port', type=positive, default=8765)
    review.add_argument('--required-reviewers', type=positive, default=1)

    for sub in (gen, review):
        sub.add_argument('--classes', type=Path, default=Path('config/classes.yaml'))
        sub.add_argument('--work-dir', type=Path, default=Path('work'))
        sub.add_argument('--image', default=os.environ.get('TA_BENCH_IMAGE'))
        sub.add_argument('--timeout', type=positive, default=300)
        sub.add_argument('--memory', default='4g')
        sub.add_argument('--cpus', type=positive, default=2)
        sub.add_argument('--development', action='store_true', help='開発環境の実行。benchmarkへの保存は禁止')
    return root


def _requests(args, classes):
    if args.resume:
        if args.defects:
            raise ValidationError('--resume cannot override --defects')
        return []
    if args.request:
        if args.defects:
            raise ValidationError('--request cannot be combined with --defects')
        requests = load_request_file(args.request)
    else:
        if not args.defects:
            raise ValidationError('--ta requires --defects')
        requests = [{'ta': str(args.ta), 'defects': args.defects, 'count': args.count}]
    return normalize_requests(requests, classes, args.max_attempts)


def _restore_settings(args):
    """Make a resumed run use the settings of its first invocation."""
    if not RUN_ID.fullmatch(args.resume):
        raise ValidationError('invalid run ID')
    previous = load_json(args.work_dir / 'runs' / args.resume / 'state.json')
    saved = previous.get('settings', {})
    saved.setdefault('models', None)  # runs started before model registration existed
    saved.setdefault('use', None)
    for key, value in saved.items():
        if key in RESUMED_SETTINGS:
            setattr(args, key, Path(value) if key in PATH_SETTINGS and value is not None else value)
    return previous


def _settings(args):
    return {key: (str(value.resolve()) if isinstance(value, Path) else value)
            for key in RESUMED_SETTINGS for value in [getattr(args, key)]}


def _provider_factory(args, settings):
    if args.candidate:
        return lambda: FileProvider(args.candidate)
    saved = settings.get('model_profile')
    profile = (ModelProfile.from_settings(saved) if saved is not None else
               select_profile(args.models, args.use, args.model, args.api_url))
    settings['model_profile'] = profile.to_settings()
    return lambda: APIProvider(profile=profile)


def _generate(args, runner_factory):
    # A resumed run also restores --classes, so the definitions are loaded afterwards.
    previous = _restore_settings(args) if args.resume else None
    classes = load_classes(args.classes)
    requests = _requests(args, classes)
    pending = previous['requests'] if previous else requests
    has_pending = any(is_pending(req, classes) for req in pending)
    if has_pending and not args.image:
        raise ValidationError(IMAGE_REQUIRED)
    settings = _settings(args)
    if previous and 'model_profile' in previous.get('settings', {}):
        settings['model_profile'] = previous['settings']['model_profile']
    # Completed and unsupported runs need neither model configuration nor credentials.
    provider_factory = _provider_factory(args, settings) if has_pending else lambda: None
    summary = run_generation(requests, classes, args.benchmark, args.work_dir,
                             provider_factory, runner_factory,
                             resume=args.resume, settings=settings)
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0 if summary['unmet'] == 0 else 2


def _own_address():
    """This machine's address on its default route. A UDP connect only picks the route; nothing is sent."""
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as probe:
        try:
            probe.connect(('192.0.2.1', 9))
            return probe.getsockname()[0]
        except OSError:
            return None


def _review(args, runner_factory):
    classes = load_classes(args.classes)
    if args.approved_only and args.include_unreviewed:
        raise ValidationError('--approved-only and --include-unreviewed are mutually exclusive')
    benchmark, work = args.dir.resolve(), args.work_dir.resolve()
    if not benchmark.is_dir():
        raise ValidationError(f'benchmark directory not found: {benchmark}')
    if args.export_blind:
        from .review.blind_export import export_blind
        result = export_blind(benchmark, args.export_blind, classes, work,
                              approved_only=not args.include_unreviewed, include_host=args.include_host)
        print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
        return 0
    if args.reverify:
        result = reverify_cases(benchmark, classes, work, runner_factory())
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0 if all(r['status'] == 'machine_pass' for r in result) else 2
    from .review.app import create_app
    listening = ipaddress.ip_address(args.host)
    lan = not listening.is_loopback
    app = create_app(benchmark, classes, work, required_reviewers=args.required_reviewers,
                     descriptions_ja=japanese_descriptions(args.classes), lan=lan)
    shown = (_own_address() or 'このPCのIPアドレス') if listening.is_unspecified else args.host
    shown = f'[{shown}]' if ':' in shown else shown  # an IPv6 address inside a URL
    print(f'レビュー: http://{shown}:{args.port} （終了: Ctrl-C）')
    if lan:
        print('LAN内に公開しています。認証はなく、同じネットワークの誰でも閲覧とレビューの保存ができます。')
    # Shared, it answers in threads: one idle connection would otherwise stall every other reviewer.
    app.run(host=args.host, port=args.port, debug=False, threaded=lan)
    return 0


def main(argv=None):
    args = parser().parse_args(argv)

    def runner_factory():
        if not args.image:
            raise ValidationError(IMAGE_REQUIRED)
        return DockerRunner(args.image, args.work_dir / 'runner', timeout=args.timeout,
                            memory=args.memory, cpus=args.cpus, development=args.development)

    try:
        if args.command == 'generate':
            return _generate(args, runner_factory)
        return _review(args, runner_factory)
    except (ValidationError, ExecutionError, OSError, ValueError, yaml.YAMLError) as exc:
        print(f'ta-bench: {exc}', file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        print('中断しました。generate は表示済みの run_id で --resume できます。', file=sys.stderr)
        return 130
