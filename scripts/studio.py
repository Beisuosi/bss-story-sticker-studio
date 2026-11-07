"""Local storyboard compiler. Image generation is performed by the host agent."""
import argparse
import hashlib
import html
import json
import shutil
import zipfile
from pathlib import Path

from PIL import Image, ImageDraw, ImageOps


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf-8')


def inside(root, relative):
    path = (root / relative).resolve()
    if path == root or root not in path.parents:
        raise ValueError(f'Path must be inside project: {relative}')
    return path


def load(root):
    plan = json.loads((root / 'plan.json').read_text(encoding='utf-8'))
    entries = plan['stickers']
    if not entries or len(entries) > 100:
        raise ValueError('Expected 1..100 stickers')
    ids = [e['id'] for e in entries]
    if len(ids) != len(set(ids)) or any(not str(i).isascii() or not str(i).isalnum() for i in ids):
        raise ValueError('Unique ASCII alphanumeric sticker IDs required')
    for e in entries:
        inside(root, e['source'])
        cols, rows = e['grid']
        if not isinstance(cols, int) or not isinstance(rows, int) or min(cols, rows) < 1 or cols*rows > 120:
            raise ValueError('Invalid grid')
        order = e.get('order', list(range(cols*rows)))
        if not order or any(not isinstance(i, int) or i < 0 or i >= cols*rows for i in order):
            raise ValueError('Invalid frame order')
        durations = e.get('durations_ms', [180]*len(order))
        if len(durations) != len(order) or any(not isinstance(d, int) or not 20 <= d <= 10000 for d in durations):
            raise ValueError('One 20..10000 ms duration per frame required')
        box = e.get('caption_box')
        if box is not None and (len(box) != 4 or not 0 <= box[0] < box[2] <= 1 or not 0 <= box[1] < box[3] <= 1):
            raise ValueError('caption_box uses normalized x0,y0,x1,y1 coordinates')
    for item in plan.get('attachments', []):
        inside(root, item['source'])
        if item['role'] not in ('cover', 'icon', 'banner'):
            raise ValueError('Unknown attachment role')
    return plan


def init(root, photo):
    if (root / 'plan.json').exists():
        raise ValueError('Project already initialized; edit plan.json instead')
    with Image.open(photo) as im:
        im.verify()
    root.mkdir(parents=True, exist_ok=True)
    (root / 'private').mkdir(exist_ok=True)
    shutil.copy2(photo, root / 'private' / ('reference' + photo.suffix.lower()))
    (root / 'sources').mkdir(exist_ok=True)
    captions = ['收到啦', '让我想想', '咖啡续命', '先歇一会', '马上处理', '怎么又来', '周末到啦', '准备开溜', '轻松闪避', '清理任务', '下班啦', '明天再说']
    entries = []
    for n, caption in enumerate(captions, 1):
        entries.append(dict(id=f'{n:02}', caption=caption, meaning='', source=f'sources/{n:02}.png', grid=[3, 2],
                            trigger='', scene='', beats=[], order=list(range(6)),
                            durations_ms=[300, 180, 180, 240, 240, 500], caption_box=None,
                            visual_status='pending', known_limits=[]))
    write(root / 'plan.json', dict(version=1, title='我的职场日常', artist='', copyright='',
                                 identity_anchors=[], interface_language='zh-CN', stickers=entries, attachments=[]))
    print('Initialized. Host agent must fill scenes/beats and generate sources before build.')


def prompts(root):
    plan = load(root)
    lines = ['# 母版提示词', '以private中的照片为唯一身份参考建立可辨认角色；默认精绘Q版，保留用户指定特征。',
             '不要凭空添加职业、姓名或标志；根据动作需要制作半身/全身。', '# 连续分镜']
    for e in plan['stickers']:
        c, r = e['grid']
        lines += [f"## {e['id']} {e['caption']}",
                  f"固定镜头，严格{c}列{r}行、等大正方形格；同一身份母版，统一光影与画风。",
                  f"触发：{e.get('trigger', '')}；场景：{e.get('scene', '')}。",
                  '默认绘制可辨认的精绘故事环境，角色、道具和背景共享透视与光照；透明底加孤立道具不能替代故事场景。用户明确选择透明简洁款时按该选择制作。固定背景锚点，不为每帧重新设计场所。',
                  '连续动作：' + '；'.join(e.get('beats', [])),
                  f"将聊天文案“{e['caption']}”实际绘制在每格画面内，不是文件名或说明文字。使用清晰的艺术字、描边与安全边距，所有帧字形一致，240像素下可读。只有用户明确要求无字时才省略；无字角色母版要求不适用于此分镜。背景锚点固定，动作真实展开。",
                  f"保存图集到 {e['source']}。检查实际等分、字形与人物细节后再合成。"]
    (root / 'prompts.md').write_text('\n\n'.join(lines), encoding='utf-8')


