import pyshark

pcap_file = "vpn.pcap"

cap = pyshark.FileCapture(pcap_file, display_filter="http")

apis = []

for packet in cap:
    try:
        http = packet.http

        method = getattr(http, "request_method", None)
        host = getattr(http, "host", "")
        uri = getattr(http, "request_uri", "")

        if method and uri:
            api = {
                "method": method,
                "url": f"http://{host}{uri}"
            }
            apis.append(api)

    except:
        pass

for a in apis:
    print(a)