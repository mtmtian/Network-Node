"""Exercise address drift and interruption recovery without contacting GCP."""
import copy
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'providers'))
from gcp_ip import CloudError, Gcp, Rotation, check
from settings import load_settings
from profile_lock import profile_lock


class FakeGcp:
    def __init__(self, settings):
        self.s = settings
        self.machine = {'id': '123', 'name': 'vm', 'selfLink': 'test/vm', 'status': 'RUNNING',
                        'networkInterfaces': [{'name': 'nic0', 'accessConfigs': [
                            {'name': 'External NAT', 'natIP': '203.0.113.10', 'networkTier': 'PREMIUM'}]}]}
        self.addresses = {'old': {'address': '203.0.113.10', 'status': 'IN_USE',
                                  'users': ['test/vm'], 'networkTier': 'PREMIUM'}}
        self.calls = []
        self.fail_add = False
        self.pending = False
        self.interrupt_add = False

    def vm(self, optional=False):
        return copy.deepcopy(self.machine)

    def address(self, name):
        return copy.deepcopy(self.addresses.get(name))

    def idle(self, vm):
        if self.pending:
            raise ValueError('operation pending')

    def call(self, *args):
        self.calls.append(args)
        resource, action = args[1:3]
        if resource == 'addresses':
            name = args[3]
            if action == 'create':
                self.addresses[name] = {'address': '203.0.113.20', 'status': 'RESERVED',
                                        'users': [], 'networkTier': 'PREMIUM'}
            elif action == 'delete':
                del self.addresses[name]
            return
        nic = self.machine['networkInterfaces'][0]
        if action == 'delete-access-config':
            old_ip = nic['accessConfigs'][0]['natIP']
            nic['accessConfigs'] = []
            for address in self.addresses.values():
                if address['address'] == old_ip:
                    address.update(users=[], status='RESERVED')
        elif action == 'add-access-config':
            ip = args[args.index('--address') + 1]
            if ip == '203.0.113.20' and self.fail_add:
                raise CloudError('simulated failure')
            if ip == '203.0.113.20' and self.interrupt_add:
                self.pending = True
                raise CloudError('uncertain result')
            nic['accessConfigs'] = [{'name': 'External NAT', 'natIP': ip, 'networkTier': 'PREMIUM'}]
            for address in self.addresses.values():
                if address['address'] == ip:
                    address.update(users=['test/vm'], status='IN_USE')


class GcpIpTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.state = Path(self.temp.name)
        (self.state / 'deploy.conf').write_text(
            '# keep comment\nGCP_ACCOUNT=test@example.com\nPROJECT_ID=test\nZONE=us-west1-a\n'
            'REGION=us-west1\nINSTANCE_NAME=vm\nIP_NAME=old\nREALITY_PORT=443\nDEVICES=mac\n')
        (self.state / '.secrets.env').write_text('STATIC_IP=203.0.113.10\nDO_NOT_CHANGE=test-secret\n')
        self.client = FakeGcp(load_settings(self.state))
        self.rendered = []

    def rotation(self, **kwargs):
        return Rotation(self.state, client=self.client, probe=kwargs.get('probe', lambda *_: None),
                        renderer=kwargs.get('renderer', lambda state: self.rendered.append(load_settings(state)['STATIC_IP'])))

    def ip(self):
        return load_settings(self.state)['STATIC_IP']

    def test_existing_vm_drift_never_overwrites_local_ip(self):
        self.client.addresses['old']['address'] = '203.0.113.20'
        with patch('gcp_ip.Gcp', return_value=self.client):
            for mode in ({'optional': True}, {'persist': True}):
                with self.assertRaisesRegex(ValueError, '不一致'):
                    check(self.state, **mode)
        self.assertEqual(self.ip(), '203.0.113.10')
        self.assertEqual(self.client.calls, [])

    def test_plan_has_no_cloud_or_client_writes(self):
        self.rotation().rotate()
        self.assertEqual(self.client.calls, [])
        self.assertEqual(self.rendered, [])
        self.assertFalse((self.state / 'ip-rotation.json').exists())

    def test_success_commits_binding_and_preserves_old_address(self):
        observed = []
        def probe(ip, port):
            observed.append((ip, port, self.ip()))
        self.rotation(probe=probe).rotate(apply=True)
        self.assertEqual(observed, [('203.0.113.20', 443, '203.0.113.10')])
        self.assertEqual(self.ip(), '203.0.113.20')
        self.assertNotEqual(load_settings(self.state)['IP_NAME'], 'old')
        self.assertEqual(self.client.addresses['old']['users'], [])
        self.assertEqual(load_settings(self.state)['DO_NOT_CHANGE'], 'test-secret')
        self.assertIn('# keep comment', (self.state / 'deploy.conf').read_text())
        self.assertEqual((self.state / 'ip-rotation.json').stat().st_mode & 0o777, 0o600)
        self.rotation().rollback(apply=True)
        self.assertEqual(self.ip(), '203.0.113.10')
        self.rotation().finalize(apply=True)
        self.assertEqual(list(self.client.addresses), ['old'])

    def test_add_failure_rebinds_old_ip(self):
        self.client.fail_add = True
        with self.assertRaisesRegex(ValueError, '已恢复'):
            self.rotation().rotate(apply=True)
        self.assertEqual(self.ip(), '203.0.113.10')
        self.assertEqual(self.client.vm()['networkInterfaces'][0]['accessConfigs'][0]['natIP'], self.ip())

    def test_unreachable_new_ip_is_not_published(self):
        def failed(*_):
            raise ValueError('TCP unreachable')
        with self.assertRaisesRegex(ValueError, '已恢复'):
            self.rotation(probe=failed).rotate(apply=True)
        self.assertNotIn('203.0.113.20', self.rendered)
        self.assertEqual(self.ip(), '203.0.113.10')

    def test_renderer_failure_restores_old_binding_and_outputs(self):
        def renderer(state):
            if load_settings(state)['STATIC_IP'] == '203.0.113.20':
                raise ValueError('disk write failed')
            self.rendered.append(self.ip())
        with self.assertRaisesRegex(ValueError, '已恢复'):
            self.rotation(renderer=renderer).rotate(apply=True)
        self.assertEqual(self.ip(), '203.0.113.10')
        self.assertEqual(load_settings(self.state)['IP_NAME'], 'old')

    def test_uncertain_pending_operation_waits_for_explicit_recovery(self):
        self.client.interrupt_add = True
        with self.assertRaisesRegex(ValueError, '自动恢复也未完成'):
            self.rotation().rotate(apply=True)
        self.assertTrue((self.state / 'ip-rotation.json').exists())
        with self.assertRaisesRegex(ValueError, 'operation pending'):
            self.rotation().rollback(apply=True)
        self.client.pending = False
        self.rotation().rollback(apply=True)
        self.assertEqual(self.ip(), '203.0.113.10')

    def test_external_reassignment_and_rebuilt_vm_are_not_overwritten(self):
        self.rotation().rotate(apply=True)
        self.client.machine['id'] = 'recreated'
        with self.assertRaisesRegex(ValueError, '重建'):
            self.rotation().rollback(apply=True)
        self.client.machine['id'] = '123'
        self.client.machine['networkInterfaces'][0]['accessConfigs'][0]['natIP'] = '203.0.113.99'
        with self.assertRaisesRegex(ValueError, '第三方'):
            self.rotation().rollback(apply=True)

    def test_second_rotation_requires_finalizing_first(self):
        self.rotation().rotate(apply=True)
        with self.assertRaisesRegex(ValueError, '已有'):
            self.rotation().rotate(apply=True)
        self.rotation().finalize(apply=True)
        self.assertNotIn('old', self.client.addresses)
        self.assertFalse((self.state / 'ip-rotation.json').exists())

    def test_cloud_failure_is_not_treated_as_resource_absence(self):
        with patch('gcp_ip.subprocess.run', return_value=subprocess.CompletedProcess([], 1, '', 'secret-value')), patch('gcp_ip.time.sleep'):
            with self.assertRaises(CloudError) as failure:
                Gcp(load_settings(self.state)).vm(optional=True)
        self.assertNotIn('secret-value', str(failure.exception))

    def test_profile_lock_excludes_concurrent_operations(self):
        with profile_lock(self.state):
            with self.assertRaisesRegex(ValueError, '正在'):
                with profile_lock(self.state):
                    self.fail('lock should reject concurrent operation')


if __name__ == '__main__':
    unittest.main()
