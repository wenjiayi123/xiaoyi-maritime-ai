"""Create a local source snapshot for review; never includes model binaries or credentials."""
from __future__ import annotations
import hashlib
import json
from pathlib import Path
import zipfile

ROOT = Path(__file__).resolve().parents[1]
ART = ROOT / '.codex_artifacts/joint-harness-phase3-20261029'
SOURCES = {
    'xiaoyi': (ROOT, [
        'web/index.html', 'web/joint_harness.js',
        'scripts/soak_joint_system.py', 'scripts/soak_full_business.py',
        'scripts/summarize_joint_phase3.py', 'scripts/plot_joint_phase3.py',
        'scripts/package_joint_phase3.py',
        'docs/HARNESS_PHASE3_ACCEPTANCE_20261029.md',
        'docs/HARNESS_PHASE3_DELIVERY_20261029.md',
        'docs/HARNESS_MODELS_EXPLAINED_20261029.md',
    ]),
    'port-dt-multi': (ROOT.parent / '模拟器/port-dt-multi', [
        'app/server.py', 'app/ui/adapters/demo_guide.js',
        'tests/js/rl_pages_contract.cjs', 'tests/js/demo_training_readiness_contract.cjs',
    ]),
    'energy-cockpit': (ROOT.parent / '能碳驾驶舱', [
        'scripts/run_backend.sh', 'frontend/src/components/XiaoyiLinkageHub.tsx',
        'e2e/action_result_status.test.mjs',
    ]),
}


def main():
    files = []
    manifest = {'schema': 'xiaoyi-phase3-source-snapshot.v1', 'files': []}
    for project, (root, names) in SOURCES.items():
        for name in names:
            path = root / name
            body = path.read_bytes()
            target = project + '/' + name
            files.append((target, body))
            manifest['files'].append({'archive_path': target, 'origin': str(path),
                'bytes': len(body), 'sha256': hashlib.sha256(body).hexdigest()})
    readme = ('# 三期源文件审阅快照\n\n'
        '这是现有项目文件的快照，包含相应文件中用户既有的更改；不是脱离原工程的独立安装包。'
        '请先对比版本，不要直接覆盖另一份工程。原有数据、权重和运行环境继续使用原位置。\n\n'
        '本机原始验收证据在舷鸥项目的 .codex_artifacts/joint-harness-phase3-20261029/。'
        '通过范围和跳过项目以验收报告为准；测试进行中的报告不能作为最终通过凭证。\n')
    name = 'HARNESS_PHASE3_SOURCE_20261029.zip'
    temp = ART / (name + '.partial')
    with zipfile.ZipFile(temp, 'w', zipfile.ZIP_DEFLATED) as z:
        z.writestr('README.md', readme)
        z.writestr('manifest.json', json.dumps(manifest, ensure_ascii=False, indent=2))
        for target, body in files:
            z.writestr(target, body)
    with zipfile.ZipFile(temp) as z:
        assert z.testzip() is None
        for entry in manifest['files']:
            assert hashlib.sha256(z.read(entry['archive_path'])).hexdigest() == entry['sha256']
    target = ART / name
    temp.replace(target)
    manifest.update(archive=str(target), archive_bytes=target.stat().st_size,
                    archive_sha256=hashlib.sha256(target.read_bytes()).hexdigest())
    (ART / 'source-package-manifest.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2))
    print(json.dumps({k: v for k, v in manifest.items() if k != 'files'}, ensure_ascii=False))


if __name__ == '__main__':
    main()
