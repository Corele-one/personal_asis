import base64
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

from personal_asis.backup import create, restore
from personal_asis.config import load_config
from personal_asis.credentials import CredentialNotFound
from personal_asis.index import Index


class MemoryKeyStore:
    value = None
    def get(self):
        if self.value is None:
            raise CredentialNotFound("missing")
        return self.value
    def set(self, value):
        self.value = value


@unittest.skipUnless(importlib.util.find_spec("cryptography"), "requires backup dependency")
class BackupTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.home = self.base / "runtime"
        self.home.mkdir()
        source = self.base / "originals"
        source.mkdir()
        (source / "private.md").write_text("# Synthetic backup canary\nBACKUP_PRIVATE_TEXT_CANARY\n")
        (self.home / "sources.yaml").write_text(json.dumps({"node_id":"rog", "sources":[
            {"id":"private", "root":str(source), "policy":"private"}]}))
        with Index(self.home / "index.sqlite3", load_config(self.home / "sources.yaml")) as index:
            index.reconcile()
            self.original_id = index.search("BACKUP_PRIVATE_TEXT_CANARY")["results"][0]["replicas"][0]["document_id"]
        self.store = MemoryKeyStore()

    def test_authenticated_encryption_and_restore_preserves_identity_and_search(self):
        result = create(self.home, self.base / "backup", self.store)
        archive = Path(result["path"])
        self.assertNotIn(b"BACKUP_PRIVATE_TEXT_CANARY", archive.read_bytes())
        self.assertNotIn(str(self.base).encode(), archive.read_bytes())
        restored = self.base / "restored"
        restore(archive, restored, self.store)
        self.assertEqual(set(p.name for p in restored.iterdir()), {"sources.yaml", "index.sqlite3"})
        with Index(restored / "index.sqlite3", load_config(restored / "sources.yaml")) as index:
            self.assertEqual(index.search("BACKUP_PRIVATE_TEXT_CANARY")["results"][0]["replicas"][0]["document_id"], self.original_id)
        self.assertTrue((self.base / "originals/private.md").is_file())

    def test_wrong_key_and_modified_ciphertext_expose_no_restored_files(self):
        archive = Path(create(self.home, self.base / "backup", self.store)["path"])
        wrong = MemoryKeyStore()
        wrong.value = base64.urlsafe_b64encode(b"x" * 32).decode()
        with self.assertRaisesRegex(ValueError, "认证失败"):
            restore(archive, self.base / "wrong", wrong)
        changed = bytearray(archive.read_bytes())
        changed[30] ^= 1
        archive.write_bytes(changed)
        with self.assertRaisesRegex(ValueError, "认证失败"):
            restore(archive, self.base / "tampered", self.store)
        self.assertFalse((self.base / "wrong").exists())
        self.assertFalse((self.base / "tampered").exists())
        self.assertFalse(list(self.base.glob("asis-restore-*")))

    def test_nonempty_target_is_never_overwritten_and_recovery_key_works(self):
        archive = Path(create(self.home, self.base / "backup", self.store)["path"])
        target = self.base / "existing"
        target.mkdir()
        (target / "keep").write_text("preserve")
        with self.assertRaisesRegex(ValueError, "空目录"):
            restore(archive, target, self.store)
        self.assertEqual((target / "keep").read_text(), "preserve")
        result = restore(archive, self.base / "offline-key", recovery_key=self.store.value)
        self.assertTrue(result["restored"])

    def test_unavailable_store_never_rotates_the_backup_key(self):
        class Unavailable:
            def get(self): raise ValueError("locked store")
            def set(self, value): raise AssertionError("must not overwrite an existing key")
        with self.assertRaisesRegex(ValueError, "locked store"):
            create(self.home, self.base / "backup", Unavailable())
        self.assertFalse((self.base / "backup").exists())

    def test_git_target_and_symlinked_state_are_rejected(self):
        checkout = self.base / "checkout"
        (checkout / ".git").mkdir(parents=True)
        with self.assertRaisesRegex(ValueError, "Git"):
            create(self.home, checkout / "backup", self.store)
        (self.home / "source-permissions.json").symlink_to(self.base / "originals/private.md")
        with self.assertRaisesRegex(ValueError, "符号链接"):
            create(self.home, self.base / "backup", self.store)
