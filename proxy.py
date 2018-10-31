import thread
import socket
import sys
import os
import time
import json
import threading
import datetime

# global variables
max_no_conn = 10
bufferSize = 4096
cacheDirectory = "./cache"
maxCacheSize = 3
cacheLimit = 2

# take command line argument
if len(sys.argv) != 2:
    print "Usage: python %s <PROXY_PORT>" % sys.argv[0]
    print "Example: python %s 20000" % sys.argv[0]
    raise SystemExit

try:
    proxy_port = int(sys.argv[1])
except:
    print "provide proper port number"
    raise SystemExit

if not os.path.isdir(cacheDirectory):
    os.makedirs(cacheDirectory)

# lock fileurl
def get_access(fileurl):
    if fileurl in locks:
        lock = locks[fileurl]
    else:
        lock = threading.Lock()
        locks[fileurl] = lock
    lock.acquire()

# unlock fileurl
def leave_access(fileurl):
    if fileurl in locks:
        lock = locks[fileurl]
        lock.release()
    else:
        print "Lock problem"
        sys.exit()


# add fileurl entry to log
def add_log(fileurl, client_addr):
    fileurl = fileurl.replace("/", "__")
    if not fileurl in logs:
        logs[fileurl] = []
    dt = time.strptime(time.ctime(), "%a %b %d %H:%M:%S %Y")
    logs[fileurl].append({
            "datetime" : dt,
            "client" : json.dumps(client_addr),
        })
    #print logs[fileurl]

# decide whether to cache or not
def do_cache_or_not(fileurl):
    try:
        log_arr = logs[fileurl.replace("/", "__")]
        if len(log_arr) < cacheLimit :
            return False
        last_third = log_arr[len(log_arr)-cacheLimit]["datetime"]
        if datetime.datetime.fromtimestamp(time.mktime(last_third)) + datetime.timedelta(minutes=10) >= datetime.datetime.now():
            print("check")
            return True
        else:
            return False
    except Exception as e:
        print e
        return False

# check whether file is already cached or not
def get_current_cache_info(fileurl):

    if fileurl.startswith("/"):
        fileurl = fileurl.replace("/", "", 1)

    cache_path = cacheDirectory + "/" + fileurl.replace("/", "__")

    if os.path.isfile(cache_path):
        last_mod_time = time.strptime(time.ctime(os.path.getmtime(cache_path)), "%a %b %d %H:%M:%S %Y")
        return cache_path, last_mod_time
    else:
        return cache_path, None


# collect all cache info
def get_cache_details(client_addr, details):
    get_access(details["total_url"])
    add_log(details["total_url"], client_addr)
    do_cache = do_cache_or_not(details["total_url"])
    cache_path, last_mod_time = get_current_cache_info(details["total_url"])
    leave_access(details["total_url"])
    details["do_cache"] = do_cache
    details["cache_path"] = cache_path
    details["last_mod_time"] = last_mod_time
    return details


# if cache is full then delete the least recently used cache item
def get_space_for_cache(fileurl):
    cache_files = os.listdir(cacheDirectory)
    if len(cache_files) < maxCacheSize:
        return
    for file in cache_files:
        get_access(file)

    last_mod_time = min(logs[file][-1]["datetime"] for file in cache_files)
    file_to_del = [file for file in cache_files if logs[file][-1]["datetime"] == last_mod_time][0]

    os.remove(cacheDirectory + "/" + file_to_del)
    for file in cache_files:
        leave_access(file)


# returns a dictionary of details
def parse_details(client_addr, client_data):
    try:

        lines = client_data.splitlines()
        while lines[len(lines)-1] == '':
            lines.remove('')
        first_line_tokens = lines[0].split()
        url = first_line_tokens[1]

        # get starting index of IP
        url_pos = url.find("://")
        if url_pos != -1:
            protocol = url[:url_pos]
            url = url[(url_pos+3):]
        else:
            protocol = "http"

        # get port if any
        # get url path
        port_pos = url.find(":")
        path_pos = url.find("/")
        if path_pos == -1:
            path_pos = len(url)


        # change request path accordingly
        if port_pos==-1 or path_pos < port_pos:
            server_port = 80
            server_url = url[:path_pos]
        else:
            server_port = int(url[(port_pos+1):path_pos])
            server_url = url[:port_pos]

        # build up request for server
        first_line_tokens[1] = url[path_pos:]
        lines[0] = ' '.join(first_line_tokens)
        client_data = "\r\n".join(lines) + '\r\n\r\n'

        return {
            "server_port" : server_port,
            "server_url" : server_url,
            "total_url" : url,
            "client_data" : client_data,
            "protocol" : protocol,
            "method" : first_line_tokens[0],
        }

    except Exception as e:
        print e
        print
        return None



