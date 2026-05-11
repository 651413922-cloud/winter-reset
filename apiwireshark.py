import pyshark
from collections import defaultdict
import json
import re

# =========================
# 配置区
# =========================
PCAP_FILE = "vpn.pcap"

# =========================
# 工具函数
# =========================

def safe_get(obj, attr, default=""):
    try:
        return getattr(obj, attr, default) or default
    except:
        return default


def extract_http_packets(pcap_file):
    """
    从 pcap 中提取 HTTP 请求
    """
    cap = pyshark.FileCapture(pcap_file, display_filter="http")

    requests = []

    for packet in cap:
        try:
            http = packet.http

            method = safe_get(http, "request_method")
            host = safe_get(http, "host")
            uri = safe_get(http, "request_uri")

            if method and uri:
                url = f"http://{host}{uri}"

                requests.append({
                    "method": method,
                    "host": host,
                    "uri": uri,
                    "url": url
                })

        except:
            continue

    cap.close()
    return requests


def classify_api(requests):
    """
    按路径简单分类 API
    """
    api_map = defaultdict(list)

    for req in requests:
        path = req["uri"]

        # 粗粒度分类规则
        if "connect" in path:
            key = "connect"
        elif "line" in path or "server" in path:
            key = "line_list"
        elif "status" in path:
            key = "status"
        elif "test" in path:
            key = "heartbeat"
        else:
            key = "other"

        api_map[key].append(req)

    return api_map


def generate_sdk(api_map):
    """
    生成 Python SDK 代码
    """
    code = []

    code.append("import requests\n")
    code.append("# =========================")
    code.append("# AUTO GENERATED SDK")
    code.append("# =========================\n")

    for api_name, reqs in api_map.items():

        sample = reqs[0]

        method = sample["method"]
        url = sample["url"]

        func_name = re.sub(r"[^a-zA-Z0-9_]", "_", api_name)

        if method == "GET":
            func = f"""
def {func_name}():
    \"\"\"Auto generated from pcap\"\"\"
    url = "{url}"
    return requests.get(url)
"""
        else:
            func = f"""
def {func_name}(data=None):
    \"\"\"Auto generated from pcap\"\"\"
    url = "{url}"
    return requests.post(url, json=data)
"""

        code.append(func)

    return "\n".join(code)


def save_sdk(code, filename="generated_sdk.py"):
    with open(filename, "w", encoding="utf-8") as f:
        f.write(code)


# =========================
# 主流程
# =========================

def main():
    print("[1] 解析 pcap...")
    requests = extract_http_packets(PCAP_FILE)

    print(f"[+] 捕获 HTTP 请求数量: {len(requests)}")

    print("[2] 分类 API...")
    api_map = classify_api(requests)

    for k, v in api_map.items():
        print(f" - {k}: {len(v)} 条")

    print("[3] 生成 SDK...")
    code = generate_sdk(api_map)

    save_sdk(code)

    print("[✓] 已生成 generated_sdk.py")


if __name__ == "__main__":
    main()