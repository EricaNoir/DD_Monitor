import unittest
from unittest.mock import patch
from studio.services import BiliAPI


class FollowingTests(unittest.TestCase):
    def setUp(self):
        self.api = BiliAPI({'SESSDATA': 'test-only'})
        self.accounts = [{'mid': 1, 'uname': '甲', 'face': '//i0.hdslb.com/a.png'},
                         {'mid': 2, 'uname': '乙', 'face': ''}]

    def test_pagination_and_batch_room_mapping_include_accounts_without_rooms(self):
        with patch.object(self.api, 'get', side_effect=[{'isLogin': True,'mid':99},
                {'list':self.accounts,'total':641}, {'1':{'room_id':88,'live_status':1,'title':'直播'}}]) as get:
            data = self.api.followings(page=2)
        self.assertTrue(data['more'])
        self.assertEqual(data['total'], 641)
        self.assertEqual(get.call_args_list[1].kwargs['pn'], 2)
        self.assertEqual(get.call_args_list[2].kwargs['uids[]'], [1,2])
        self.assertEqual(data['rooms'][0]['id'], '88')
        self.assertTrue(data['rooms'][0]['live'])
        self.assertEqual(data['rooms'][1]['id'], '')
        self.assertTrue(all(r['following'] for r in data['rooms']))

    def test_search_uses_entire_followings_search_endpoint(self):
        with patch.object(self.api, 'get', side_effect=[{'isLogin': True,'mid':99},
                {'list':[], 'total':0}]) as get:
            data = self.api.followings('昵称')
        self.assertTrue(get.call_args_list[1].args[0].endswith('/followings/search'))
        self.assertEqual(get.call_args_list[1].kwargs['name'], '昵称')
        self.assertFalse(data['more'])

    def test_expired_login_and_room_failure_are_not_empty_following_lists(self):
        with patch.object(self.api,'get',return_value={'isLogin':False}), self.assertRaisesRegex(ValueError,'登录'):
            self.api.followings()
        with patch.object(self.api,'get',side_effect=[{'isLogin':True,'mid':99},
                {'list':self.accounts,'total':2},ValueError('unavailable')]):
            data = self.api.followings()
        self.assertEqual(len(data['rooms']),2)
        self.assertTrue(data['rooms_unavailable'])
        self.assertFalse(data['rooms'][0]['room_known'])


if __name__ == '__main__':
    unittest.main()
