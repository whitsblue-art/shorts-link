import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock,patch
from io import BytesIO
from PIL import Image

from shopping import script, media, assets
from shopping.core import GateError


def story():
    lines=['수전 끝에 붙은 이건 필터 헤드예요. 수전 전체를 바꾸는 건 아닙니다.',
           '가운데로 모이거나 넓게 퍼지는 물줄기를 보세요. 같은 헤드에서 나오는 모습입니다.',
           '접시를 이렇게 헹구는 방식이에요. 제품은 프로필 링크에서 15번.']
    return {'style_version':3,'title':'끝에 붙은 작은 차이','thumbnail_text':'수전 끝에 붙은 작은 차이',
        'scenes':[{'scene_num':i,'narration':n,'badge':'실제 사용 모습','hook':'필터 헤드 살펴보기',
                   'sub':'프로필 링크에서 [15번] 검색!' if i==3 else '실제 사용 장면',
                   'visual_prompt':'Actual filter head demonstration','media_kind':'video'} for i,n in enumerate(lines,1)]}


class UsageTests(unittest.TestCase):
    def test_odd_sized_animated_source_is_encoded_without_losing_motion(self):
        frames=[Image.new('RGB',(401,401),color) for color in ('white','black','red')]
        data=BytesIO();frames[0].save(data,format='GIF',save_all=True,append_images=frames[1:],duration=500,loop=0)
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            with patch('shopping.assets.fetch',return_value=(data.getvalue(),'https://example.org/use.gif','image/gif')),patch('shopping.assets.validate_product_media',return_value={'verdict':'PASS'}):
                asset=assets.demonstration_clip(Mock(),{},root/'unused.jpg',{'url':'https://example.org/use.gif'},root,1)
            info=media.probe(root/asset['clip'])['streams'][0]
            self.assertEqual((info['width'],info['height']),(402,402))
            self.assertGreater(asset['motion_change'],.25)

    def test_one_final_cta_and_real_motion_required(self):
        script.validate(story(),15)
        for field,value in [('narration','프로필을 보세요. '+story()['scenes'][0]['narration']),('media_kind','image')]:
            bad=story();bad['scenes'][0][field]=value
            with self.assertRaises(GateError):script.validate(bad,15)

    def test_script_review_uses_each_actual_scene_and_alignment_gate(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            for n in range(1,4):Image.new('RGB',(400,400),(n*40,10,10)).save(root/f'scene_{n:02d}.jpg')
            ai=Mock();script.review(ai,{'title':'주방 필터 헤드'},15,story(),root)
            prompt,checks,parts=ai.judge.call_args.args
            self.assertIn('scene_action_alignment',checks)
            self.assertIn('correct_product_noun',checks)
            self.assertEqual(sum(p.get('type')=='input_image' for p in parts),3)
        with self.assertRaises(GateError):script.review(Mock(),{'title':'filter'},15,story())

    def test_compact_subtitles_preserve_all_words(self):
        words=['수전','끝에','붙은','작은','필터','헤드로','접시를','헹구는','모습입니다']
        boundaries=[{'text':w,'start':i*.4,'end':i*.4+.35} for i,w in enumerate(words)]
        cues=media.caption_cues(boundaries,media.PROFILES['shorts'],compact=True)
        self.assertTrue(all(len(c['lines'])==1 for c in cues))
        self.assertEqual(' '.join(' '.join(c['lines']) for c in cues),' '.join(words))


if __name__=='__main__':unittest.main()