# insert the header
def insert_if_modified(details):

    lines = details["client_data"].splitlines()
    while lines[len(lines)-1] == '':
        lines.remove('')

    #header = "If-Modified-Since: " + time.strptime("%a %b %d %H:%M:%S %Y", details["last_mod_time"])
    header = time.strftime("%a %b %d %H:%M:%S %Y", details["last_mod_time"])
    header = "If-Modified-Since: " + header
    lines.append(header)

    details["client_data"] = "\r\n".join(lines) + "\r\n\r\n"
    return details


# serve get request
def serve_get(client_socket, client_addr, details):
    try:
        #print details["client_data"], details["do_cache"], details["cache_path"], details["last_mod_time"]
        client_data = details["client_data"]
        do_cache = details["do_cache"]
        cache_path = details["cache_path"]
        last_mod_time = details["last_mod_time"]

        server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        server_socket.connect((details["server_url"], details["server_port"]))
        server_socket.send(details["client_data"])

        reply = server_socket.recv(bufferSize)
        if last_mod_time and "304 Not Modified" in reply:
            print (reply)
            print "returning cached file %s to %s" % (cache_path, str(client_addr))
            get_access(details["total_url"])
            f = open(cache_path, 'rb')
            chunk = f.read(bufferSize)
            while chunk:
                client_socket.send(chunk)
                chunk = f.read(bufferSize)
            f.close()
            leave_access(details["total_url"])

        else:
            if do_cache:
                print (reply)
                print "caching file while serving %s to %s" % (cache_path, str(client_addr))
                get_space_for_cache(details["total_url"])
                get_access(details["total_url"])
                f = open(cache_path, "w+")
                # print len(reply), reply
                while len(reply):
                    client_socket.send(reply)
                    f.write(reply)
                    reply = server_socket.recv(bufferSize)
                    #print len(reply), reply
                f.close()
                leave_access(details["total_url"])
                client_socket.send("\r\n\r\n")
            else:
                print (reply)
                print "without caching serving %s to %s" % (cache_path, str(client_addr))
                #print len(reply), reply
                while len(reply):
                    client_socket.send(reply)
                    reply = server_socket.recv(bufferSize)
                    #print len(reply), reply
                client_socket.send("\r\n\r\n")

        server_socket.close()
        client_socket.close()
        return

    except Exception as e:
        server_socket.close()
        client_socket.close()
        print e
        return


# A thread function to handle one request
def handle_one_request_(client_socket, client_addr, client_data):

    details = parse_details(client_addr, client_data)

    if not details:
        print "no details"
        client_socket.close()
        return

    elif details["method"] == "GET":
        details = get_cache_details(client_addr, details)
        if details["last_mod_time"]:
            details = insert_if_modified(details)
        serve_get(client_socket, client_addr, details)


    client_socket.close()
    print client_addr, "closed"
    print

# This funciton initializes socket and starts listening.
# When connection request is made, a new thread is created to serve the request
def start_proxy_server():

    # Initialize socket
    try:
        proxy_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        proxy_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        proxy_socket.bind(('', proxy_port))
        proxy_socket.listen(max_no_conn)

        print "Serving proxy on %s port %s ..." % (
            str(proxy_socket.getsockname()[0]),
            str(proxy_socket.getsockname()[1])
            )

    except Exception as e:
        print "Error in starting proxy server ..."
        print e
        proxy_socket.close()
        raise SystemExit


    # Main server loop
    while True:
        try:
            client_socket, client_addr = proxy_socket.accept()
            client_data = client_socket.recv(bufferSize)

            print
            print "%s - - [%s] \"%s\"" % (
                str(client_addr),
                str(datetime.datetime.now()),
                client_data.splitlines()[0]
                )

            thread.start_new_thread(
                handle_one_request_,
                (
                    client_socket,
                    client_addr,
                    client_data
                )
            )

        except KeyboardInterrupt:
            client_socket.close()
            proxy_socket.close()
            print "\nProxy server shutting down ...\n"
            break


logs = {}
locks = {}
start_proxy_server()
