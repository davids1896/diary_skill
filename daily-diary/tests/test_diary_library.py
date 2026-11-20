from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import threading
import subprocess
import unittest
import urllib.request
import urllib.error

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from diary_library import Library, SafeHTML


class LibraryTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.cache, self.web, self.archive = [self.root / n for n in ['cache', 'web', 'archive']]
        for p in [self.cache, self.web, self.archive]:p.mkdir()
        (self.web / 'index.html').write_text('<h1>日记</h1>')
        self.lib = Library({'cache':str(self.cache),'assets':str(self.web),'roots':{'archive':str(self.archive)},'image_roots':[str(self.archive)]})
        ident, revision = 'a'*20, 'b'*64
        self.directory = self.cache/ident/revision
        (self.directory/'assets').mkdir(parents=True)
        (self.directory/'diary.pdf').write_bytes(b'%PDF-test-payload')
        (self.directory/'diary.md').write_text('# synthetic diary')
        (self.directory/'body.html').write_text('<p>synthetic diary</p>')
        self.lib.rows=[{'id':ident,'date':'2026-01-01','kind':'archive','label':'日记稿','title':'日记',
                       'excerpt':'测试','draft':False,'ready':True,'supplement':False,'revision':revision}]
        library = self.lib
        class Handler(BaseHTTPRequestHandler):
            def authorized(self):return self.headers.get('X-Test-Owner')=='yes'
            def do_GET(self):library.handle(self,self.path,{})
            def do_HEAD(self):library.handle(self,self.path,{})
            def do_POST(self):library.handle(self,self.path,{})
            def log_message(self,*args):pass
        self.server=ThreadingHTTPServer(('127.0.0.1',0),Handler)
        threading.Thread(target=self.server.serve_forever,daemon=True).start()
        self.addCleanup(self.server.server_close)
        self.addCleanup(self.server.shutdown)
        self.base='http://127.0.0.1:'+str(self.server.server_port)

    def get(self,path,owner=True,method='GET',headers=None):
        r=urllib.request.Request(self.base+path,method=method,headers={**({'X-Test-Owner':'yes'} if owner else {}),**(headers or {})})
        return urllib.request.urlopen(r)

    def test_every_portal_route_requires_owner(self):
        for path in ['/diary/','/diary/api/index','/diary/api/entries/'+'a'*20+'/pdf']:
            with self.assertRaises(urllib.error.HTTPError) as e:self.get(path,False)
            self.assertEqual(e.exception.code,403)

    def test_only_catalogued_files_can_be_downloaded(self):
        for path in ['/diary/../../private.txt','/diary/api/entries/'+'a'*20+'/assets/../../secret','/diary/api/entries/'+'f'*20+'/pdf']:
            with self.assertRaises(urllib.error.HTTPError) as e:self.get(path)
            self.assertEqual(e.exception.code,404)

    def test_pdf_range_requests_and_content_type(self):
        with self.get('/diary/api/entries/'+'a'*20+'/pdf',headers={'Range':'bytes=0-4'}) as r:
            self.assertEqual(r.status,206)
            self.assertEqual(r.read(),b'%PDF-')
            self.assertEqual(r.headers['Content-Type'],'application/pdf')
            self.assertEqual(r.headers['Cache-Control'],'no-store')

    def test_invalid_range_fails_without_file_disclosure(self):
        with self.assertRaises(urllib.error.HTTPError) as e:self.get('/diary/api/entries/'+'a'*20+'/pdf',headers={'Range':'bytes=10000-'})
        self.assertEqual(e.exception.code,416)

    def test_write_requests_are_rejected(self):
        with self.assertRaises(urllib.error.HTTPError) as e:self.get('/diary/api/index',method='POST')
        self.assertEqual(e.exception.code,405)

    def test_api_has_no_private_paths(self):
        with self.get('/diary/api/index') as r:data=r.read().decode()
        self.assertNotIn(str(self.cache),data)
        self.assertNotIn('source_sha',data)
        self.assertEqual(json.loads(data)['entries'][0]['date'],'2026-01-01')

    def test_untrusted_markup_and_external_pictures_are_not_executed(self):
        parser=SafeHTML('/diary/assets/')
        parser.feed('<p onclick="steal()">hello</p><a href="javascript:steal()">bad</a><img src="https://external.invalid/track"><img src="assets/'+'a'*64+'.png">')
        body=''.join(parser.parts)
        self.assertNotIn('onclick',body)
        self.assertNotIn('javascript:',body)
        self.assertNotIn('external.invalid',body)
        self.assertIn('/diary/assets/'+'a'*64+'.png',body)

    def test_discovery_excludes_source_notes_and_out_of_tree_symlinks(self):
        folder=self.archive/'2026/01';folder.mkdir(parents=True)
        (folder/'2026-01-01.md').write_text('# 日记\n\n## 工作记录\n做测试\n## 日记\n记录')
        (folder/'2026-01-01-media-review.md').write_text('private source note')
        secret=self.root/'secret.md';secret.write_text('private')
        (folder/'2026-01-02.md').symlink_to(secret)
        rows=self.lib.discover()
        self.assertEqual([r['date'] for r in rows],['2026-01-01'])

    def test_media_change_invalidates_pdf_receipt(self):
        picture=self.archive/'picture.png';picture.write_bytes(b'old')
        stat=picture.stat();previous={'source_sha':'x','revision':'b'*64,'images':[{'source':str(picture),'bytes':stat.st_size,'mtime_ns':stat.st_mtime_ns}]}
        self.assertTrue(self.lib._current({'id':'a'*20,'source_sha':'x','path':str(self.archive/'entry.md')},previous))
        picture.write_bytes(b'new-picture')
        self.assertFalse(self.lib._current({'id':'a'*20,'source_sha':'x','path':str(self.archive/'entry.md')},previous))

    def test_trusted_published_baseline_requires_matching_text_pdf_and_picture(self):
        source=self.archive/'2026-01-01.md';source.write_text('# synthetic diary')
        source.with_suffix('.pdf').write_bytes(b'%PDF-synthetic')
        picture=self.archive/'pic.png';picture.write_bytes(b'picture')
        def git(*args):return subprocess.run(['git','-C',str(self.archive),*args],check=True,capture_output=True,text=True).stdout.strip()
        git('init');git('config','user.name','Synthetic Test');git('config','user.email','test@example.invalid');git('add','.');git('commit','-m','Validated synthetic baseline')
        self.assertFalse(self.lib.published_baseline_matches(source,[{'source':str(picture)}]))
        self.lib.config['validated_archive_commit']=git('rev-parse','HEAD')
        self.assertTrue(self.lib.published_baseline_matches(source,[{'source':str(picture)}]))
        picture.write_bytes(b'revised picture')
        self.assertFalse(self.lib.published_baseline_matches(source,[{'source':str(picture)}]))


if __name__=='__main__':unittest.main()
