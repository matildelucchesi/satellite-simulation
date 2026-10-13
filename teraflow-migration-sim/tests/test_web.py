import json
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch
from urllib.request import Request,urlopen
from urllib.error import HTTPError
from src.web import make_server
from src.storage import atomic_json,append_json


class LocalWebTests(unittest.TestCase):
    def setUp(self):
        self.temporary=tempfile.TemporaryDirectory();self.root=Path(self.temporary.name)
        self.server=make_server(self.root,0)
        self.thread=threading.Thread(target=self.server.serve_forever,daemon=True);self.thread.start()
        self.url='http://127.0.0.1:'+str(self.server.server_address[1])

    def tearDown(self):
        self.server.shutdown();self.server.server_close();self.thread.join();self.temporary.cleanup()

    def session(self):
        with urlopen(self.url+'/api/v1/session',timeout=5) as response:
            return json.load(response)['token'],response.headers['Set-Cookie'].split(';')[0]

    def command(self,token=None,cookie=None,origin=None):
        headers={'Content-Type':'application/json'}
        if token:headers['X-CSRF-Token']=token
        if cookie:headers['Cookie']=cookie
        if origin:headers['Origin']=origin
        request=Request(self.url+'/api/v1/jobs',data=b'{"operation":"environment"}',headers=headers)
        return urlopen(request,timeout=5)

    def test_commands_require_session_and_same_origin(self):
        token,cookie=self.session()
        for args in ({},{'token':token},{'token':token,'cookie':cookie,'origin':'https://foreign.example'}):
            with self.assertRaises(HTTPError) as caught:self.command(**args)
            self.assertEqual(caught.exception.code,403)
        with patch.object(self.server.application.jobs,'start',return_value={'job_id':'example'}) as start:
            with self.command(token,cookie,self.url) as response:self.assertEqual(response.status,202)
            start.assert_called_once_with('environment',None)

    def test_sse_reconnect_replays_only_events_after_cursor(self):
        identifier='job-'+'a'*32;directory=self.root/'results/jobs'/identifier;directory.mkdir()
        atomic_json(directory/'job.json',{'job_id':identifier,'status':'completed'})
        for index in range(1,4):append_json(directory/'events.jsonl',{'id':index,'phase':'test','timestamp_utc':'2026-10-08T00:00:00+00:00'})
        request=Request(self.url+'/api/v1/jobs/'+identifier+'/events',headers={'Last-Event-ID':'1'})
        with urlopen(request,timeout=5) as response:body=response.read().decode()
        self.assertNotIn('id: 1\n',body);self.assertIn('id: 2\n',body);self.assertIn('id: 3\n',body)
        self.assertIn('event: end\n',body)
        payloads=[json.loads(line[6:]) for line in body.splitlines() if line.startswith('data: ')]
        self.assertEqual([row['id'] for row in payloads[:-1]],[2,3])
        self.assertEqual(payloads[-1],{'status':'completed'})

    def test_downloads_only_registered_artifacts(self):
        atomic_json(self.root/'results/campaign.json',{'complete':False})
        with urlopen(self.url+'/api/v1/artifacts',timeout=5) as response:rows=json.load(response)['artifacts']
        self.assertEqual(len(rows),1)
        with urlopen(self.url+rows[0]['download_url'],timeout=5) as response:
            self.assertEqual(json.load(response),{'complete':False})
            self.assertIn('attachment',response.headers['Content-Disposition'])
        for path in ('/api/v1/artifacts/../../config/scenario.json','/../../secret','/api/v1/artifacts/unregistered'):
            with self.assertRaises(HTTPError) as caught:urlopen(self.url+path,timeout=5)
            self.assertEqual(caught.exception.code,404)

    def test_host_header_rebinding_is_rejected(self):
        request=Request(self.url+'/api/v1/session',headers={'Host':'foreign.example'})
        with self.assertRaises(HTTPError) as caught:urlopen(request,timeout=5)
        self.assertEqual(caught.exception.code,403)
