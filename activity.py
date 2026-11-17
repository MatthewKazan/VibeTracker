"""Process-wide admission, cancellation and sleeping for low-resource mode."""
import contextlib
import threading
import time

class Paused(ValueError):pass
LOCK=threading.RLock()
RUNNING=threading.Event();RUNNING.set()
STOP=threading.Event()
EPOCH=0
CANCEL={}
UNLOAD_ERROR=''
READY=threading.Event();READY.set()
STARTUP_UNTIL=0
STARTUP_TIMER=None

def paused():return not RUNNING.is_set()
def ticket():
    with LOCK:
        check();return EPOCH

def check(epoch=None):
    if paused() or epoch is not None and epoch!=EPOCH:raise Paused('Low-resource mode is on. Resume background activity to use AI, syncing or background web activity.')

def configure(value):
    global EPOCH,UNLOAD_ERROR
    with LOCK:
        EPOCH+=1;UNLOAD_ERROR=''
        if value:RUNNING.clear();STOP.set()
        else:STOP.clear();RUNNING.set()
        callbacks=list(CANCEL.values()) if value else []
    for callback in callbacks:
        try:callback()
        except Exception:pass

def startup_grace(seconds=30):
    global STARTUP_UNTIL,STARTUP_TIMER
    if STARTUP_TIMER:STARTUP_TIMER.cancel()
    STARTUP_UNTIL=time.monotonic()+seconds;READY.clear()
    STARTUP_TIMER=threading.Timer(seconds,READY.set);STARTUP_TIMER.daemon=True;STARTUP_TIMER.start()

def wait(seconds=0):
    READY.wait()
    RUNNING.wait()
    return not STOP.wait(seconds) and not paused()

@contextlib.contextmanager
def cancellable(callback,epoch=None):
    key=object()
    with LOCK:
        if paused() or epoch is not None and epoch!=EPOCH:
            callback();check(epoch)
        CANCEL[key]=callback
    try:yield
    finally:
        with LOCK:CANCEL.pop(key,None)

def result():return {'paused':paused(),'unload_error':UNLOAD_ERROR,'startup_remaining':max(0,STARTUP_UNTIL-time.monotonic())}

def run_process(args,*,input=None,capture_output=False,text=False,timeout=None,**kwargs):
    import subprocess,time
    epoch=ticket();process=subprocess.Popen(args,stdin=subprocess.PIPE if input is not None else None,stdout=subprocess.PIPE if capture_output else None,stderr=subprocess.PIPE if capture_output else None,text=text,**kwargs)
    def stop():
        if process.poll() is None:process.terminate()
    started=time.monotonic();sent=False
    try:
        with cancellable(stop,epoch):
            while True:
                check(epoch)
                if timeout and time.monotonic()-started>timeout:raise subprocess.TimeoutExpired(args,timeout)
                try:
                    out,err=process.communicate(input=input if not sent else None,timeout=.1);check(epoch)
                    return subprocess.CompletedProcess(args,process.returncode,out,err)
                except subprocess.TimeoutExpired:sent=True
    finally:
        if process.poll() is None:
            process.terminate()
            try:process.communicate(timeout=1)
            except subprocess.TimeoutExpired:process.kill();process.communicate()

@contextlib.contextmanager
def open_url(request,timeout=20,handlers=()):
    """Close active response sockets when the user pauses, including reads in progress."""
    import urllib.request,http.client,socket
    epoch=ticket()
    with contextlib.ExitStack() as stack:
        def factory(kind):
            def create(host,**kwargs):
                connection=kind(host,**kwargs);original=connection.connect
                def connect_socket():
                    check(epoch);original();sock=connection.sock
                    def cancel():
                        try:sock.shutdown(socket.SHUT_RDWR)
                        except OSError:pass
                        connection.close()
                    stack.enter_context(cancellable(cancel,epoch));check(epoch)
                connection.connect=connect_socket;return connection
            return create
        class HTTP(urllib.request.HTTPHandler):
            def http_open(self,req):return self.do_open(factory(http.client.HTTPConnection),req)
        class HTTPS(urllib.request.HTTPSHandler):
            def https_open(self,req):return self.do_open(factory(http.client.HTTPSConnection),req)
        try:
            check(epoch)
            with urllib.request.build_opener(*handlers,HTTP,HTTPS).open(request,timeout=timeout) as response:
                yield response
                check(epoch)
        except Exception:check(epoch);raise
