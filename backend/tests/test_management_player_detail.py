"""Player detail/history projections are scoped, paginated and credential-free."""
from pathlib import Path
import sys
import unittest
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from management import Management, ManagementError
from service import Service
from state import Store, Catalog

ROOT = Path(__file__).resolve().parents[2]

class PlayerDetail(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.catalog = Catalog(ROOT/'protocol')

    def setUp(self):
        self.store = Store(Path(':memory:'))
        self.addCleanup(self.store.close)
        self.service = Service(self.store, self.catalog)
        self.manager = Management(self.store,self.service,b'disposable-player-detail-test-token-12345',
                                  [{'id':'owner','role':'owner','enabled':True}])
        self.actor = {'id':'owner','role':'owner'}
        for account in ('detail-one','detail-two'):
            self.store.account(account,account)
            self.service.shop.set_wallet(account,100,0,0)

    def adjust(self, account, index):
        self.manager.command('users/'+account+'/wallet-adjustments',
            {'currency':'crystals','delta':1,'reason':'Disposable scoped history'},
            {'Authorization':'Bearer disposable-player-detail-test-token-12345','X-Management-Actor':'owner',
             'Idempotency-Key':f'detail-request-{index}'})

    def test_last_login_uses_latest_session_without_exposing_credentials(self):
        before=self.manager.read('users/detail-one',{},self.actor)
        self.assertIsNone(before['last_login_at'])
        self.assertIsNone(before['last_avatar_save_at'])
        for stamp,guid in ((500,'1'*32),(300,'2'*32),(900,'3'*32)):
            with patch('state.time.time',return_value=stamp):
                self.store.bind_session('detail-one',guid)
        after=self.manager.read('users/detail-one',{},self.actor)
        self.assertEqual(after['last_login_at'],900)
        self.assertNotIn('guid',after)
        self.assertNotIn('session',after)
        self.assertIsNone(self.manager.read('users/detail-two',{},self.actor)['last_login_at'])

    def test_each_player_history_filters_before_pagination_and_expands_audit(self):
        for index,account in enumerate(('detail-one','detail-two','detail-one')):
            self.adjust(account,index)
        for suffix in ('transactions','audit'):
            first=self.manager.read('users/detail-one/'+suffix,{'limit':'1'},self.actor)
            self.assertEqual(first['total'],2)
            self.assertEqual(first['next_cursor'],'1')
            second=self.manager.read('users/detail-one/'+suffix,{'limit':'1','cursor':'1'},self.actor)
            self.assertIsNone(second['next_cursor'])
            self.assertNotEqual(first['items'],second['items'])
            for row in first['items']+second['items']:
                self.assertEqual(row.get('account_id',row.get('target_id')),'detail-one')
                if suffix=='audit':
                    self.assertIsInstance(row['before'],dict)
                    self.assertNotIn('before_json',row)

    def test_unknown_accounts_and_invalid_cursors_fail_instead_of_leaking_global_history(self):
        self.adjust('detail-two',1)
        for suffix in ('transactions','audit'):
            for account,query,status in [('missing',{},404),('detail-one',{'cursor':'-1'},400),
                                         ('detail-one',{'limit':'0'},400)]:
                with self.subTest(suffix=suffix,account=account),self.assertRaises(ManagementError) as got:
                    self.manager.read('users/'+account+'/'+suffix,query,self.actor)
                self.assertEqual(got.exception.status,status)
            self.assertEqual(self.manager.read('users/detail-one/'+suffix,{},self.actor)['items'],[])

    def test_nonplayer_audit_target_collisions_do_not_become_player_activity(self):
        with self.store.atomic():
            for index,operation in enumerate(('operators.manage','moderation.news','moderation.reports')):
                self.manager._audit(f'collision-{index}','owner','owner',operation,'detail-one',
                                    'Nonplayer target collision',{}, {'fixture':True})
        self.adjust('detail-one',1)
        result=self.manager.read('users/detail-one/audit',{},self.actor)
        self.assertEqual(result['total'],1)
        self.assertEqual(result['items'][0]['operation'],'wallet.adjust')

if __name__=='__main__':
    unittest.main()
