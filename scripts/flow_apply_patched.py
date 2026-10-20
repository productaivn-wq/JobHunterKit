import runpy
import socket
import struct
import sys

import psycopg2

# Save original getaddrinfo
original_getaddrinfo = socket.getaddrinfo


def resolve_dns_raw(hostname, dns_server="8.8.8.8"):
    # If it is already an IP, return it
    try:
        socket.inet_aton(hostname)
        return hostname
    except OSError:
        pass

    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.settimeout(3.0)

        # Build standard query
        pkt = struct.pack(">HHHHHH", 0x1234, 0x0100, 1, 0, 0, 0)
        for part in hostname.split("."):
            pkt += struct.pack("B", len(part)) + part.encode("utf-8")
        pkt += struct.pack(">BHH", 0, 1, 1)

        s.sendto(pkt, (dns_server, 53))
        data, _ = s.recvfrom(1024)

        idx = 12
        while True:
            label_len = data[idx]
            if label_len == 0:
                idx += 5
                break
            idx += 1 + label_len

        # Parse answer section
        answers_count = struct.unpack(">H", data[6:8])[0]
        curr_idx = idx
        for _ in range(answers_count):
            if data[curr_idx] & 0xC0 == 0xC0:
                curr_idx += 2
            else:
                while True:
                    lbl_len = data[curr_idx]
                    if lbl_len == 0:
                        curr_idx += 1
                        break
                    curr_idx += 1 + lbl_len

            atype, aclass, attl, ardlen = struct.unpack(
                ">HHIH", data[curr_idx : curr_idx + 10]
            )
            curr_idx += 10

            if atype == 1:  # A record
                ip = ".".join(map(str, data[curr_idx : curr_idx + ardlen]))
                return ip

            curr_idx += ardlen
    except Exception as e:
        print(f"[DNS Patch] Failed to resolve {hostname}: {e}")
    return None


# Mapping cache with hardcoded Supabase pooler IP resolved from Google DNS
DNS_CACHE = {
    "aws-1-ap-southeast-1.pooler.supabase.com": "13.213.241.248",
    "postgres.vnjekvlwaqmsgboknohm": "13.213.241.248",
}


def custom_getaddrinfo(host, port, family=0, type=0, proto=0, flags=0):
    if host in DNS_CACHE:
        return original_getaddrinfo(DNS_CACHE[host], port, family, type, proto, flags)

    try:
        return original_getaddrinfo(host, port, family, type, proto, flags)
    except socket.gaierror:
        # Fallback to direct raw DNS resolution via Google DNS
        print(f"[DNS Patch] OS lookup failed for {host}. Attempting direct DNS...")
        ip = resolve_dns_raw(host)
        if ip:
            DNS_CACHE[host] = ip
            print(f"[DNS Patch] Resolved {host} to {ip}")
            return original_getaddrinfo(ip, port, family, type, proto, flags)
        raise


socket.getaddrinfo = custom_getaddrinfo

# Optional job-id parsing
target_job_id = None
new_argv = []
for arg in sys.argv:
    if arg.startswith("--job-id="):
        target_job_id = arg.split("=")[1]
    elif arg == "--job-id" and len(sys.argv) > sys.argv.index(arg) + 1:
        # We will handle it in the next pass
        pass
    else:
        # Check if the previous was --job-id
        idx = sys.argv.index(arg)
        if idx > 0 and sys.argv[idx - 1] == "--job-id":
            target_job_id = arg
        else:
            new_argv.append(arg)

sys.argv = new_argv

if target_job_id:
    print(f"[Job-ID Patch] Targeting job ID: {target_job_id}")

    # Subclass psycopg2 connection to override the cursor method
    class CustomConnection(psycopg2.extensions.connection):
        def cursor(self, *args, **kwargs):
            factory = psycopg2.extensions.cursor
            if len(args) > 1:
                if args[1] is not None:
                    factory = args[1]
            elif "cursor_factory" in kwargs:
                if kwargs["cursor_factory"] is not None:
                    factory = kwargs["cursor_factory"]

            class CustomCursor(factory):
                def execute(self, query, vars=None):
                    if (
                        isinstance(query, str)
                        and "FROM job_hunter.jobs" in query
                        and "status_apply = 'pending'" in query
                    ):
                        # Inject ID filter and bypass status check only for initial pending/applying state
                        query = query.replace(
                            "status_apply = 'pending'",
                            f"id = {int(target_job_id)} AND (status_apply = 'pending' OR status_apply = 'applying')",
                        )
                        print(f"[Job-ID Patch] Modified SQL: {query}")
                    return super().execute(query, vars)

            if len(args) > 1:
                args = list(args)
                args[1] = CustomCursor
                args = tuple(args)
            else:
                kwargs["cursor_factory"] = CustomCursor

            return super().cursor(*args, **kwargs)

    # Monkeypatch psycopg2.connect to use CustomConnection
    original_connect = psycopg2.connect

    def patched_connect(*args, **kwargs):
        has_factory = (len(args) > 1 and args[1] is not None) or kwargs.get(
            "connection_factory"
        ) is not None
        if not has_factory:
            kwargs["connection_factory"] = CustomConnection
        return original_connect(*args, **kwargs)

    psycopg2.connect = patched_connect

if __name__ == "__main__":
    print("[DNS Patch] Applied socket.getaddrinfo monkeypatch successfully.")
    sys.argv[0] = "flow_apply.py"
    runpy.run_path("scripts/flow_apply.py", run_name="__main__")
