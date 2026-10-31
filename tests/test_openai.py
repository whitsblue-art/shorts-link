import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

from shopping.ai import AI, strict_schema, review_audio
from shopping.core import GateError, AIUnavailable
from shopping.pipeline import verified_files


def response(data, status=200):
    r=Mock(status_code=status,headers={'Content-Type':'application/json'})
    r.json.return_value=data
    return r


def output(value):
    return {'status':'completed','output':[{'type':'message','content':[{'type':'output_text','text':json.dumps(value)}]}],
            'usage':{'input_tokens':100,'output_tokens':30}}


class OpenAITests(unittest.TestCase):
    def setUp(self):
        self.env=patch.dict(os.environ,{'OPENAI_API_KEY':'test-only-secret'})
        self.env.start()
        self.addCleanup(self.env.stop)

    def test_old_provider_key_never_substitutes_for_openai(self):
        with patch.dict(os.environ,{'OPENAI_API_KEY':'','GEMINI_API_KEY':'old-key'}):
            with self.assertRaises(AIUnavailable): AI()

    def test_strict_response_schema_and_actual_image_transport(self):
        schema={'type':'OBJECT','properties':{'ok':{'type':'BOOLEAN'}}}
        image={'type':'input_image','image_url':'data:image/jpeg;base64,TEST','detail':'high'}
        with patch('shopping.ai.requests.post',return_value=response(output({'ok':True}))) as post:
            self.assertEqual(AI().json('Review image',[image],schema=schema),{'ok':True})
        args=post.call_args
        self.assertEqual(args.args[0],'https://api.openai.com/v1/responses')
        body=args.kwargs['json']
        self.assertFalse(body['store'])
        self.assertEqual(body['input'][0]['content'][1],image)
        self.assertEqual(body['reasoning'],{'effort':'low'})
        self.assertNotIn('temperature',body)
        contract=body['text']['format']
        self.assertTrue(contract['strict'])
        self.assertEqual(contract['schema']['required'],['ok'])
        self.assertFalse(contract['schema']['additionalProperties'])

    def test_schema_is_enforced_locally_too(self):
        for bad in ({'ok':'true'},{'ok':True,'extra':1},{}):
            with patch('shopping.ai.requests.post',return_value=response(output(bad))):
                with self.assertRaises(GateError):
                    AI().json('Return JSON',schema={'type':'OBJECT','properties':{'ok':{'type':'BOOLEAN'}}})

    def test_incomplete_and_refusal_never_pass(self):
        cases=[{'status':'incomplete','output':[]},
            {'status':'completed','output':[{'content':[{'type':'refusal','refusal':'no'}]}]}]
        for value in cases:
            with patch('shopping.ai.requests.post',return_value=response(value)):
                with self.assertRaises(GateError): AI().json('test')

    def test_unknown_and_omitted_verdict_checks_reject(self):
        for value in ({'verdict':'UNKNOWN','reason':'uncertain','checks':{'same_model':'UNKNOWN'}},
                      {'verdict':'PASS','reason':'omitted','checks':{}}):
            with patch('shopping.ai.requests.post',return_value=response(output(value))):
                with self.assertRaises(GateError): AI().judge('Check actual model',['same_model'])

    def test_search_uses_structured_citations_not_guessed_text_urls(self):
        value={'status':'completed','output':[
            {'type':'web_search_call','action':{'sources':[{'url':'https://official.example/p','title':'Official'}]}},
            {'type':'message','content':[{'type':'output_text','text':'Guess: https://invented.example/','annotations':[
                {'type':'url_citation','url':'https://official.example/p','title':'Official'}]}]}]}
        with patch('shopping.ai.requests.post',return_value=response(value)) as post:
            result=AI().search('Find exact product')
        self.assertEqual(result['sources'],[{'url':'https://official.example/p','title':'Official'}])
        self.assertEqual(post.call_args.kwargs['json']['tools'][0]['type'],'web_search')

    def test_original_audio_goes_to_audio_model_and_is_locally_validated(self):
        verdict={'verdict':'PASS','reason':'actual speech matches','checks':{'same_meaning':'PASS'}}
        value={'choices':[{'finish_reason':'stop','message':{'content':json.dumps(verdict)}}]}
        audio={'type':'input_audio','input_audio':{'format':'mp3','data':'SAMPLE'}}
        with patch('shopping.ai.requests.post',return_value=response(value)) as post:
            result=AI().judge('Listen to actual original audio',['same_meaning'],[audio])
        self.assertEqual(post.call_args.args[0],'https://api.openai.com/v1/chat/completions')
        body=post.call_args.kwargs['json']
        self.assertEqual(body['messages'][1]['content'][1],audio)
        self.assertNotIn('response_format',body)
        self.assertEqual(result['review_model'],'gpt-audio-1.5')
        self.assertEqual(result['provider'],'openai')

    def test_transcriber_is_blind_to_expected_narration(self):
        with tempfile.TemporaryDirectory() as temp:
            p=Path(temp)/'voice.mp3';p.write_bytes(b'audio fixture')
            with patch('shopping.ai.requests.post',return_value=response({'text':'실제 음성'})) as post:
                self.assertEqual(AI().transcribe(p),'실제 음성')
            self.assertEqual(post.call_args.args[0],'https://api.openai.com/v1/audio/transcriptions')
            self.assertNotIn('prompt',post.call_args.kwargs['data'])
            self.assertEqual(post.call_args.kwargs['files']['file'][1],b'audio fixture')

    def test_audio_review_receives_original_and_transcript_is_only_hint(self):
        ai=Mock(transcribe_model='test-transcriber')
        ai.transcribe.return_value='프로필 링크에서 15번을 검색해 주세요'
        ai.judge.return_value={'verdict':'PASS','provider':'openai'}
        with tempfile.TemporaryDirectory() as temp:
            p=Path(temp)/'voice.mp3';p.write_bytes(b'original mp3')
            r=review_audio(ai,p,'프로필 링크에서 15번을 검색해 주세요')
        self.assertEqual(ai.judge.call_args.args[2][0]['type'],'input_audio')
        self.assertEqual(r['provider'],'openai')

    def test_errors_do_not_print_server_message_or_secret(self):
        bad={'error':{'message':'test-only-secret sensitive server body','code':'invalid_api_key'}}
        with patch('shopping.ai.requests.post',return_value=response(bad,401)):
            with self.assertRaises(AIUnavailable) as caught: AI().json('test')
        self.assertNotIn('test-only-secret',str(caught.exception))
        self.assertNotIn('sensitive',str(caught.exception))

    def test_previous_provider_approval_cannot_be_released(self):
        with tempfile.TemporaryDirectory() as temp:
            with self.assertRaisesRegex(GateError,'current OpenAI'):
                verified_files({'qa_passed':True,'qa_provider':'old-provider','qa_version':1},Path(temp))

    def test_current_review_receipt_accepts_only_matching_file_bytes(self):
        from shopping.core import fingerprint
        with tempfile.TemporaryDirectory() as temp:
            directory=Path(temp);(directory/'video.mp4').write_bytes(b'reviewed')
            row={'qa_passed':True,'qa_provider':'openai','qa_version':2,'asset_hashes':{'video.mp4':fingerprint(b'reviewed')}}
            verified_files(row,directory)
            (directory/'video.mp4').write_bytes(b'replaced')
            with self.assertRaisesRegex(GateError,'modified'):
                verified_files(row,directory)

    def test_active_workflows_do_not_use_previous_provider(self):
        root=Path(__file__).resolve().parent.parent
        for path in (root/'.github/workflows').glob('*.yml'):
            self.assertNotIn('GEMINI_API_KEY',path.read_text(encoding='utf-8'))


if __name__=='__main__': unittest.main()
