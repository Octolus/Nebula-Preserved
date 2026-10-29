"""Offline companion/locomotion contracts. Socket creation is forbidden."""
import copy
import json
from pathlib import Path
import socket
import sys
import tempfile
import unittest
from unittest.mock import patch

BACKEND=Path(__file__).resolve().parents[1]
ROOT=BACKEND.parent
sys.path.insert(0,str(BACKEND))

from resources import ResourceCatalog,ResourceEntitlements,collection_response
from state import Store
from wire import ProtocolError,Request,json_field


def native_consumer_tokens(response,guid):
    """Independent implementation of the two native acceptance/list branches."""
    tokens=response.split('#')
    if len(tokens)<2 or tokens[0]!='true' or tokens[1]!=guid:
        raise ValueError('Native acceptance failed')
    return [value for value in tokens[2:] if value!='']


class ResourceContracts(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.catalog=ResourceCatalog(ROOT/'protocol')
        cls.document=json.loads((ROOT/'protocol/resource-entitlements.json').read_text(encoding='utf-8'))
        cls.scratch=(Path(tempfile.gettempdir()) / "nebula-preserved-tests")/'work/offline-resource-tests'
        cls.scratch.mkdir(parents=True,exist_ok=True)

    def setUp(self):
        self.no_network=patch.object(socket,'socket',side_effect=AssertionError('No network in static resource checks'))
        self.no_network.start()
        self.temp=tempfile.TemporaryDirectory(dir=self.scratch)
        self.path=Path(self.temp.name)
        self.store=Store(self.path/'state.sqlite3')
        self.store.account('resource-account-a')
        self.store.account('resource-account-b')
        self.store.bind_session('resource-account-a','resource-guid-a')
        self.store.bind_session('resource-account-b','resource-guid-b')
        self.resources=ResourceEntitlements(self.store,self.catalog)

    def tearDown(self):
        self.store.close()
        self.temp.cleanup()
        self.no_network.stop()

    def item(self,kind):return self.catalog.list(kind)[0]['item_id']

    def test_exact_catalog_identity_and_conflicting_thumbnail(self):
        self.assertEqual(self.document['summary']['canonical_items'],328)
        self.assertEqual(len(self.catalog.list('companions')),219)
        self.assertEqual(len(self.catalog.list('locomotions')),108)
        for row in self.catalog.list():
            prefix='02' if row['kind']=='companions' else '03'
            self.assertEqual(row['bundle'],prefix+'/'+row['item_id'].lower())
            self.assertTrue(row['asset_path'].endswith('/'+row['item_id']+'/'+row['item_id']+'.prefab'))
        for kind,item_id in [('companions','fabricated-id'),('locomotions','BetLh1pHAn7b3I7u0ofpb3IOaS46It4S'),
                             ('locomotions','RRYfEeOcrt3MS0jtdiNvV02cnUKK630W')]:
            with self.assertRaises(ProtocolError):self.catalog.resolve(kind,item_id)

    def test_no_default_grants_and_exact_empty_dto(self):
        for kind in ('companions','locomotions'):
            response=self.resources.response('resource-account-a','resource-guid-a',kind)
            self.assertEqual(response,'true#resource-guid-a')
            self.assertEqual(native_consumer_tokens(response,'resource-guid-a'),[])
        self.assertEqual(native_consumer_tokens('true#resource-guid-a##','resource-guid-a'),[])

    def test_canonical_ids_only_and_regrant_label_override(self):
        item_id=self.item('companions')
        first=self.resources.grant('resource-account-a','companions',item_id,'Local name')
        self.resources.grant('resource-account-a','companions',item_id)
        self.assertEqual(self.resources.list('resource-account-a')[0]['display_name'],'Local name')
        second=self.resources.grant('resource-account-a','companions',item_id,'Updated local label')
        self.assertEqual(second['granted_at'],first['granted_at'])
        self.assertEqual(second['display_name'],'Updated local label')
        self.assertEqual(len(self.resources.list('resource-account-a')),1)
        with self.assertRaises(ProtocolError):self.resources.grant('resource-account-a','companions',item_id.lower())
        with self.assertRaises(ProtocolError):self.resources.grant('resource-account-a','locomotions',item_id)

    def test_per_account_lists_and_native_response_tokens(self):
        pet=self.item('companions')
        locomotion=self.item('locomotions')
        self.resources.grant('resource-account-a','companions',pet,'Display # name')
        self.resources.grant('resource-account-a','locomotions',locomotion)
        for kind,expected in [('companions',pet),('locomotions',locomotion)]:
            reply=self.resources.response('resource-account-a','resource-guid-a',kind)
            self.assertEqual(reply,'true#resource-guid-a#'+expected)
            self.assertEqual(native_consumer_tokens(reply,'resource-guid-a'),[expected])
        self.assertEqual(self.resources.list('resource-account-b'),[])
        with self.assertRaises(ProtocolError):self.resources.response('resource-account-a','resource-guid-b','companions')
        with self.assertRaises(ProtocolError):collection_response('guid',['bad#id'])

    def test_persistence_and_purchase_parallel_names(self):
        pet=self.item('companions')
        locomotion=self.item('locomotions')
        self.resources.grant('resource-account-a','companions',pet,'Name # with separator')
        self.resources.grant('resource-account-a','locomotions',locomotion)
        self.store.close()
        self.store=Store(self.path/'state.sqlite3')
        self.resources=ResourceEntitlements(self.store,self.catalog)
        fields=self.resources.purchase_fields('resource-account-a')
        self.assertEqual(fields['companions'],[pet])
        self.assertEqual(fields['companionsName'],['Name # with separator'])
        self.assertEqual(fields['locomotions'],[locomotion])
        self.assertEqual(fields['locomotionsName'],[locomotion])
        self.assertNotIn('#',json_field(fields))
        self.assertEqual(json.loads(json_field(fields)),fields)

    def test_reject_conflicting_catalog_mapping(self):
        altered=copy.deepcopy(self.document)
        row=copy.deepcopy(altered['items'][0])
        altered['items'].append(row)
        (self.path/'resource-entitlements.json').write_text(json.dumps(altered),encoding='utf-8')
        source=ResourceCatalog(self.path)
        with self.assertRaises(ProtocolError):source.resolve(row['kind'],row['item_id'])

    def test_client_crypto_platform_field_remains_required(self):
        # AES.Encrypt6a32c0 appends this platform name before encryption even
        # when the direct coroutine's logical input contains only GUID#PS4ID.
        request=Request.parse('resource-guid-a#resource-account-a#StandaloneWindows')
        self.assertEqual(request.fields,('resource-guid-a','resource-account-a'))
        self.assertEqual(request.platform,'StandaloneWindows')
        with self.assertRaises(ProtocolError):Request.parse('resource-guid-a#resource-account-a')


if __name__=='__main__':unittest.main()

