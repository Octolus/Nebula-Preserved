"""Actual successor HousingStore/Service; disposable SQLite, no sockets/processes."""
from pathlib import Path
import asyncio,copy,json,sqlite3,sys,tempfile,time,unittest
BASE=Path(__file__).resolve().parents[2]
sys.path[:0]=[str(BASE/'backend'),str(BASE/'tools')]
from housing import HousingStore,HOUSING_FIELDS
from housing_atomic import ACK_SECONDS,SAVE_SECONDS,HousingSavePending,dispatch_housing_atomic
from state import Store,Catalog
from service import Service
from wire import ProtocolError
from avatar_entry_codec import encode_entry_fields

class Atomic(unittest.TestCase):
 def setUp(self):
  self.temp=tempfile.TemporaryDirectory();self.path=Path(self.temp.name)/'state.sqlite3';self.store=Store(self.path)
  for account,guid in [('housing-owner','owner-guid'),('housing-visitor','visitor-guid')]:self.store.account(account,account);self.store.bind_session(account,guid)
  self.housing=HousingStore(self.store,BASE/'protocol');self.housing.bind_space('test-apartment','Home','housing-owner')
  self.now=1000.;self.housing.atomic_saves.clock=lambda:self.now
  for guid in ('owner-guid','visitor-guid'):self.allocate(guid)
  self.item=next(k for k,v in self.housing.catalog.items() if v['behaviour']=='ground' and v['placement_cost']==1)
  self.housing.grant_item('housing-owner',self.item)
 def allocate(self,guid,instance='test-apartment',scene='Home'):
  with self.store.db:self.store.db.execute('INSERT OR REPLACE INTO allocations VALUES(?,?,?,?,?,?)',(guid,instance,scene,'127.0.0.1',28000,time.time()))
 def tearDown(self):self.store.close();self.temp.cleanup()
 def parts(self,x=1.,tail=2.,n=101):
  data=self.housing.empty_layout('Home');data.update(aidasset=[self.item]*n,aidasset_tx=[x]*min(n,100)+[tail]*max(0,n-100),aidasset_ty=[0.]*n,aidasset_tz=[0.]*n,aidasset_r=[90.]*n,atablename=None)
  result=[]
  for part in ('0','1'):
   value=copy.deepcopy(data)
   for i in range(n):
    if (i<100)!=(part=='0'):
     value['aidasset'][i]='null'
     for key in ('aidasset_tx','aidasset_ty','aidasset_tz','aidasset_r'):value[key][i]=0.
   for key in ('aidasset_tx','aidasset_ty','aidasset_tz','aidasset_r'):value[key]=[str(v) for v in value[key]]
   result.append(encode_entry_fields(value,HOUSING_FIELDS))
  return result
 def send(self,part,parts=None,guid='owner-guid'):return self.housing.save_part(guid,(parts or self.parts())[int(part)],part)
 def layout(self):
  row=self.store.db.execute('SELECT layout_json,updated_at FROM housing_layouts WHERE instance_id=?',('test-apartment',)).fetchone()
  return tuple(row) if row else None
 def complete(self,parts=None):self.send('0',parts);self.send('1',parts)
 def next_save(self):self.now+=ACK_SECONDS+0.1
 def test_atomic_partial_never_replaces_committed_half(self):
  self.complete();before=self.layout();self.next_save();self.send('0',self.parts(8.,9.));self.assertEqual(before,self.layout())
  self.assertEqual(self.housing.load(self.housing.binding('test-apartment'))['aidasset_tx'][-1],2.)
 def test_two_parts_commit_whole_once(self):
  self.send('0');self.assertIsNone(self.layout());self.send('1');value=json.loads(self.layout()[0]);self.assertEqual(value['aidasset_tx'],[1.]*100+[2.]);self.assertEqual(self.store.db.execute('SELECT count(*) FROM housing_save_receipts').fetchone()[0],1)
 def test_reordered_part1_waits_for_part0_and_current_receipt(self):
  with self.assertRaises(HousingSavePending) as got:self.send('1')
  p=got.exception;self.assertFalse(p.coordinator.ready(p.ticket));self.assertIsNone(self.layout());self.send('0');self.assertTrue(p.coordinator.ready(p.ticket))
 def test_restart_partial_stays_partial_then_original_counterpart_completes(self):
  self.send('0');self.store.close();self.store=Store(self.path);self.housing=HousingStore(self.store,BASE/'protocol');self.housing.atomic_saves.clock=lambda:self.now
  self.assertIsNone(self.layout());self.send('1');self.assertEqual(json.loads(self.layout()[0])['aidasset_tx'][-1],2.)
 def test_restart_preserves_last_complete_layout_and_grants(self):
  self.complete();before=self.layout();self.store.close();self.store=Store(self.path);self.housing=HousingStore(self.store,BASE/'protocol');self.assertEqual(before,self.layout());self.assertEqual([x['item_id'] for x in self.housing.inventory('housing-owner')],[self.item]);self.assertEqual(self.housing.personal_spaces('housing-owner'),['Home'])
 def test_expiry_quarantines_without_promoting_partial(self):
  self.complete();before=self.layout();self.next_save();parts=self.parts(8.,9.);self.send('0',parts);self.now+=SAVE_SECONDS+1
  with self.assertRaises(ProtocolError):self.send('1',parts)
  self.assertEqual(before,self.layout());self.assertEqual(self.store.db.execute('SELECT state FROM housing_save_stages').fetchone()[0],'blocked')
 def test_new_current_guid_recovers_expired_lane(self):
  self.send('0');self.now+=SAVE_SECONDS+1
  with self.assertRaises(ProtocolError):self.send('1')
  self.store.bind_session('housing-owner','new-owner-guid');self.allocate('new-owner-guid');self.send('0',guid='new-owner-guid');self.send('1',guid='new-owner-guid');self.assertIsNotNone(self.layout())
 def test_conflicting_same_part_cannot_overwrite_staged_part(self):
  self.send('0')
  with self.assertRaises(ProtocolError):self.send('0',self.parts(8.,9.))
  with self.assertRaises(ProtocolError):self.send('1')
  self.assertIsNone(self.layout())
 def test_conflicting_shared_ground_length_rejected(self):
  self.send('0')
  with self.assertRaises(ProtocolError):self.send('1',self.parts(n=102))
  self.assertIsNone(self.layout())
 def test_conflicting_repeated_wall_metadata_rejected(self):
  self.send('0');from avatar_entry_codec import decode_entry_fields
  value=decode_entry_fields(self.parts()[1],HOUSING_FIELDS);value['aidassetWallSlot']=[0];value['aidassetWall']=[next(k for k,v in self.housing.catalog.items() if v['behaviour']=='wall')]
  self.housing.grant_item('housing-owner',value['aidassetWall'][0])
  for key in ('aidasset_tx','aidasset_ty','aidasset_tz','aidasset_r'):value[key]=[str(v) for v in value[key]]
  with self.assertRaises(ProtocolError):self.housing.save_part('owner-guid',encode_entry_fields(value,HOUSING_FIELDS),'1')
  self.assertIsNone(self.layout())
 def test_identical_open_and_ack_duplicates_are_idempotent(self):
  self.send('0');self.send('0');self.send('1');before=self.layout();self.send('1');self.send('0');self.assertEqual(before,self.layout());self.assertEqual(self.store.db.execute('SELECT count(*) FROM housing_save_receipts').fetchone()[0],1)
 def test_consecutive_original_saves_same_guid_after_bounded_ack_window(self):
  self.complete();self.next_save();self.complete(self.parts(8.,9.));self.assertEqual(json.loads(self.layout()[0])['aidasset_tx'],[8.]*100+[9.]);self.assertEqual(self.store.db.execute('SELECT count(*) FROM housing_save_receipts').fetchone()[0],2)
 def test_consecutive_save_with_unchanged_first_half_and_reversed_order(self):
  self.complete();self.next_save();parts=self.parts(1.,9.)
  with self.assertRaises(HousingSavePending):self.send('1',parts)
  self.send('0',parts);self.assertEqual(json.loads(self.layout()[0])['aidasset_tx'][-1],9.)
 def test_differing_during_ack_window_rejects_temporarily_not_forever(self):
  self.complete();before=self.layout()
  with self.assertRaises(ProtocolError):self.send('0',self.parts(8.,9.))
  self.assertEqual(before,self.layout());self.next_save();self.complete(self.parts(8.,9.));self.assertNotEqual(before,self.layout())
 def test_visitor_rejected_without_any_state_mutation(self):
  before=list(self.store.db.iterdump())
  with self.assertRaises(ProtocolError):self.send('0',guid='visitor-guid')
  self.assertEqual(before,list(self.store.db.iterdump()))
 def test_stale_owner_guid_cannot_complete_pending_save(self):
  self.send('0');before=self.layout();self.store.bind_session('housing-owner','new-owner-guid')
  with self.assertRaises(ProtocolError):self.send('1')
  self.assertEqual(before,self.layout())
 def test_current_allocation_change_rejects_old_scene(self):
  self.send('0');self.allocate('owner-guid','other-instance','Nexus')
  with self.assertRaises(ProtocolError):self.send('1')
  self.assertIsNone(self.layout())
 def test_entitlement_revocation_before_commit_cannot_promote(self):
  self.send('0')
  with self.store.db:self.store.db.execute('DELETE FROM housing_entitlements')
  with self.assertRaises(ProtocolError):self.send('1')
  self.assertIsNone(self.layout())
 def test_atomic_rollback_on_durable_failure(self):
  self.send('0')
  self.store.db.execute("CREATE TRIGGER fail_receipt BEFORE INSERT ON housing_save_receipts BEGIN SELECT RAISE(ABORT,'failure'); END");self.store.db.commit()
  with self.assertRaises(sqlite3.IntegrityError):self.send('1')
  self.assertIsNone(self.layout());row=self.store.db.execute('SELECT part1_json FROM housing_save_stages').fetchone();self.assertIsNone(row[0])
 def test_two_database_connections_share_one_lane(self):
  self.send('0');other=Store(self.path)
  try:
   housing=HousingStore(other,BASE/'protocol');housing.atomic_saves.clock=lambda:self.now
   housing.save_part('owner-guid',self.parts()[1],'1');self.assertIsNotNone(self.layout())
  finally:other.close()
 def test_delayed_duplicate_after_ack_window_is_staged_not_promoted(self):
  self.complete();before=self.layout();self.next_save()
  with self.assertRaises(HousingSavePending) as got:self.send('1')
  self.assertEqual(before,self.layout());self.now+=SAVE_SECONDS+1
  with self.assertRaises(ProtocolError):got.exception.coordinator.ready(got.exception.ticket)
  self.assertEqual(before,self.layout())
 def test_empty_layout_requires_both_original_parts(self):
  parts=self.parts(n=0);self.send('0',parts);self.assertIsNone(self.layout());self.send('1',parts);self.assertEqual(json.loads(self.layout()[0])['aidasset'],[])
 def test_async_actual_service_part1_ack_only_after_whole_commit(self):
  service=Service(self.store,Catalog(BASE/'protocol'));service.housing.atomic_saves.clock=lambda:self.now;parts=self.parts()
  def message(part):return '#'.join(('owner-guid','housing-owner',parts[int(part)],part,'StandaloneWindows'))
  async def run():
   task=asyncio.create_task(dispatch_housing_atomic(service,'HousingSavePresetServletParts',message('1')));await asyncio.sleep(.01)
   self.assertFalse(task.done());self.assertIsNone(self.layout())
   answer=await dispatch_housing_atomic(service,'HousingSavePresetServletParts',message('0'));self.assertEqual(answer,'true#owner-guid#housing-owner#true')
   self.assertEqual(await task,'true#owner-guid#housing-owner#true');self.assertIsNotNone(self.layout())
  asyncio.run(run())
 def test_async_stale_guid_does_not_get_success(self):
  service=Service(self.store,Catalog(BASE/'protocol'));parts=self.parts()
  async def run():
   task=asyncio.create_task(dispatch_housing_atomic(service,'HousingSavePresetServletParts','#'.join(('owner-guid','housing-owner',parts[1],'1','StandaloneWindows'))));await asyncio.sleep(.01)
   self.store.bind_session('housing-owner','new-owner-guid')
   with self.assertRaises(ProtocolError):await task
  asyncio.run(run());self.assertIsNone(self.layout())
if __name__=='__main__':unittest.main(verbosity=2)
