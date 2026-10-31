"""Offline checks of prepared host hardening, capacity and policy variables; nothing is applied."""
import importlib.util
from pathlib import Path
import unittest

try:
    import yaml
except ImportError:  # PyYAML is optional for these offline checks.
    yaml = None

ROOT = Path(__file__).resolve().parents[3]
ANSIBLE = ROOT / 'deployment/ansible'
SPEC = importlib.util.spec_from_file_location('policy_installer', ROOT / 'deployment/bootstrap/deploy.py')
DEPLOY = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(DEPLOY)


def tasks(items):
    for task in items:
        yield task
        for key in ('block', 'rescue', 'always'):
            yield from tasks(task.get(key, []))


@unittest.skipIf(yaml is None, 'PyYAML required')
class HostHardening(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.play = yaml.safe_load((ANSIBLE / 'site.yaml').read_text(encoding='utf-8'))[0]
        cls.tasks = {task['name']: task for task in tasks(cls.play['tasks'])}

    def test_ssh_dropin_is_guarded_validated_and_reloaded_by_handler(self):
        ssh = self.tasks['Harden SSH login (key-only, root by key only)']
        self.assertEqual(ssh['when'], 'nebula_ssh_hardening | default(true) | bool')
        names = [task['name'] for task in ssh['block']]
        guard = names.index('Never disable passwords without an authorized key (lockout guard)')
        dropin = names.index('Install SSH hardening drop-in (00- so it wins over cloud-image 50-* settings)')
        validate = names.index('Validate the complete sshd configuration before any reload')
        self.assertLess(guard, dropin)
        self.assertLess(dropin, validate)
        copy = ssh['block'][dropin]['ansible.builtin.copy']
        self.assertEqual(copy['dest'], '/etc/ssh/sshd_config.d/00-nebula-hardening.conf')
        for line in ('PasswordAuthentication no', 'PermitRootLogin prohibit-password'):
            self.assertIn(line, copy['content'])
        self.assertEqual(ssh['block'][dropin]['notify'], 'Reload sshd')
        self.assertEqual(ssh['block'][validate]['ansible.builtin.command'], '/usr/sbin/sshd -t')
        self.assertIn('/root/.ssh/authorized_keys', ssh['block'][0]['loop'])
        rescue = [task['name'] for task in ssh['rescue']]
        self.assertEqual(rescue[0], 'Remove an sshd drop-in that failed validation')
        handlers = {handler['name']: handler for handler in self.play['handlers']}
        self.assertEqual(handlers['Reload sshd']['ansible.builtin.systemd_service']['state'], 'reloaded')

    def test_fail2ban_default_on_and_ufw_opt_in_with_ssh_allowed_first(self):
        self.assertEqual(self.tasks['Protect SSH with fail2ban']['when'], 'nebula_fail2ban | default(true) | bool')
        jail = self.tasks['Configure the sshd jail']['ansible.builtin.copy']['content']
        self.assertIn('[sshd]', jail)
        self.assertIn('enabled = true', jail)
        ufw = self.tasks['Enable host firewall (opt-in; Docker-published ports bypass ufw)']
        self.assertEqual(ufw['when'], 'nebula_ufw | default(false) | bool')
        names = [task['name'] for task in ufw['block']]
        self.assertLess(names.index('Allow SSH and the public service ports before enabling'),
                        names.index('Default-deny other inbound host traffic and enable ufw'))
        self.assertIn('[22, 80, 443, 8443, 8444]', ufw['block'][1]['loop'])

    def test_backups_run_before_restart_and_offsite_hook_is_disabled_by_default(self):
        order = [task['name'] for task in self.play['tasks']]
        self.assertLess(order.index('Take a verified pre-deploy backup (retained separately from daily sets)'),
                        order.index('Start or refresh complete stack'))
        self.assertEqual(self.tasks['Install optional off-host backup hook']['when'],
                         "nebula_backup_offsite_command | default('') | length > 0")
        self.assertEqual(self.tasks['Remove disabled off-host backup hook']['ansible.builtin.file']['state'], 'absent')

    def test_shipped_capacity_defaults_and_scaled_memory(self):
        assertions = self.tasks['Validate platform and reviewed pins']['ansible.builtin.assert']['that']
        self.assertIn('(nebula_max_processes | default(4) | int) in range(1, 33)', assertions)
        compose = (ANSIBLE / 'templates/compose.host.yaml.j2').read_text(encoding='utf-8')
        self.assertIn('default(768 + 256 * (nebula_max_processes | default(4) | int))', compose)
        env = (ANSIBLE / 'templates/runtime.env.j2').read_text(encoding='utf-8')
        for name in ('NEBULA_PUBLIC_WORLD_IDLE_SECONDS', 'NEBULA_STARTER_CRYSTALS', 'NEBULA_STARTER_NP',
                     'NEBULA_STARTER_APARTMENTS',
                     'NEBULA_ENROLLMENT_MAX_ACCOUNTS', 'NEBULA_PROTECTED_ACCOUNTS', 'NEBULA_PROTECT_STAFF_ACCOUNTS'):
            self.assertIn(name + '=', env)
        example = yaml.safe_load((ANSIBLE / 'vars.example.yaml').read_text(encoding='utf-8'))
        self.assertEqual(example['nebula_starter_apartments'], ['Home', 'CliffApartment', 'LakeApartment'])
        self.assertEqual((example['nebula_max_processes'], example['nebula_ufw'], example['nebula_ssh_hardening'],
                          example['nebula_backup_offsite_command']), (4, False, True, ''))


class InstallerPolicy(unittest.TestCase):
    def test_policy_values_default_to_four_worlds_and_validate_options(self):
        self.assertEqual(DEPLOY.policy_values(None), {'nebula_max_processes': 4})
        values = DEPLOY.policy_values({'max_processes': 3, 'starter_crystals': 500, 'starter_np': None,
                                       'protected_accounts': ['76561190000000991'], 'ufw': True,
                                       'ssh_hardening': False})
        self.assertEqual(values, {'nebula_max_processes': 3, 'nebula_starter_crystals': 500,
                                  'nebula_protected_accounts': ['76561190000000991'], 'nebula_ufw': True,
                                  'nebula_ssh_hardening': False})
        for options in ({'max_processes': 33}, {'starter_np': -1}, {'protected_accounts': ['me']},
                        {'unknown_option': 1}):
            with self.subTest(options=options), self.assertRaises(ValueError):
                DEPLOY.policy_values(options)


if __name__ == '__main__':
    unittest.main()
