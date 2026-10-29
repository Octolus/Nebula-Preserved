"""Transactions through the public local service; no socket or target required."""
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from service import Service
from state import Catalog, Store


class NotificationIntegrationTests(unittest.TestCase):
    def test_gift_notice_is_atomic_with_debit_and_recipient_ownership(self):
        protocol = Path(__file__).resolve().parents[2]/'protocol'
        with tempfile.TemporaryDirectory() as directory:
            store = Store(Path(directory)/'preservation.sqlite3')
            try:
                service = Service(store, Catalog(protocol))
                store.account('gift-sender', 'Actual Donor')
                store.account('gift-target', 'Actual Recipient')
                guid = 'b'*32
                store.bind_session('gift-sender', guid)
                store.accept_friendship('gift-sender', 'gift-target')
                item = next(row for row in service.catalog.items.values() if row['gender'] == 'MALE')
                service.shop.configure_shop('local-gifts', 0, 'Local Gifts')
                service.shop.configure_offer('gift-offer','wardrobe',item['item_id'],'local-gifts',item['category'],0,
                    'Verified Gift',crystals=25,gender=item['gender'],category=item['category'])
                service.shop.set_wallet('gift-sender', 100)
                request = guid+'#gift-sender#gift-offer#Actual Recipient#25#StandaloneWindows'
                with patch.object(service.notifications,'enqueue_gift',side_effect=OSError('notice storage failed')):
                    with self.assertRaises(OSError): service.dispatch('NPShopGiftItemServlet',request)
                self.assertEqual(service.shop.wallet('gift-sender')['crystals'],100)
                self.assertEqual(store.inventory('gift-target'),[])
                self.assertEqual(store.db.execute('SELECT COUNT(*) FROM shop_owned').fetchone()[0],0)
                self.assertEqual(service.dispatch('NPShopGiftItemServlet',request).split('#')[3],'OK')
                self.assertEqual(service.dispatch('NPShopGiftItemServlet',request).split('#')[3],'ISPURCHASED')
                self.assertEqual(service.shop.wallet('gift-sender')['crystals'],75)
                self.assertEqual(len(store.inventory('gift-target')),1)
                notices = service.notifications.pending('gift-target')
                self.assertEqual(len(notices),1)
                self.assertEqual((notices[0]['source_username'],notices[0]['notification_type'],notices[0]['arguments']),
                    ('Actual Donor',3,'Verified Gift'))
            finally:
                store.close()

    def test_fresh_reward_queues_once_and_notice_failure_rolls_back_grant(self):
        protocol = Path(__file__).resolve().parents[2]/'protocol'
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            store = Store(root/'preservation.sqlite3')
            try:
                service = Service(store, Catalog(protocol))
                store.account('notice-owner', 'Actual Recipient')
                guid = 'a'*32
                store.bind_session('notice-owner', guid)
                items = list({row['item_id']: row for row in service.catalog.items.values()}.values())[:2]
                for index,item in enumerate(items):
                    service.rewards.configure('GenericReward', 'notice-'+str(index), grant_kind='wardrobe',
                        item_id=item['item_id'], gender=item['gender'], category=item['category'])
                request = guid+'#notice-owner#notice-0#StandaloneWindows'
                self.assertEqual(service.dispatch('GenericReward', request).split('#')[-1], 'true')
                self.assertEqual(service.dispatch('GenericReward', request).split('#')[-1], 'false')
                notices = service.notifications.pending('notice-owner')
                self.assertEqual(len(notices), 1)
                self.assertEqual(notices[0]['source_username'], 'Actual Recipient')
                self.assertEqual(notices[0]['notification_type'], 4)
                self.assertEqual(len(store.inventory('notice-owner')), 1)
                with patch.object(service.notifications, 'enqueue_reward', side_effect=OSError('notice storage failed')):
                    with self.assertRaises(OSError):
                        service.dispatch('GenericReward', guid+'#notice-owner#notice-1#StandaloneWindows')
                self.assertEqual(len(store.inventory('notice-owner')), 1)
                self.assertEqual(len(service.notifications.pending('notice-owner')), 1)
                self.assertEqual(store.db.execute("SELECT COUNT(*) FROM local_reward_claims WHERE trigger_key='notice-1'").fetchone()[0], 0)
            finally:
                store.close()
            reopened = Store(root/'preservation.sqlite3')
            try:
                self.assertEqual(len(reopened.inventory('notice-owner')), 1)
                self.assertEqual(reopened.db.execute('SELECT COUNT(*) FROM notification_outbox').fetchone()[0], 1)
            finally:
                reopened.close()


if __name__ == '__main__': unittest.main()

