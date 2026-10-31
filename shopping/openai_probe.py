"""Small real capability tests; no catalog writes or YouTube publishing."""
import asyncio
import json
import os
from pathlib import Path
import sys
from PIL import Image
from .ai import AI, image_part, review_audio
from .core import ROOT, GateError, AIUnavailable, atomic_json
from .media import make_voice


def main():
    directory=ROOT/'current_episode/openai_capabilities'
    directory.mkdir(parents=True,exist_ok=True)
    rows=[]
    try:
        ai=AI(directory/'usage.json')
    except GateError as exc:
        rows.append({'check':'OpenAI key','ok':False,'detail':str(exc)})
        atomic_json(directory/'report.json',rows)
        print(json.dumps(rows,ensure_ascii=False),flush=True)
        return 1
    Image.new('RGB',(512,512),'red').save(directory/'test_red.jpg')
    def structured():
        r=ai.json('Connection test. Return {"ok":true}.',schema={'type':'OBJECT','properties':{'ok':{'type':'BOOLEAN'}}})
        if r.get('ok') is not True: raise GateError('Structured positive control failed')
        return {'model':ai.text_model,'contract':'strict JSON'}
    def vision():
        r=ai.json('What is the dominant color? Use an English lowercase color name.',[image_part(directory/'test_red.jpg')],review=True,
            schema={'type':'OBJECT','properties':{'color':{'type':'STRING'}}})
        if r['color'].lower()!='red': raise GateError('Vision positive control failed')
        return {'model':ai.review_model,'color':r['color']}
    def search():
        r=ai.search('Find the official YouTube Data API documentation. Cite the official Google documentation URL.')
        if not r['sources']: raise GateError('Search returned no structured source URLs')
        return {'cited_source_count':len(r['sources'])}
    def speech():
        text='연결 검사입니다. 프로필 링크에서 십오 번을 검색해 주세요.'
        path=directory/'test_voice.mp3'
        asyncio.run(make_voice(text,path,'shorts'))
        r=review_audio(ai,path,text)
        atomic_json(directory/'audio_review.json',r)
        return {'transcription_model':ai.transcribe_model,'audio_review_model':ai.audio_review_model,'semantic_verdict':r['semantic_review']['verdict']}
    for label,fn in [('structured text',structured),('image understanding',vision),('cited web search',search),('transcription and original-audio review',speech)]:
        try:
            rows.append({'check':label,'ok':True,'detail':fn()})
        except GateError as exc:
            rows.append({'check':label,'ok':False,'detail':str(exc)})
            if isinstance(exc,AIUnavailable): break
        except Exception as exc:
            rows.append({'check':label,'ok':False,'detail':type(exc).__name__})
        atomic_json(directory/'report.json',rows)
        print(json.dumps(rows[-1],ensure_ascii=False),flush=True)
    atomic_json(directory/'report.json',rows)
    return 0 if len(rows)==4 and all(row['ok'] for row in rows) else 1


if __name__=='__main__':
    sys.exit(main())
