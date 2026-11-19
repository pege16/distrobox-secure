#!/usr/bin/env python3
"""Pure validation tests; no Podman daemon or image required."""
import importlib.util
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

MODULE = Path(__file__).with_name('distrobox-secure-runtime.py')
spec = importlib.util.spec_from_file_location('secure_runtime', MODULE)
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)


class RuntimeTests(unittest.TestCase):
    def test_no_grants(self):
        with TemporaryDirectory() as home:
            with patch.object(Path, 'home', return_value=Path(home)):
                network, mounts = mod.grants('example', Path(home) / 'managed', '/home/node')
                self.assertEqual((network, mounts), ('none', []))

    def test_reject_mount_inside_managed_home(self):
        with TemporaryDirectory() as home:
            conf = Path(home) / '.config/distrobox-secure/permissions.conf'
            conf.parent.mkdir(parents=True)
            src = Path(home) / 'src'
            src.mkdir()
            conf.write_text(f'example:mount:{src}:/home/node/.config/opencode\n')
            with patch.object(Path, 'home', return_value=Path(home)):
                with self.assertRaises(SystemExit):
                    mod.grants('example', Path(home) / 'managed', '/home/node')

    def test_grant_workspace_and_network(self):
        with TemporaryDirectory() as home:
            src = Path(home) / 'src'
            src.mkdir()
            conf = Path(home) / '.config/distrobox-secure/permissions.conf'
            conf.parent.mkdir(parents=True)
            conf.write_text(f'example:network:bridge\nexample:mount:{src}:/workspace/src:ro\n')
            with patch.object(Path, 'home', return_value=Path(home)):
                network, mounts = mod.grants('example', Path(home) / 'managed', '/home/node')
                self.assertEqual(network, 'bridge')
                self.assertEqual(mounts, [(str(src), '/workspace/src', 'ro')])

    def test_reject_root_image(self):
        from subprocess import CompletedProcess
        image = '[{"Config":{"User":"","Env":["HOME=/root"]}}]'
        with patch.object(mod, 'run', return_value=CompletedProcess([], 0, stdout=image)):
            with self.assertRaises(SystemExit):
                mod.image_identity('example:latest', {})

    def test_profile_parsing(self):
        with TemporaryDirectory() as home:
            conf = Path(home) / '.config/distrobox-secure/containers/example.conf'
            conf.parent.mkdir(parents=True)
            conf.write_text('user=developer\nhome=/home/developer\nshell=/bin/bash\n')
            with patch.object(Path, 'home', return_value=Path(home)):
                self.assertEqual(mod.read_profile('example'), {
                    'user': 'developer', 'home': '/home/developer', 'shell': '/bin/bash'})


if __name__ == '__main__':
    unittest.main()
