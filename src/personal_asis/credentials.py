"""OS credential stores. Never fall back to plaintext credential files."""

import ctypes
import ctypes.util
import json
import os
from pathlib import Path
import platform
import subprocess
import sys


class CredentialNotFound(ValueError):
    pass


class CredentialStore:
    def __init__(self, account, service="local.personal-asis.coordinator"):
        self.account = account
        self.service = service

    def _windows_wsl(self, secret=None):
        # Use Windows Credential Manager, never a plaintext file or argv secret.
        bridge = Path(__file__).with_name("wincred.ps1")
        path = subprocess.run(["wslpath", "-w", str(bridge.resolve())],
                              capture_output=True, check=True, timeout=10).stdout.decode().strip()
        env = os.environ.copy()
        # The systemd user manager has no interactive WSL_INTEROP environment.
        if not env.get("WSL_INTEROP") or not Path(env["WSL_INTEROP"]).exists():
            env["WSL_INTEROP"] = "/run/WSL/1_interop"
        request = {"service": self.service, "account": self.account,
                   "action": "get" if secret is None else "set"}
        if secret is not None:
            request["secret"] = secret
        result = subprocess.run([
            "/mnt/c/Windows/System32/WindowsPowerShell/v1.0/powershell.exe",
            "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-File", path],
            input=json.dumps(request).encode(), capture_output=True, env=env, timeout=30)
        if result.returncode == 3:
            raise CredentialNotFound("系统凭据库中没有此凭据")
        if result.returncode:
            raise ValueError("Windows 凭据管理器不可用或没有节点凭据")
        try:
            response = json.loads(result.stdout.decode("utf-8-sig"))
            if secret is None:
                value = response["secret"]
                if not isinstance(value, str) or not value:
                    raise ValueError()
                return value
        except (ValueError, KeyError, UnicodeError) as exc:
            raise ValueError("Windows 凭据管理器返回无效响应") from exc

    @staticmethod
    def _is_wsl():
        return sys.platform == "linux" and "microsoft" in platform.release().lower()

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
                if status == -25300:
                    raise CredentialNotFound("系统凭据库中没有此凭据")
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
        if self._is_wsl():
            return self._windows_wsl()
        result = subprocess.run(["secret-tool", "lookup", "service", self.service, "account", self.account],
                                capture_output=True)
        if result.returncode == 1 and not result.stdout and not result.stderr:
            raise CredentialNotFound("Secret Service 中没有此凭据")
        result.check_returncode()
        secret = result.stdout.decode().strip()
        if not secret:
            raise CredentialNotFound("Secret Service 中没有节点凭据")
        return secret

    def set(self, secret):
        if sys.platform == "darwin":
            self._mac(secret)
        elif self._is_wsl():
            self._windows_wsl(secret)
        else:
            subprocess.run(["secret-tool", "store", "--label=Personal Asis node",
                            "service", self.service, "account", self.account],
                           input=secret.encode(), capture_output=True, check=True)
