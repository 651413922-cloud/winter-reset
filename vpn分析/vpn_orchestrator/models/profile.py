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


def profile_from_db_row(row) -> ProfileItem:
    """从 sqlite3.Row 构建 ProfileItem"""
    return ProfileItem(
        index_id=row['IndexId'],
        config_type=row['ConfigType'],
        core_type=row['CoreType'],
        config_version=row['ConfigVersion'],
        sub_id=row['Subid'],
        is_sub=row['IsSub'],
        pre_socks_port=row['PreSocksPort'],
        display_log=row['DisplayLog'],
        remarks=row['Remarks'],
        address=row['Address'],
        port=row['Port'],
        password=row['Password'],
        username=row['Username'],
        network=row['Network'],
        header_type=row['HeaderType'],
        request_host=row['RequestHost'],
        path=row['Path'],
        stream_security=row['StreamSecurity'],
        allow_insecure=row['AllowInsecure'],
        sni=row['Sni'],
        alpn=row['Alpn'],
        fingerprint=row['Fingerprint'],
        public_key=row['PublicKey'],
        short_id=row['ShortId'],
        spider_x=row['SpiderX'],
        extra=row['Extra'] or '',
        mux_enabled=row['MuxEnabled'],
        cert=row['Cert'] or '',
        cert_sha=row['CertSha'] or '',
        echo_config_list=row['EchConfigList'] or '',
        final_mask=row['Finalmask'] or '',
        proto_extra=row['ProtoExtra'] or '',
        transport_extra=row['TransportExtra'] or '',
        ports=row['Ports'] or '',
        alter_id=row['AlterId'],
        flow=row['Flow'] or '',
        profile_id=row['Id'] or '',
        security=row['Security'] or '',
    )