"""ProfileItem 数据模型 - 对应 SQLite ProfileItem 表"""

from dataclasses import dataclass, field
from typing import Optional
import json


@dataclass
class ProfileItem:
    """一个 VPN 节点配置"""
    index_id: str
    config_type: int
    core_type: Optional[int]
    config_version: int
    sub_id: Optional[str]
    is_sub: int
    pre_socks_port: Optional[int]
    display_log: int
    remarks: str
    address: str
    port: int
    password: str          # 实际是 UUID
    username: str
    network: str
    header_type: str
    request_host: str
    path: str
    stream_security: str   # tls / none
    allow_insecure: str
    sni: str
    alpn: str
    fingerprint: str
    public_key: str
    short_id: str
    spider_x: str
    extra: str             # JSON
    mux_enabled: int
    cert: str
    cert_sha: str
    echo_config_list: str
    final_mask: str
    proto_extra: str       # JSON - 包含 Flow, VlessEncryption 等
    transport_extra: str   # JSON - 包含 Host, Path, 传输配置
    ports: str
    alter_id: int
    flow: str
    profile_id: str        # 表中列名叫 Id
    security: str

    @property
    def proto_extra_dict(self) -> dict:
        if not self.proto_extra:
            return {}
        try:
            return json.loads(self.proto_extra)
        except json.JSONDecodeError:
            return {}

    @property
    def transport_extra_dict(self) -> dict:
        if not self.transport_extra:
            return {}
        try:
            return json.loads(self.transport_extra)
        except json.JSONDecodeError:
            return {}

    @property
    def effective_path(self) -> str:
        te = self.transport_extra_dict
        if te.get('Path'):
            return te['Path']
        return self.path

    @property
    def effective_host(self) -> str:
        te = self.transport_extra_dict
        if te.get('Host'):
            return te['Host']
        return self.request_host

    @property
    def effective_flow(self) -> str:
        pe = self.proto_extra_dict
        if pe.get('Flow'):
            return pe['Flow']
        return self.flow or ''

    @property
    def vless_encryption(self) -> str:
        """仅 VLESS+Vision 需要此密钥"""
        pe = self.proto_extra_dict
        return pe.get('VlessEncryption', '')

    def display(self) -> str:
        return (f"[{self.remarks}] {self.address}:{self.port} "
                f"| {self.stream_security} | {self.network}")


def _safe(row, key, default=''):
    """安全获取字段，兼容不同版本 v2rayN 数据库 schema"""
    try:
        val = row[key]
        return val if val is not None else default
    except (IndexError, KeyError):
        return default


def profile_from_db_row(row) -> ProfileItem:
    """从 sqlite3.Row 构建 ProfileItem"""
    return ProfileItem(
        index_id=_safe(row, 'IndexId'),
        config_type=_safe(row, 'ConfigType', 0),
        core_type=_safe(row, 'CoreType', None),
        config_version=_safe(row, 'ConfigVersion', 0),
        sub_id=_safe(row, 'Subid', None),
        is_sub=_safe(row, 'IsSub', 0),
        pre_socks_port=_safe(row, 'PreSocksPort', None),
        display_log=_safe(row, 'DisplayLog', 0),
        remarks=_safe(row, 'Remarks'),
        address=_safe(row, 'Address'),
        port=_safe(row, 'Port', 0),
        password=_safe(row, 'Password'),
        username=_safe(row, 'Username'),
        network=_safe(row, 'Network'),
        header_type=_safe(row, 'HeaderType'),
        request_host=_safe(row, 'RequestHost'),
        path=_safe(row, 'Path'),
        stream_security=_safe(row, 'StreamSecurity'),
        allow_insecure=_safe(row, 'AllowInsecure'),
        sni=_safe(row, 'Sni'),
        alpn=_safe(row, 'Alpn'),
        fingerprint=_safe(row, 'Fingerprint'),
        public_key=_safe(row, 'PublicKey'),
        short_id=_safe(row, 'ShortId'),
        spider_x=_safe(row, 'SpiderX'),
        extra=_safe(row, 'Extra'),
        mux_enabled=_safe(row, 'MuxEnabled', 0),
        cert=_safe(row, 'Cert'),
        cert_sha=_safe(row, 'CertSha'),
        echo_config_list=_safe(row, 'EchConfigList'),
        final_mask=_safe(row, 'Finalmask'),
        proto_extra=_safe(row, 'ProtoExtra'),
        transport_extra=_safe(row, 'TransportExtra'),
        ports=_safe(row, 'Ports'),
        alter_id=_safe(row, 'AlterId', 0),
        flow=_safe(row, 'Flow'),
        profile_id=_safe(row, 'Id'),
        security=_safe(row, 'Security'),
    )