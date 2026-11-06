"""Self-contained presentation of captured questions; original media stays untouched."""
import base64
import html
import json
import mimetypes
import re
from pathlib import Path
from xml.etree import ElementTree as ET
from zipfile import ZipFile

from .math_typesetting import MathTypesetter


STYLE = '''
:root{color-scheme:light;font-size:18px}*{box-sizing:border-box}
body{margin:0;background:#f4f6fa;color:#172338;font:1rem/1.9 -apple-system,BlinkMacSystemFont,"PingFang SC","Microsoft YaHei",sans-serif}
main{max-width:1060px;margin:42px auto;padding:0 24px}h1{font-size:1.8rem;line-height:1.4}h2{font-size:1.3rem;margin:8px 0 20px}
.lead{color:#485970}.badge{display:inline-block;background:#e5edff;color:#2751a3;padding:4px 12px;border-radius:8px}
.eyebrow,.meta,figcaption{font-size:.82rem;color:#52627b}article{background:#fff;padding:32px;margin:28px 0;border-radius:14px;border:1px solid #dce3ed;min-width:0}
.question-content p,.solution-content p{margin:.8em 0;overflow-wrap:anywhere}
.math-image-link{display:inline-block;vertical-align:middle;max-width:100%;overflow-x:auto;overflow-y:hidden;margin:0 .08em;line-height:0;background:white;border-radius:3px;cursor:zoom-in}
.math-image-link:hover{outline:1px solid #92b5e8}.math-image{display:block;width:var(--math-width);max-width:none;height:auto;background:#fff}
.figure-card{margin:24px 0;padding:18px;border:1px solid #dde5ef;border-radius:10px;background:#fff;text-align:center}
.figure-image-link{display:block;width:100%;cursor:zoom-in}.figure-image{display:block;width:min(100%,var(--figure-width));height:auto;margin:auto;background:#fff}
figcaption{margin-top:12px;line-height:1.6}figcaption button{margin:6px 0 0 10px}
.options{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:12px;margin:18px 0}.option{min-width:0}
details{border-top:1px solid #e4e8ee;padding:14px 0}summary{cursor:pointer;color:#244d8c;font-weight:600}
.table-scroll{overflow-x:auto}table{width:100%;border-collapse:collapse;font-size:.82rem}th,td{padding:10px;border-bottom:1px solid #e4e8ee;text-align:left;vertical-align:top;overflow-wrap:anywhere}th:first-child{min-width:6em}
pre{white-space:pre-wrap;overflow-wrap:anywhere;font-size:.8rem;background:#f3f5f8;padding:14px}a{color:#2455ae}
.note{background:#edf3fc;padding:16px 20px;border-radius:9px}nav{font-size:.85rem;display:flex;gap:8px 18px;flex-wrap:wrap}
button{font:inherit;font-size:.82rem;cursor:pointer;background:#fff;border:1px solid #b9cbe2;border-radius:7px;padding:5px 12px;color:#244d8c}button:hover{background:#edf3fc}
:focus-visible{outline:3px solid #6599e4;outline-offset:3px}
.image-viewer{width:calc(100vw - 32px);max-width:1440px;height:94vh;max-height:94vh;padding:0;border:1px solid #cdd9e8;border-radius:12px;background:#fff;color:#172338}
.image-viewer::backdrop{background:rgba(12,24,43,.7)}.viewer-header{display:flex;gap:12px;align-items:center;justify-content:space-between;padding:14px 18px;border-bottom:1px solid #e0e7f0}
.viewer-title{font-size:.9rem;margin:0;line-height:1.5}.viewer-controls{display:flex;gap:8px;flex-wrap:wrap;flex-shrink:0}
.viewer-stage{height:calc(100% - 112px);overflow:auto;padding:16px;background:#edf1f6}.viewer-stage img{display:block;max-width:none;height:auto;margin:auto;background:#fff}
.viewer-hint{font-size:.76rem;color:#52627b;margin:6px 16px}
.math-inline{display:inline-block;max-width:100%;overflow-x:auto;overflow-y:hidden;vertical-align:middle;padding:.12em 0;line-height:1.4;white-space:nowrap}
.math-display{display:block;max-width:100%;overflow-x:auto;overflow-y:hidden;padding:8px 0}.math-display .katex-display{margin:.35em 0}
.katex{font-size:1.08em}.question-parts{list-style:none;padding:0}.question-parts li{margin:.8em 0}.part-number{font-weight:600;margin-right:.3em}
.options.text-options{grid-template-columns:1fr}.option{display:flex;gap:.6em;align-items:baseline}.option-label{flex-shrink:0;font-weight:500}
.solution-guide{background:#f5f8fd;border:1px solid #d8e3f1;border-radius:10px;padding:18px 22px;margin:24px 0}
.solution-guide>summary{font-size:1.06rem}.guide-title{font-weight:600;margin:.8em 0 .3em}.guide-lead{color:#244d69}
.guide-route{border-top:1px solid #d8e3f1;margin-top:20px;padding-top:12px}.guide-route h4{margin:.4em 0;font-size:1rem}
.guide-dl{margin:8px 0}.guide-dl dt{font-weight:600;color:#355578;margin-top:12px}.guide-dl dd{margin:2px 0 12px}
.guide-steps{padding-left:1.5em}.guide-steps li{padding:4px 0}.step-reason{display:block;color:#536279;font-size:.92rem}
.guide-transfer{background:#e9f0fa;border-radius:8px;padding:14px 18px;margin-top:20px}.guide-transfer h4{margin:0 0 8px}
.guide-checks{display:grid;grid-template-columns:1fr 1fr;gap:20px}.guide-checks h4{margin:12px 0 6px}.guide-checks ul,.guide-transfer ul{padding-left:1.3em;margin:6px 0}
.answer-summary{border-left:3px solid #8aa4c7;padding-left:16px}.print-title,.print-question-number{display:none}.editorial-note{font-size:.78rem;color:#586980}
@media(max-width:640px){:root{font-size:17px}main{margin:20px auto;padding:0 10px}article{padding:18px 14px}.figure-card{padding:10px;margin:20px 0}.options{grid-template-columns:repeat(2,minmax(0,1fr))}h1{font-size:1.45rem}.viewer-header{align-items:flex-start;flex-direction:column}.viewer-stage{height:calc(100% - 165px)}.viewer-controls{gap:5px}th,td{padding:7px}}
@media(max-width:640px){.solution-guide{padding:14px 12px}.guide-checks{grid-template-columns:1fr;gap:4px}.guide-transfer{padding:10px 12px}}
@media print{@page{size:A4;margin:18mm}body{background:#fff;color:#000;font-size:12pt}main{max-width:none;margin:0;padding:0}article{break-inside:auto;border:0;padding:0;margin:20px 0}.figure-card{break-inside:avoid;padding:0;border:0}.page-intro,.page-footer,.teaching-material,.image-viewer,figcaption button,.meta,.eyebrow,.screen-title{display:none!important}.print-title{display:block;text-align:center;font-size:18pt}.print-question-number{display:inline}.math-image-link,.math-inline,.math-display{overflow:visible}.math-image{max-width:100%}h2{font-size:13pt;break-after:avoid}.figure-image{max-height:90mm;width:auto;max-width:100%}a{color:inherit;text-decoration:none}}
'''

