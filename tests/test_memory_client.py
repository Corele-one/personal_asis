import unittest
from urllib.error import URLError
from personal_asis.memory_client import MemoryClient,NoRedirect


class MemoryClientTests(unittest.TestCase):
    def test_offline_write_explicitly_unknown_and_never_retried(self):
        class Offline:
            calls=0
            def open(self,*args,**kwargs):
                self.calls+=1;raise URLError('synthetic_unavailable')
        offline=Offline();client=MemoryClient('synthetic',opener=offline)
        result=client.call('capture',{'synthetic':True})
        self.assertFalse(result['available'])
        self.assertTrue(result['mutation_result_unknown'])
        self.assertEqual(offline.calls,1)

    def test_private_authorization_cannot_follow_redirect_to_new_destination(self):
        with self.assertRaises(URLError):NoRedirect().redirect_request(None,None,None,None,None,None)