def encode(frames, durations, path):
    # Shared palette per sticker; reserve index 255 only for binary GIF transparency.
    atlas = Image.new('RGB', (240*len(frames), 240), 'white')
    for j, frame in enumerate(frames):
        bg = Image.new('RGBA', frame.size, 'white')
        bg.alpha_composite(frame)
        atlas.paste(bg.convert('RGB'), (240*j, 0))
    for colors in (192, 128, 96, 64):
        palette = atlas.quantize(colors=colors)
        encoded = []
        for frame in frames:
            bg = Image.new('RGBA', frame.size, 'white')
            bg.alpha_composite(frame)
            p = bg.convert('RGB').quantize(palette=palette, dither=Image.Dither.NONE)
            p.paste(255, mask=frame.getchannel('A').point(lambda a: 255 if a < 128 else 0))
            encoded.append(p)
        encoded[0].save(path, save_all=True, append_images=encoded[1:], duration=durations,
                        transparency=255, loop=0, disposal=2, optimize=False)
        if path.stat().st_size <= 500000:
            return colors
    raise ValueError(f'{path.name} exceeds 500000 bytes; simplify or shorten deliberately')


def build(root):
    plan = load(root)
    dst = root / 'output'
    dst.mkdir(exist_ok=True)
    buildinfo = []
    for e in plan['stickers']:
        cols, rows = e['grid']
        with Image.open(inside(root, e['source'])) as im:
            sheet = ImageOps.exif_transpose(im).convert('RGBA')
        w, h = sheet.size
        if w % cols or h % rows or w//cols != h//rows:
            raise ValueError(f"{e['id']}: sheet must be exactly divisible into square cells")
        tiles = [sheet.crop((j%cols*w//cols, j//cols*h//rows, (j%cols+1)*w//cols, (j//cols+1)*h//rows))
                 .resize((240, 240), Image.Resampling.LANCZOS) for j in range(cols*rows)]
        box = e.get('caption_box')
        if box is not None:
            coords = tuple(round(v*240) for v in box)
            donor = e.get('caption_frame', 0)
            if not isinstance(donor, int) or not 0 <= donor < len(tiles):
                raise ValueError('Invalid caption_frame')
            strip = tiles[donor].crop(coords)
            for frame in tiles:
                frame.paste(strip, coords[:2])
        order = e.get('order', list(range(cols*rows)))
        durations = e.get('durations_ms', [180]*len(order))
        colors = encode([tiles[j] for j in order], durations, dst / f"{e['id']}.gif")
        buildinfo.append(dict(id=e['id'], palette_colors=colors,
                              caption_locked=box is not None, visual_status=e.get('visual_status', 'pending'),
                              source_sha256=hashlib.sha256(inside(root, e['source']).read_bytes()).hexdigest(),
                              entry_sha256=hashlib.sha256(json.dumps(e, sort_keys=True, ensure_ascii=False).encode()).hexdigest()))
    write(dst / 'build.json', buildinfo)
    check(root)


def check(root):
    plan = load(root)
    dst = root / 'output'
    dst.mkdir(exist_ok=True)
    errors, warnings, report, cards = [], [], [], []
    index = {x['id']: x for x in json.loads((dst/'build.json').read_text(encoding='utf-8'))} if (dst/'build.json').exists() else {}
    if not 8 <= len(plan['stickers']) <= 24:
        warnings.append('WeChat album profile expects 8..24 stickers; current draft count differs')
    for e in plan['stickers']:
        path = dst / f"{e['id']}.gif"
        if not path.exists():
            errors.append(f"Missing {path.name}")
            continue
        try:
            recorded = index.get(e['id'], {})
            current = hashlib.sha256(json.dumps(e, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
            if recorded.get('entry_sha256') != current or recorded.get('source_sha256') != hashlib.sha256(inside(root,e['source']).read_bytes()).hexdigest():
                raise ValueError('Source or plan changed since build; rebuild before checking/packing')
            with Image.open(path) as im:
                info = im.info.copy()
                if im.format != 'GIF' or im.size != (240, 240) or info.get('loop') != 0:
                    raise ValueError('Expected 240x240 looping GIF')
                if path.stat().st_size > 500000:
                    raise ValueError('File exceeds 500000 bytes')
                frames, timings, hashes = [], [], []
                for j in range(im.n_frames):
                    im.seek(j)
                    frame = im.convert('RGBA')
                    frame.load()
                    duration = im.info.get('duration', 0)
                    if duration <= 0 or im.size != (240, 240):
                        raise ValueError('Invalid decoded frame timing or canvas')
                    frames.append(frame.copy()); timings.append(duration)
                    hashes.append(hashlib.sha256(frame.tobytes()).hexdigest())
                if len(set(hashes)) < 2:
                    raise ValueError('No distinct decoded movement; animation not established')
            contact = Image.new('RGB', (240*min(6, len(frames)), 240*((len(frames)+5)//6)), '#eeeeee')
            for j, frame in enumerate(frames):
                bg = Image.new('RGBA', frame.size, 'white'); bg.alpha_composite(frame)
                contact.paste(bg.convert('RGB'), (j%6*240, j//6*240))
            contact.save(dst / f"{e['id']}-decoded.png")
            report.append(dict(id=e['id'], caption=e['caption'], bytes=path.stat().st_size,
                               frames=len(frames), frame_ms=timings, duration_ms=sum(timings),
                               sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
                               visual_status=e.get('visual_status', 'pending'), known_limits=e.get('known_limits', [])))
            cards.append(f'<article><img src="{e["id"]}.gif"><p>{html.escape(e["caption"])}</p></article>')
            if e.get('visual_status') != 'accepted':
                warnings.append(f"{e['id']}: visual review/acceptance pending")
        except (OSError, ValueError) as exc:
            errors.append(f"{e['id']}: {exc}")
    if any(x.get('known_limits') for x in plan['stickers']):
        warnings.append('Read per-sticker known_limits before upload')
    spec = {'cover': ((240, 240), 500000), 'icon': ((50, 50), 100000), 'banner': ((750, 400), 500000)}
    seen_roles = set()
    for a in plan.get('attachments', []):
        role = a['role']; seen_roles.add(role)
        try:
            p = inside(root, a['source'])
            with Image.open(p) as im:
                size, limit = spec[role]
                if im.size != size or p.stat().st_size > limit:
                    raise ValueError('Wrong dimensions or file size')
                if role != 'banner' and (im.format != 'PNG' or im.convert('RGBA').getextrema()[3][0] != 0):
                    raise ValueError('Cover/icon must be transparent PNG')
                if role == 'banner' and (im.format not in ('JPEG', 'PNG') or im.convert('RGBA').getextrema()[3][0] < 255):
                    raise ValueError('Banner must be opaque JPEG/PNG')
        except (OSError, ValueError) as exc:
            errors.append(f'{role}: {exc}')
    if seen_roles != set(spec):
        warnings.append('Submission attachments incomplete; do not label as complete submission kit')
    result = dict(technical_pass=not errors, errors=errors, warnings=warnings, stickers=report,
                  content_review='Not established by technical checks; verify official profile and actual images')
    write(dst / 'report.json', result)
    page = '<!doctype html><meta charset="utf-8"><title>Sticker review</title><style>body{font:16px sans-serif;background:#eee5d8}main{display:flex;flex-wrap:wrap;gap:16px}article{background:white;padding:12px}img{width:240px;height:240px}</style>'
    page += '<h1>' + html.escape(plan.get('title', 'Sticker review')) + '</h1><p>Technical review is not platform approval.</p><main>' + ''.join(cards) + '</main>'
    (dst / 'preview.html').write_text(page, encoding='utf-8')
    if errors:
        raise ValueError('; '.join(errors))
    print(f"PASS: {len(report)} GIFs; {len(warnings)} review notices. See output/report.json")
    return plan


def pack(root):
    plan = check(root)
    path = root / 'delivery.zip'
    with zipfile.ZipFile(path, 'w', zipfile.ZIP_DEFLATED) as z:
        for e in plan['stickers']:
            for suffix in ('.gif', '-decoded.png'):
                p = root / 'output' / (e['id'] + suffix)
                z.write(p, p.name)
        for name in ('preview.html', 'report.json'):
            z.write(root / 'output' / name, name)
        for a in plan.get('attachments', []):
            p = inside(root, a['source'])
            z.write(p, 'attachments/' + a['role'] + p.suffix.lower())
        z.writestr('submission.json', json.dumps({k: plan.get(k, '') for k in ('title', 'artist', 'copyright')}, ensure_ascii=False, indent=2))
    with zipfile.ZipFile(path) as z:
        if z.testzip():
            raise ValueError('ZIP integrity check failed')
    print('Delivery created; private photos and source sheets excluded')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=('init', 'prompts', 'build', 'check', 'pack'))
    parser.add_argument('project', type=Path)
    parser.add_argument('--photo', type=Path)
    args = parser.parse_args(); root = args.project.resolve()
    try:
        if args.command == 'init':
            if args.photo is None:
                raise ValueError('--photo is required')
            init(root, args.photo)
        else:
            globals()[args.command](root)
    except (OSError, ValueError, KeyError, TypeError) as exc:
        parser.exit(2, f'ERROR: {exc}\n')


if __name__ == '__main__':
    main()