VIEWER = '''
<dialog id="image-viewer" class="image-viewer" aria-labelledby="viewer-title">
 <div class="viewer-header"><p id="viewer-title" class="viewer-title">查看原图</p>
  <div class="viewer-controls"><button type="button" id="zoom-out" aria-label="缩小图片">缩小 −</button><button type="button" id="zoom-in" aria-label="放大图片">放大 ＋</button><button type="button" id="zoom-fit">适应窗口</button><button type="button" id="viewer-close" autofocus>关闭</button></div>
 </div><div class="viewer-stage" id="viewer-stage"><img id="viewer-image" alt=""></div>
 <p class="viewer-hint">可放大查看细节；放大后滚动查看图片，按 Esc 关闭。</p>
</dialog>
<script>
(() => {
 const dialog=document.getElementById('image-viewer'),picture=document.getElementById('viewer-image'),stage=document.getElementById('viewer-stage');
 let width=0,opener=null;
 const fit=()=>{if(!picture.naturalWidth)return;width=Math.min(picture.naturalWidth,Math.max(120,stage.clientWidth-32),Math.max(120,stage.clientHeight-32)*picture.naturalWidth/picture.naturalHeight);picture.style.width=width+'px';stage.scrollTop=0;stage.scrollLeft=0;};
 document.addEventListener('click',event=>{
  const trigger=event.target.closest('[data-image-ref]');if(!trigger)return;
  const source=document.getElementById(trigger.dataset.imageRef);if(!source)return;
  event.preventDefault();opener=trigger;picture.alt=source.alt;document.getElementById('viewer-title').textContent=source.alt;
  picture.onload=()=>requestAnimationFrame(fit);picture.src=source.src;
  if(!dialog.open)dialog.showModal();if(picture.complete)requestAnimationFrame(fit);
 });
 document.getElementById('viewer-close').addEventListener('click',()=>dialog.close());
 document.getElementById('zoom-fit').addEventListener('click',fit);
 document.getElementById('zoom-in').addEventListener('click',()=>{width=Math.min(width*1.5,picture.naturalWidth*4);picture.style.width=width+'px';});
 document.getElementById('zoom-out').addEventListener('click',()=>{width=Math.max(100,width/1.5);picture.style.width=width+'px';});
 dialog.addEventListener('click',event=>{if(event.target===dialog)dialog.close();});
 dialog.addEventListener('close',()=>{if(opener)opener.focus({preventScroll:true});});
 window.addEventListener('resize',()=>{if(dialog.open)fit();});
})();
</script>
'''


