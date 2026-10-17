"""Fernet 对称加密：API Key 加密落库、解密使用与掩码展示。

参考「平台托管 + 用户自配」模式：数据库永远不存明文密钥，
明文只在服务端调用模型或连通性测试时短暂解密，接口一律回传掩码。
"""
from __future__ import annotations

from cryptography.fernet import Fernet, InvalidToken


def generate_master_key() -> str:
    """生成 Fernet 主密钥（url-safe base64，32 字节），供首次落库 app_meta 使用。"""
    return Fernet.generate_key().decode("ascii")


class SecretBox:
    """用主密钥初始化的加解密器；主密钥来自环境变量或数据库 app_meta。"""

    def __init__(self, master_key: str) -> None:
        self._fernet = Fernet(master_key.encode("ascii"))

    def encrypt(self, plaintext: str) -> str:
        # 加密后再入库，数据库文件与日志中不出现明文密钥
        return self._fernet.encrypt(plaintext.encode("utf-8")).decode("ascii")

    def decrypt(self, ciphertext: str) -> str:
        try:
            return self._fernet.decrypt(ciphertext.encode("ascii")).decode("utf-8")
        except (InvalidToken, ValueError) as exc:
            # 主密钥更换或密文损坏时明确报错，不静默返回错误密钥
            raise ValueError("密钥解密失败：加密主密钥与存储密文不匹配") from exc


def mask_key(api_key: str) -> str:
    """掩码规则：保留前 3 位与后 4 位，中间以 **** 代替；过短时全掩码。"""
    if not api_key:
        return ""
    if len(api_key) <= 8:
        return "****"
    return api_key[:3] + "****" + api_key[-4:]
