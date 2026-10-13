"""OS credential stores. Never fall back to plaintext credential files."""

import ctypes
import ctypes.util
import subprocess
import sys


class CredentialStore:
    def __init__(self, account):
        self.account = account
        self.service = "local.personal-asis.coordinator"

    def _mac(self, secret=None):
        # Security.framework keeps secrets off subprocess argv and console output.
        lib = ctypes.CDLL(ctypes.util.find_library("Security"))
        core = ctypes.CDLL(ctypes.util.find_library("CoreFoundation"))
        service, account = self.service.encode(), self.account.encode()
        find = lib.SecKeychainFindGenericPassword
        find.argtypes = [ctypes.c_void_p, ctypes.c_uint32, ctypes.c_char_p,
                         ctypes.c_uint32, ctypes.c_char_p, ctypes.POINTER(ctypes.c_uint32),
                         ctypes.POINTER(ctypes.c_void_p), ctypes.POINTER(ctypes.c_void_p)]
        find.restype = ctypes.c_int32
        free = lib.SecKeychainItemFreeContent
        free.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
        release = core.CFRelease
        release.argtypes = [ctypes.c_void_p]
        length, data, item = ctypes.c_uint32(), ctypes.c_void_p(), ctypes.c_void_p()
        status = find(None, len(service), service, len(account), account,
                      ctypes.byref(length), ctypes.byref(data), ctypes.byref(item))
        try:
            if secret is None:
                if status != 0:
                    raise ValueError("系统凭据库中没有可用的节点凭据，或钥匙串未解锁")
                return ctypes.string_at(data, length.value).decode()
            raw = secret.encode()
            if status == 0:
                modify = lib.SecKeychainItemModifyAttributesAndData
                modify.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_uint32, ctypes.c_char_p]
                modify.restype = ctypes.c_int32
                status = modify(item, None, len(raw), raw)
            elif status == -25300:  # errSecItemNotFound
                add = lib.SecKeychainAddGenericPassword
                add.argtypes = [ctypes.c_void_p, ctypes.c_uint32, ctypes.c_char_p,
                                ctypes.c_uint32, ctypes.c_char_p, ctypes.c_uint32,
                                ctypes.c_char_p, ctypes.c_void_p]
                add.restype = ctypes.c_int32
                status = add(None, len(service), service, len(account), account, len(raw), raw, None)
            if status != 0:
                raise ValueError("系统凭据库存储失败，请检查钥匙串权限")
        finally:
            if data.value:
                free(None, data)
            if item.value:
                release(item)

    def get(self):
        if sys.platform == "darwin":
            return self._mac()
        result = subprocess.run(["secret-tool", "lookup", "service", self.service, "account", self.account],
                                capture_output=True, check=True)
        secret = result.stdout.decode().strip()
        if not secret:
            raise ValueError("Secret Service 中没有节点凭据")
        return secret

    def set(self, secret):
        if sys.platform == "darwin":
            self._mac(secret)
        else:
            subprocess.run(["secret-tool", "store", "--label=Personal Asis node",
                            "service", self.service, "account", self.account],
                           input=secret.encode(), capture_output=True, check=True)
