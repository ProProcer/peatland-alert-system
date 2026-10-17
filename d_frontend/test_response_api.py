"""Exercise the response UI adapter over HTTP without changing shared data."""
from http.client import HTTPConnection
import json
from pathlib import Path
import shutil
import tempfile
import threading
import unittest
from unittest.mock import patch
from d_frontend.serve_demo import make_server, ROOT


class ResponseInterfaceTests(unittest.TestCase):
    def test_run_previews_settings_and_origin_rejection(self):
        with tempfile.TemporaryDirectory() as temp:
            folder=Path(temp)
            source=folder/'role_a_real/regional_40'
            source.mkdir(parents=True)
            for name in ['features.json','risk.json','cells.geojson']:
                shutil.copy(ROOT/'contracts/examples'/name, source/name)
            with patch('d_frontend.response_api.STATE',folder/'incidents.json'), patch('d_frontend.response_api.LOG',folder/'notifications.log'), make_server(folder,port=0) as server:
                thread=threading.Thread(target=server.serve_forever,daemon=True)
                thread.start()
                conn=HTTPConnection('127.0.0.1',server.server_port,timeout=10)
                def request(path,body=None,origin=None):
                    headers={'Content-Type':'application/json'}
                    if origin:headers['Origin']=origin
                    conn.request('POST' if body is not None else 'GET',path,json.dumps(body) if body is not None else None,headers)
                    result=conn.getresponse()
                    return result.status,json.loads(result.read())
                try:
                    code,data=request('/response/status')
                    self.assertEqual(code,200)
                    self.assertFalse(data['available'])
                    code,data=request('/response/run',{'cooldown_hours':6,'max_water_km':15,'use_llm':False})
                    self.assertEqual(code,200,data)
                    self.assertTrue(data['dispatches'])
                    self.assertTrue(data['social']['twitter'])
                    self.assertTrue(data['individual_emails'])
                    self.assertTrue(data['engine']['state_persisted'])
                    self.assertTrue(data['log'])
                    first=data['dispatches']
                    self.assertEqual(request('/response/run',{})[1]['dispatches'],first)
                    self.assertEqual(request('/response/run',{'max_water_km':-1})[0],400)
                    self.assertEqual(request('/response/run',{},'https://example.com')[0],403)
                finally:
                    conn.close()
                    server.shutdown()
                    thread.join(timeout=5)