def word_media_roles(path):
    """Use OOXML equation objects versus picture drawings, rather than image dimensions."""
    with ZipFile(path) as archive:
        root = ET.fromstring(archive.read('word/document.xml'))
    ns = {'w':'http://schemas.openxmlformats.org/wordprocessingml/2006/main',
          'a':'http://schemas.openxmlformats.org/drawingml/2006/main',
          'r':'http://schemas.openxmlformats.org/officeDocument/2006/relationships',
          'v':'urn:schemas-microsoft-com:vml','o':'urn:schemas-microsoft-com:office:office'}
    roles = {}
    for picture in root.findall('.//a:blip',ns):
        roles[picture.get('{'+ns['r']+'}embed')] = 'diagram'
    for obj in root.findall('.//w:object',ns):
        if obj.find('o:OLEObject',ns) is not None:
            for picture in obj.findall('.//v:imagedata',ns):
                roles[picture.get('{'+ns['r']+'}id')] = 'formula'
    return roles


def render_preview(questions, root, typesetter=None, total_count=None):
    root = Path(root).resolve()
    esc = html.escape
    typesetter = typesetter or MathTypesetter([{'presentation':q['presentation'],'guide':q['solution_guide']} for q in questions])
    total_count = len(questions) if total_count is None else total_count
    rich = typesetter.render
    data_cache,role_cache = {},{}
    serial = 0

    def embedded_image(asset):
        if asset not in data_cache:
            path=(root/asset).resolve()
            if root not in path.parents:
                raise ValueError('Image outside the artifact directory')
            mime=mimetypes.guess_type(path.name)[0] or 'image/png'
            data_cache[asset]='data:'+mime+';base64,'+base64.b64encode(path.read_bytes()).decode('ascii')
        return data_cache[asset]

    def render_question_blocks(question, blocks, section):
        nonlocal serial
        original=question['source']['original_file']
        if original not in role_cache:
            role_cache[original]=word_media_roles(root/original)
        roles=role_cache[original]
        assets={a['relationship_id']:a for a in question['assets']}
        figures={f['relationship_id']:f for f in question['content'].get('figures',[])}
        diagram_index=0

        def render_image(token, diagram=False):
            nonlocal serial,diagram_index
            serial+=1
            image_id='media-'+str(serial)
            rid=token['relationship_id'];asset=assets[rid]
            data=embedded_image(asset['path'])
            if diagram:
                diagram_index+=1
                alt=figures.get(rid,{}).get('alt',f'题目 {question["source"]["question_id"]} 的解析配图 {diagram_index}')
                w,h=asset['dimensions_px']
                target=(920 if w/h>2 else 720) if rid in figures else (440 if h>w else 600)
                return f'<figure class="figure-card"><a class="figure-image-link" href="#image-viewer" data-image-ref="{image_id}" aria-label="放大：{esc(alt)}"><img id="{image_id}" class="figure-image" src="{data}" alt="{esc(alt)}" style="--figure-width:{target}px" width="{w}" height="{h}"></a><figcaption>{esc(alt)}<button type="button" data-image-ref="{image_id}">放大查看</button></figcaption></figure>'
            # Preserve formula proportions and scale the Word sizing to the reading font.
            width=token.get('display_width_px') or asset['dimensions_px'][0]/6.8
            em=round(width*1.5/18,4)
            alt=f'题目 {question["source"]["question_id"]} 的公式（点击放大）'
            return f'<a class="math-image-link" href="#image-viewer" data-image-ref="{image_id}"><img id="{image_id}" class="math-image" src="{data}" alt="{alt}" style="--math-width:{em}em"></a>'

        def render_inline(tokens):
            return ''.join(esc(t['text']).replace('\n','<br>') if t['kind']=='text' else render_image(t) for t in tokens)

        rendered=[]
        for block in blocks:
            tokens=block['tokens']
            if not tokens:
                continue
            # Keep the original four-option paragraph as four clearly separated cells.
            cells=[]
            if tokens[0].get('text')=='A．':
                for token in tokens:
                    if token['kind']=='text' and re.fullmatch(r'\s*[A-D][.．]\s*',token['text']):
                        cells.append([])
                    if cells:
                        cells[-1].append(token)
            if len(cells)==4:
                rendered.append('<div class="options">'+''.join('<div class="option">'+render_inline(c)+'</div>' for c in cells)+'</div>')
                continue
            inline=[]
            for token in tokens:
                if token['kind']=='image' and (token['relationship_id'] in figures or roles.get(token['relationship_id'])=='diagram'):
                    if inline:
                        rendered.append('<p>'+render_inline(inline)+'</p>');inline=[]
                    rendered.append(render_image(token,True))
                else:
                    inline.append(token)
            if inline:
                rendered.append('<p>'+render_inline(inline)+'</p>')
        return '<div class="'+section+'-content">'+''.join(rendered)+'</div>'

    def edited_stem(question):
        edited=question['presentation']
        pieces=['<div class="question-content"><p>'+rich(edited['stem_latex'])+'</p>']
        figure_rids={f['relationship_id'] for f in question['content']['figures']}
        figure_blocks=[{'tokens':[t]} for b in question['content']['source_blocks'] for t in b['tokens']
                       if t['kind']=='image' and t['relationship_id'] in figure_rids]
        if figure_blocks:
            pieces.append(render_question_blocks(question,figure_blocks,'question'))
        if edited['options']:
            text_options=' text-options' if any(len(o['content'])>30 or re.search(r'[\u4e00-\u9fff]',o['content']) for o in edited['options']) else ''
            pieces.append('<div class="options'+text_options+'">'+''.join(
                '<div class="option"><span class="option-label">'+esc(o['key'])+'．</span><span>'+rich(o['content'])+'</span></div>' for o in edited['options'])+'</div>')
        if edited['parts']:
            pieces.append('<ol class="question-parts">'+''.join('<li><span class="part-number">（'+esc(p['id'])+'）</span>'+rich(p['content'])+'</li>' for p in edited['parts'])+'</ol>')
        return ''.join(pieces)+'</div>'

    def guidance(question):
        guide=question['solution_guide']
        pieces=['<details class="solution-guide teaching-material" open><summary>解题思路与套路</summary>',
                '<p class="guide-lead">'+rich(guide['one_sentence'])+'</p>']
        multipart=len(guide['routes'])>1
        for route in guide['routes']:
            pieces.append('<section'+(' class="guide-route"' if multipart else '')+'>')
            if multipart:
                pieces.append('<h4>（'+esc(route['part_id'])+'）'+rich(route['label'])+'</h4><p>'+rich(route['why'])+'</p>')
            pieces.append('<ol class="guide-steps">'+''.join('<li>'+rich(s['action'])+'</li>' for s in route['steps'])+'</ol></section>')
        # Structured reasoning stays in JSON; the reading view focuses on the decision and key steps.
        pieces.append('<p><strong>易错提醒</strong></p><ul>'+''.join('<li>'+rich(s)+'</li>' for s in guide['pitfalls'])+'</ul>')
        pieces.append('<p class="editorial-note">补充指导 · 待教师审核</p></details>')
        return ''.join(pieces)

    dimensions=[('chapter','章节'),('syllabus_knowledge','考纲知识点'),('question_type','题型'),('difficulty','难度'),('question_category','题目类别'),('solution_strategies','解题思路与技巧'),('year','年份'),('correct_rate','正确率'),('score_rate','得分率'),('used_in_papers','已组卷')]
    statuses={'unavailable':'来源未提供','source_observed':'来源原标','source_normalized':'来源标签归一化','inferred':'推断，待复核','not_assessed':'待标注','mixed':'来源标签及推断，待复核','deferred':'预留，后续接入'}
    role_names={'primary':'主知识点','secondary':'次知识点','supporting':'辅助知识点'}
    cards=[]
    for number,question in enumerate(sorted(questions,key=lambda q:not q['content'].get('figures')),1):
        rows=[]
        for key,name in dimensions:
            tag=question['tags'][key]
            value='、'.join(map(str,tag['values'])) or '暂无数据'
            if key=='difficulty':value=question['source']['difficulty_raw']['label_3']
            if key=='question_type':value=question['source']['question_type_raw']
            if tag['status']=='deferred':value='—'
            rows.append(f'<tr><th>{name}</th><td>{esc(value)}</td><td>{statuses[tag["status"]]}</td></tr>')
        matches='；'.join(m['node_id']+' '+m['node_name']+'（'+role_names[m['role']]+'）' for m in question['alignment']['matches'])
        gaps='；'.join(dict.fromkeys(g['proposal'] for g in question['alignment']['unmapped'])) or '本题未发现未映射的来源知识点'
        stem=edited_stem(question)
        original_stem=render_question_blocks(question,question['content']['source_blocks'],'source-question')
        solution=render_question_blocks(question,question['answer']['source_blocks']+question['explanation']['source_blocks'],'solution')
        changes=''.join('<li>'+esc(c['reason'])+'</li>' for c in question['presentation']['changes'])
        source=question['source']
        cards.append(f'''<article id="{question['id']}"><div class="eyebrow">{esc(source['question_type_raw'])} · {esc(source['difficulty_raw']['label'])} · 系数 {source['difficulty_raw']['coefficient']}</div><h2><span class="screen-title">题目 {source['question_id']}</span><span class="print-question-number">{number}．</span></h2>
{stem}<p class="meta">来源：{esc(source['paper'].get('title') or '来源试卷名称未提供')} · <a href="{esc(source['original_file'])}">下载原件</a></p>
{guidance(question)}
<details class="teaching-material"><summary>查看答案与完整解析</summary><p class="answer-summary">{rich(question['presentation']['answer_summary_latex'])}</p><p class="editorial-note">以下为来源完整解答，保留原有公式和文字。{esc(question['explanation']['note'])}</p>{solution}</details>
<details class="teaching-material"><summary>查看标签与知识点对齐</summary><div class="table-scroll"><table><thead><tr><th>维度</th><th>值</th><th>证据状态</th></tr></thead><tbody>{''.join(rows)}</tbody></table></div><p>对齐建议：{esc(matches)}</p><p>待补知识点：{esc(gaps)}</p><p class="meta">以上对齐及推断标签待教师复核。</p></details>
<details class="teaching-material"><summary>查看来源原文与整理记录</summary>{original_stem}<p>规范展示的调整：</p><ul>{changes}</ul><a href="questions/{question['id']}.json">逐题 JSON（含解题思路与套路）</a></details></article>''')
    return f'''<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>高中数学 · 题库预览</title><style>{typesetter.css}\n{STYLE}</style></head><body>
<main><div class="page-intro"><span class="badge">高中数学 · 本地整理</span><h1>数学题目与标签样例</h1><p class="lead">共 {total_count} 道题，本页预览 {len(questions)} 道。含解题思路与套路，图表可点击放大；完整数据见下方链接。</p>
<p class="note">当前整理 7 类题目标签。“思想方法”与“核心素养”统一为“解题思路与技巧”；正确率、得分率、已组卷先留空。知识点映射与推断标签待复核。</p>
<nav><a href="questions.jsonl">全部题目数据</a><a href="validation.json">校验结果</a></nav></div><h1 class="print-title">高中数学试题（预览）</h1>
{''.join(cards)}<p class="page-footer meta">图片和数学字体已嵌入，可离线打开；浏览器打印时仅输出题目。本地整理预览；数据与内容复核状态见校验结果。</p></main>{VIEWER}</body></html>'''
